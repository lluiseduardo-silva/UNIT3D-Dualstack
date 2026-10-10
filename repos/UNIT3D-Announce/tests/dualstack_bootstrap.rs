use std::{env, time::{Duration, Instant}};
use sqlx::{Executor, MySqlPool, Row, mysql::MySqlPoolOptions};
use unit3d_announce::dualstack::{coordinator::{Coordinator, Credit, Error, Identity, Settings}, peer::{Announce, Event, Operation, Policy}};

async fn query_id(pool: &MySqlPool) -> Option<u64> {
    sqlx::query_scalar("SELECT ID FROM information_schema.PROCESSLIST WHERE ID<>CONNECTION_ID() AND DB=DATABASE() AND INFO LIKE 'UPDATE torrents t LEFT JOIN%' LIMIT 1")
        .fetch_optional(pool).await.unwrap()
}

async fn exists(pool: &MySqlPool, id: u64) -> bool {
    sqlx::query_scalar::<_,i64>("SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID=?")
        .bind(id).fetch_one(pool).await.unwrap()!=0
}

#[tokio::test(flavor="multi_thread",worker_threads=4)]
#[ignore="Exige MySQL real e banco isolado unit3d_dualstack_journal_test"]
async fn bootstrap_cancellation() {
    assert_eq!(env::var("DUALSTACK_MYSQL_TESTS").as_deref(),Ok("1"));
    let options=sqlx::mysql::MySqlConnectOptions::new().host("172.29.92.20")
        .username(&env::var("MYSQL_USER").unwrap()).password(&env::var("MYSQL_PASSWORD").unwrap())
        .database("unit3d_dualstack_journal_test");
    let pool=MySqlPoolOptions::new().max_connections(8).acquire_timeout(Duration::from_secs(3))
        .after_connect(|c,_| Box::pin(async move {
            sqlx::query("SET SESSION innodb_lock_wait_timeout=30").execute(c).await?; Ok(())
        })).connect_with(options.clone()).await.unwrap();
    assert_eq!(sqlx::query_scalar::<_,String>("SELECT DATABASE()").fetch_one(&pool).await.unwrap(),"unit3d_dualstack_journal_test");
    let grants=sqlx::query("SHOW GRANTS").fetch_all(&pool).await.unwrap().iter()
        .map(|r|r.get::<String,_>(0)).collect::<Vec<_>>().join("\n");
    assert!(!grants.contains("CONNECTION_ADMIN")&&!grants.contains("SUPER")&&!grants.contains("ALL PRIVILEGES ON *.*"));
    println!("PASS usuario SQL sem SUPER ou CONNECTION_ADMIN nos grants diretos");
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM tracker_ownership WHERE id=1").fetch_one(&pool).await.unwrap(),0);
    sqlx::query("DELETE FROM peers").execute(&pool).await.unwrap();
    sqlx::query("DELETE FROM history").execute(&pool).await.unwrap();
    sqlx::query("UPDATE torrents SET seeders=777").execute(&pool).await.unwrap();
    let settings=Settings {peer:Policy {allow_private_addresses:true,..Policy::default()},..Settings::default()};
    let mut blocker=pool.begin().await.unwrap();
    sqlx::query("SELECT id FROM torrents WHERE id=12001 FOR UPDATE").fetch_one(&mut *blocker).await.unwrap();
    let task={let pool=pool.clone();tokio::spawn(async move {Coordinator::open(pool,settings).await})};
    let id=tokio::time::timeout(Duration::from_secs(5),async {
        loop {if let Some(id)=query_id(&pool).await {break id;} tokio::time::sleep(Duration::from_millis(10)).await;}
    }).await.unwrap();
    assert!(matches!(Coordinator::open(pool.clone(),settings).await,
        Err(Error::Owned | Error::Timeout("aquisicao da lease"))));
    task.abort(); assert!(matches!(task.await,Err(error) if error.is_cancelled()));
    let started=Instant::now();
    let gone=tokio::time::timeout(Duration::from_secs(2),async {
        while exists(&pool,id).await {tokio::time::sleep(Duration::from_millis(20)).await;}
    }).await.is_ok();
    // Sempre limpar a conexao especifica do controle negativo, sem deixar SQL orfao.
    if !gone {pool.execute(format!("KILL CONNECTION {id}").as_str()).await.unwrap();}
    blocker.rollback().await.unwrap();
    tokio::time::timeout(Duration::from_secs(3),async {
        while exists(&pool,id).await {tokio::time::sleep(Duration::from_millis(20)).await;}
    }).await.unwrap();
    let modified:i64=sqlx::query_scalar("SELECT COUNT(*) FROM torrents WHERE seeders<>777").fetch_one(&pool).await.unwrap();
    let orphan_expected=env::var("DUALSTACK_EXPECT_ORPHAN").as_deref()==Ok("1");
    if orphan_expected {
        sqlx::query("UPDATE tracker_ownership SET lease_expires_at=UTC_TIMESTAMP(3) WHERE id=1 AND backend='rust'").execute(&pool).await.unwrap();
    }
    println!("CANCELLED_BOOTSTRAP connection_gone={gone} elapsed_ms={} rollback_modified={modified} negative_control={orphan_expected}",started.elapsed().as_millis());
    assert_eq!(gone,!orphan_expected);
    assert_eq!(modified,0);
    if !orphan_expected {
        tokio::time::timeout(Duration::from_secs(5),async {
            loop {
                let live:i64=sqlx::query_scalar("SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM tracker_ownership WHERE id=1").fetch_one(&pool).await.unwrap();
                if live==0 {break;} tokio::time::sleep(Duration::from_millis(20)).await;
            }
        }).await.unwrap();
        let c=Coordinator::open(pool.clone(),settings).await.unwrap();
        c.shutdown().await.unwrap();
        let row=sqlx::query("SELECT COUNT(*) AS n FROM torrents WHERE seeders<>0").fetch_one(&pool).await.unwrap();
        assert_eq!(row.get::<i64,_>("n"),0);

        // Timeout interno: a resposta so pode sair depois do rollback no servidor.
        sqlx::query("UPDATE torrents SET seeders=777").execute(&pool).await.unwrap();
        let mut lock=pool.begin().await.unwrap();
        sqlx::query("SELECT id FROM torrents WHERE id=12001 FOR UPDATE").fetch_one(&mut *lock).await.unwrap();
        let unrelated={let pool=pool.clone();tokio::spawn(async move {
            sqlx::query_scalar::<_,i64>("SELECT SLEEP(1)").fetch_one(&pool).await.unwrap()
        })};
        let started=Instant::now();
        let result=Coordinator::open_with_bootstrap_timeout(pool.clone(),settings,Duration::from_millis(250)).await;
        assert!(matches!(result,Err(Error::Timeout("bootstrap"))));
        assert!(query_id(&pool).await.is_none());
        assert!(started.elapsed()<Duration::from_secs(2));
        assert_eq!(unrelated.await.unwrap(),0,"Outra consulta foi interrompida");
        lock.rollback().await.unwrap();
        assert_eq!(sqlx::query_scalar::<_,i64>("SELECT COUNT(*) FROM torrents WHERE seeders<>777").fetch_one(&pool).await.unwrap(),0);
        println!("PASS timeout interno, rollback confirmado e consulta alheia preservada");

        // A conexao de controle cai: nao alegar cancelamento nem liberar a lease.
        let small=MySqlPoolOptions::new().max_connections(2).connect_with(options).await.unwrap();
        let mut a=small.acquire().await.unwrap(); let mut b=small.acquire().await.unwrap();
        let aid:u64=sqlx::query_scalar("SELECT CONNECTION_ID()").fetch_one(&mut *a).await.unwrap();
        let bid:u64=sqlx::query_scalar("SELECT CONNECTION_ID()").fetch_one(&mut *b).await.unwrap();
        drop(a); drop(b);
        let mut lock=pool.begin().await.unwrap();
        sqlx::query("SELECT id FROM torrents WHERE id=12001 FOR UPDATE").fetch_one(&mut *lock).await.unwrap();
        let task={let p=small.clone();tokio::spawn(async move {
            Coordinator::open_with_bootstrap_timeout(p,settings,Duration::from_secs(1)).await
        })};
        let work=tokio::time::timeout(Duration::from_secs(3),async {
            loop {if let Some(id)=query_id(&pool).await {break id;} tokio::time::sleep(Duration::from_millis(10)).await;}
        }).await.unwrap();
        assert!(work==aid||work==bid);
        let control=if work==aid {bid} else {aid};
        pool.execute(format!("KILL CONNECTION {control}").as_str()).await.unwrap();
        assert!(matches!(task.await.unwrap(),Err(Error::BootstrapCancellation)));
        let live:i64=sqlx::query_scalar("SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM tracker_ownership WHERE id=1").fetch_one(&pool).await.unwrap();
        assert_eq!(live,1);
        // Encerramento manual exclusivamente da conexao sabotada neste ensaio.
        if exists(&pool,work).await {pool.execute(format!("KILL CONNECTION {work}").as_str()).await.unwrap();}
        lock.rollback().await.unwrap();
        sqlx::query("UPDATE tracker_ownership SET lease_expires_at=UTC_TIMESTAMP(3) WHERE id=1 AND backend='rust'").execute(&pool).await.unwrap();
        small.close().await;
        assert_eq!(sqlx::query_scalar::<_,i64>("SELECT COUNT(*) FROM torrents WHERE seeders<>777").fetch_one(&pool).await.unwrap(),0);
        println!("PASS falha da conexao de controle sinalizada, sem liberacao prematura nem commit parcial");
        counts(&pool,settings).await;
    }
}

async fn counts(pool: &MySqlPool, settings: Settings) {
    let settings=Settings {max_peers:20,peer:Policy {min_interval:0,..settings.peer},..settings};
    let c=Coordinator::open(pool.clone(),settings).await.unwrap();
    for i in 0..9 {
        let id=Identity {user_id:12001,torrent_id:12001,peer_id:format!("-BS9200-{i:012}").as_bytes().try_into().unwrap()};
        let families:&[u8]=match i {0|4=>&[4],1|6=>&[6],_=>&[4,6]};
        for family in families {
            c.publish(id,Operation::Announce(Announce {event:Event::Started,
                ip:if *family==4 {"192.0.2.30"} else {"2001:db8::30"}.parse().unwrap(),port:6881,
                uploaded:1000,downloaded:0,left:if i==3||i==4 {100} else {0},visible:i!=5,
                agent:"bootstrap-contract".into()}),Credit::default(),None).unwrap();
        }
    }
    c.shutdown().await.unwrap();
    sqlx::query("UPDATE peer_ips SET connectable=1").execute(pool).await.unwrap();
    for (i,family,connectable) in [(2,6,Some(false)),(3,4,None),(4,4,Some(false))] {
        sqlx::query("UPDATE peer_ips SET connectable=? WHERE peer_id=? AND family=?")
            .bind(connectable).bind(format!("-BS9200-{i:012}").into_bytes()).bind(family).execute(pool).await.unwrap();
    }
    sqlx::query("UPDATE peers SET active=0 WHERE peer_id=?").bind(b"-BS9200-000000000006".as_slice()).execute(pool).await.unwrap();
    sqlx::query("UPDATE peer_ips SET last_announced_at=UTC_TIMESTAMP()-INTERVAL 8000 SECOND WHERE (peer_id=? AND family=4) OR peer_id=?")
        .bind(b"-BS9200-000000000007".as_slice()).bind(b"-BS9200-000000000008".as_slice()).execute(pool).await.unwrap();
    for (require,expected) in [(false,[4,2,2,3,2,1]),(true,[4,1,2,2,0,1])] {
        let c=Coordinator::open(pool.clone(),Settings {require_connectivity:require,..settings}).await.unwrap();
        let row=sqlx::query("SELECT seeders,leechers,seeders_ipv4,seeders_ipv6,leechers_ipv4,leechers_ipv6 FROM torrents WHERE id=12001").fetch_one(pool).await.unwrap();
        let actual=[row.get::<i32,_>(0),row.get::<i32,_>(1),row.get::<u32,_>(2) as i32,
            row.get::<u32,_>(3) as i32,row.get::<u32,_>(4) as i32,row.get::<u32,_>(5) as i32];
        assert_eq!(actual,expected,"Conectividade obrigatoria: {require}");
        assert_eq!(sqlx::query_scalar::<_,i64>("SELECT COUNT(*) FROM peers WHERE uploaded<>1000").fetch_one(pool).await.unwrap(),0);
        assert_eq!(sqlx::query_scalar::<_,i64>("SELECT COUNT(*) FROM history WHERE uploaded<>0 OR actual_uploaded<>0").fetch_one(pool).await.unwrap(),0);
        c.shutdown().await.unwrap();
    }
    println!("PASS contagem unica, familias, invisiveis/inativos, conectividade desconhecida e expiracao independente sem credito novo");
}
