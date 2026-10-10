use std::{env, sync::{Arc, Barrier}, time::Duration};
use sqlx::{MySqlPool, Row, mysql::MySqlPoolOptions};
use unit3d_announce::dualstack::{coordinator::{Coordinator, Credit, Error, Identity, Settings}, peer::{Announce, Event, Operation, Outcome, Policy}};

#[path="support/dualstack_failures.rs"]
mod failures;
#[path="support/dualstack_response.rs"]
mod response;
#[path="support/dualstack_retention.rs"]
mod retention;
#[path="support/dualstack_admin.rs"]
mod admin;
#[path="support/dualstack_writer.rs"]
mod writer;
#[path="support/dualstack_endpoints.rs"]
mod endpoints;
#[path="support/dualstack_recovery.rs"]
mod recovery;

const ID: Identity = Identity { user_id:12001,torrent_id:12001,peer_id:*b"-DS9200-000000000092" };

fn test_database() -> String {
    let name=env::var("DUALSTACK_TEST_DATABASE").unwrap_or_else(|_|"unit3d_dualstack_journal_test".into());
    assert!(matches!(name.as_str(),"unit3d_dualstack_journal_test" | "unit3d_dualstack_recovery_test"));
    name
}

fn request(family:u8, upload:u64, event:Event) -> Operation {
    Operation::Announce(Announce { event,ip:if family==4 {"192.0.2.30"} else {"2001:db8::30"}.parse().unwrap(),
        port:if event==Event::Stopped {0} else {6881}, uploaded:upload,downloaded:0,left:0,visible:true,agent:"dualstack-rust-test".into() })
}

async fn reset(pool:&MySqlPool) {
    let live:i64=sqlx::query_scalar("SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM tracker_ownership WHERE id=1").fetch_one(pool).await.unwrap();
    assert_eq!(live,0,"Encerre o proprietario do laboratorio antes dos testes");
    sqlx::query("DELETE FROM peers").execute(pool).await.unwrap();
    sqlx::query("DELETE FROM history").execute(pool).await.unwrap();
    sqlx::query("UPDATE users SET uploaded=0,downloaded=0").execute(pool).await.unwrap();
    sqlx::query("UPDATE torrents SET seeders=0,leechers=0,seeders_ipv4=0,seeders_ipv6=0,leechers_ipv4=0,leechers_ipv6=0,times_completed=0,balance=0").execute(pool).await.unwrap();
}

async fn credit(pool:&MySqlPool) -> u64 { sqlx::query_scalar("SELECT uploaded FROM users WHERE id=12001").fetch_one(pool).await.unwrap() }
async fn count(pool:&MySqlPool,table:&str) -> i64 { sqlx::query_scalar(&format!("SELECT COUNT(*) FROM {table}")).fetch_one(pool).await.unwrap() }

#[tokio::test(flavor="multi_thread",worker_threads=4)]
#[ignore="Exige DUALSTACK_MYSQL_TESTS=1, MySQL real e banco isolado unit3d_dualstack_journal_test"]
async fn mysql_coordinator_contract() {
    assert_eq!(env::var("DUALSTACK_MYSQL_TESTS").as_deref(),Ok("1"));
    let options=sqlx::mysql::MySqlConnectOptions::new().host("172.29.92.20")
        .username(&env::var("MYSQL_USER").unwrap()).password(&env::var("MYSQL_PASSWORD").unwrap())
        .database(&test_database());
    let pool=MySqlPoolOptions::new().max_connections(8).acquire_timeout(Duration::from_secs(3)).connect_with(options).await.expect("MySQL do laboratorio indisponivel");
    let database:String=sqlx::query_scalar("SELECT DATABASE()").fetch_one(&pool).await.unwrap();
    assert_eq!(database,test_database());
    let isolation:String=sqlx::query_scalar("SELECT @@transaction_isolation").fetch_one(&pool).await.unwrap();
    assert_eq!(isolation,"REPEATABLE-READ");
    let wait:u64=sqlx::query_scalar("SELECT @@innodb_lock_wait_timeout").fetch_one(&pool).await.unwrap();
    assert_eq!(wait,10);
    let settings=Settings {peer:Policy {min_interval:0,..Policy::default()},..Settings::default()};
    reset(&pool).await;
    let generation:u64=sqlx::query_scalar("SELECT generation FROM tracker_ownership WHERE id=1").fetch_one(&pool).await.unwrap();
    sqlx::query("UPDATE tracker_ownership SET legacy_reconciliation_required=1 WHERE id=1").execute(&pool).await.unwrap();
    assert!(matches!(Coordinator::open(pool.clone(),settings).await,Err(Error::LegacyReconciliation)));
    assert_eq!(sqlx::query_scalar::<_,u64>("SELECT generation FROM tracker_ownership WHERE id=1").fetch_one(&pool).await.unwrap(),generation);
    sqlx::query("UPDATE tracker_ownership SET legacy_reconciliation_required=0 WHERE id=1").execute(&pool).await.unwrap();
    println!("PASS reconciliacao legada bloqueia aquisicao Rust sem alterar geracao");
    let c=Coordinator::open(pool.clone(),settings).await.unwrap();
    assert!(matches!(Coordinator::open(pool.clone(),settings).await,Err(Error::Owned)));
    for (family,uploaded) in [(4,1000),(6,1000),(6,1100),(4,1050),(4,1200)] {
        assert_eq!(c.publish(ID,request(family,uploaded,Event::Started),Credit::default(),None).unwrap().outcome,Outcome::Accepted);
    }
    assert_eq!(credit(&pool).await,0);
    let batch=c.batch(); assert_eq!(batch.len(),5);
    assert_eq!(c.persist_batch(&batch).await.unwrap(),5);
    assert_eq!(c.persist_batch(&batch).await.unwrap(),0);
    assert_eq!(c.flush().await.unwrap(),5); assert_eq!(c.backlog(),0);
    assert_eq!(credit(&pool).await,200);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT balance FROM torrents WHERE id=12001").fetch_one(&pool).await.unwrap(),200);
    assert_eq!(count(&pool,"peers").await,1); assert_eq!(count(&pool,"peer_ips").await,2);
    let row=sqlx::query("SELECT seeders,seeders_ipv4,seeders_ipv6 FROM torrents WHERE id=12001").fetch_one(&pool).await.unwrap();
    // O contador legado e INT; os novos contadores por familia sao INT UNSIGNED.
    assert_eq!((row.get::<i32,_>(0),row.get::<u32,_>(1),row.get::<u32,_>(2)),(1,1,1));
    let before=c.peer(ID).unwrap(); let old_generation=c.generation();
    c.shutdown().await.unwrap();
    let restored=Coordinator::open(pool.clone(),settings).await.unwrap();
    assert!(restored.generation()>old_generation);
    let after=restored.peer(ID).unwrap();
    assert_eq!(after.endpoints,before.endpoints); assert_eq!(after.last_announces,before.last_announces);
    assert_eq!((after.uploaded,after.state_version,after.session_generation),(1200,5,1));
    assert!(c.persist_batch(&batch).await.is_err());
    restored.publish(ID,request(6,1300,Event::Completed),Credit::default(),None).unwrap();
    restored.flush().await.unwrap(); assert_eq!(credit(&pool).await,300);
    restored.publish(ID,request(4,1300,Event::Stopped),Credit::default(),None).unwrap();
    restored.flush().await.unwrap(); assert_eq!(count(&pool,"peer_ips").await,1);
    let version=restored.peer(ID).unwrap().state_version;
    assert_eq!(restored.publish(ID,request(4,9000,Event::Stopped),Credit::default(),None).unwrap().outcome,Outcome::Ignored);
    assert_eq!(restored.peer(ID).unwrap().state_version,version); assert_eq!(credit(&pool).await,300);
    restored.shutdown().await.unwrap();
    println!("PASS contabilidade 1000/1000/1100/1050/1200, reentrega, restart, geracao e stop parcial");

    reset(&pool).await;
    let c=Coordinator::open(pool.clone(),Settings {max_pending:1,..settings}).await.unwrap();
    c.publish(ID,request(4,1000,Event::Started),Credit::default(),None).unwrap();
    assert!(matches!(c.publish(ID,request(6,1100,Event::Started),Credit::default(),None),Err(Error::BacklogFull)));
    assert_eq!(c.peer(ID).unwrap().uploaded,1000); assert_eq!(c.peer(ID).unwrap().state_version,1);
    c.flush().await.unwrap(); c.publish(ID,request(6,1100,Event::Started),Credit::default(),None).unwrap();
    c.shutdown().await.unwrap(); assert_eq!(credit(&pool).await,100);
    println!("PASS backlog cheio sem avancar referencia");

    reset(&pool).await;
    let c=Coordinator::open(pool.clone(),settings).await.unwrap();
    c.publish(ID,request(4,1000,Event::Started),Credit::default(),None).unwrap();
    c.publish(ID,request(6,1100,Event::Started),Credit::default(),None).unwrap();
    // Erro real depois dos upserts de peers e endpoints, sem privilegios globais.
    sqlx::query("ALTER TABLE history ADD CONSTRAINT dualstack_test_fail CHECK (uploaded = 0)").execute(&pool).await.unwrap();
    let failed=c.persist_batch(&c.batch()).await;
    sqlx::query("ALTER TABLE history DROP CHECK dualstack_test_fail").execute(&pool).await.unwrap();
    match failed {
        Err(Error::Database(sqlx::Error::Database(error))) => {
            let error=error.downcast_ref::<sqlx::mysql::MySqlDatabaseError>();
            assert_eq!(error.number(),3819); assert!(error.message().contains("dualstack_test_fail"));
        }
        result => panic!("Esperava violacao do CHECK de ensaio; recebido: {result:?}"),
    }
    assert_eq!(count(&pool,"peers").await,0); assert_eq!(count(&pool,"peer_ips").await,0);
    assert_eq!(count(&pool,"history").await,0); assert_eq!(credit(&pool).await,0); assert_eq!(c.backlog(),2);
    c.flush().await.unwrap(); assert_eq!(credit(&pool).await,100); c.shutdown().await.unwrap();
    println!("PASS falha SQL entre endpoints e historico deixa zero efeitos parciais");

    reset(&pool).await;
    let c=Arc::new(Coordinator::open(pool.clone(),settings).await.unwrap());
    c.publish(ID,request(4,1000,Event::Started),Credit::default(),None).unwrap();
    let barrier=Arc::new(Barrier::new(5));
    let questions=|pool:MySqlPool| async move {sqlx::query("SHOW GLOBAL STATUS LIKE 'Questions'").fetch_one(&pool).await.unwrap().get::<String,_>(1).parse::<u64>().unwrap()};
    let before_queries=questions(pool.clone()).await;
    let mut threads=vec![];
    for worker in 0..4 {
        let (c,barrier)=(c.clone(),barrier.clone());
        threads.push(std::thread::spawn(move||{
            barrier.wait();
            for n in 1..=100 { c.publish(ID,request(if worker%2==0 {4} else {6},1000+worker*1000+n*10,Event::Completed),Credit::default(),None).unwrap(); }
        }));
    }
    barrier.wait(); for thread in threads {thread.join().unwrap();}
    let after_queries=questions(pool.clone()).await;
    assert_eq!(after_queries-before_queries,1,"publish nao pode consultar MySQL; somente a leitura de Questions deve aparecer");
    assert_eq!(c.backlog(),401); assert_eq!(c.peer(ID).unwrap().uploaded,5000);
    while c.backlog()>0 {c.flush().await.unwrap();}
    assert_eq!(credit(&pool).await,4000); assert_eq!(count(&pool,"peer_ips").await,2);
    c.shutdown().await.unwrap();
    println!("PASS quatro threads, 401 transicoes, credito 4000 e zero SQL durante publish");

    reset(&pool).await;
    let c=Coordinator::open(pool.clone(),settings).await.unwrap();
    let now=c.now();
    c.publish_at(ID,request(6,1000,Event::Started),Credit::default(),None,now-7199,false).unwrap();
    c.publish_at(ID,request(4,1000,Event::Started),Credit::default(),None,now-10,false).unwrap();
    assert_eq!(c.expire_at(now+2,false).unwrap(),1); c.flush().await.unwrap();
    assert_eq!(count(&pool,"peer_ips").await,1);
    assert_eq!(sqlx::query_scalar::<_,u8>("SELECT family FROM peer_ips").fetch_one(&pool).await.unwrap(),4);
    c.shutdown().await.unwrap();
    println!("PASS expiracao independente por familia");

    reset(&pool).await;
    let c=Coordinator::open(pool.clone(),settings).await.unwrap();
    for peer in [b'1',b'2',b'3'] {
        let id=Identity {peer_id:[peer;20],..ID};
        for family in [4,6] {c.publish(id,request(family,1000,Event::Started),Credit::default(),None).unwrap();}
    }
    assert!(matches!(c.publish(ID,request(4,1000,Event::Started),Credit::default(),None),Err(Error::PeerLimit)));
    c.shutdown().await.unwrap(); assert_eq!(count(&pool,"peers").await,3); assert_eq!(count(&pool,"peer_ips").await,6);
    println!("PASS tres peers dualstack e quarto peer recusado");

    reset(&pool).await;
    let c=Coordinator::open(pool.clone(),settings).await.unwrap();
    c.publish(ID,request(4,u64::MAX-1,Event::Started),Credit::default(),None).unwrap();
    c.publish(ID,request(6,u64::MAX,Event::Completed),Credit::default(),None).unwrap();
    c.shutdown().await.unwrap(); assert_eq!(credit(&pool).await,1);
    assert_eq!(sqlx::query_scalar::<_,u64>("SELECT uploaded FROM peers").fetch_one(&pool).await.unwrap(),u64::MAX);
    println!("PASS uint64 maximo exato em memoria e MySQL");

    // TIMESTAMP e DATETIME preenchidos precisam sobreviver a reentrega e bootstrap.
    reset(&pool).await;
    let c=Coordinator::open(pool.clone(),settings).await.unwrap();
    let at=c.now()-60;
    for (family,offset) in [(4,0),(6,1)] {
        let Operation::Announce(mut announce)=request(family,1000,Event::Started) else {unreachable!()};
        announce.left=100;
        c.publish_at(ID,Operation::Announce(announce),Credit::default(),None,at+offset,false).unwrap();
    }
    for (family,offset,completed) in [(4,10,1),(6,20,0)] {
        let Operation::Announce(mut announce)=request(family,1100,Event::Completed) else {unreachable!()};
        announce.downloaded=100;
        let result=c.publish_at(ID,Operation::Announce(announce),Credit::default(),None,at+offset,false).unwrap();
        assert_eq!(result.completed_delta,completed);
    }
    c.publish_at(ID,Operation::Probe {ip:"192.0.2.30".parse().unwrap(),port:6881,revision:1,connectable:true},Credit::default(),None,at+30,false).unwrap();
    let before=c.peer(ID).unwrap();
    let batch=c.batch(); assert_eq!(batch.len(),5);
    assert_eq!(c.persist_batch(&batch).await.unwrap(),5);
    assert_eq!(c.persist_batch(&batch).await.unwrap(),0);
    c.shutdown().await.unwrap();
    let row=sqlx::query("SELECT created_at,updated_at,swarm_updated_at,completed_at,seedtime FROM history WHERE user_id=12001 AND torrent_id=12001").fetch_one(&pool).await.unwrap();
    let completed_at=chrono::DateTime::from_timestamp((at+10) as i64,0).unwrap().naive_utc();
    assert_eq!(row.get::<Option<chrono::NaiveDateTime>,_>("completed_at"),Some(completed_at));
    for (column,offset) in [("created_at",0),("updated_at",30),("swarm_updated_at",20)] {
        assert_eq!(row.get::<chrono::DateTime<chrono::Utc>,_>(column).timestamp(),(at+offset) as i64);
    }
    assert_eq!(row.get::<u64,_>("seedtime"),10);
    let restored=Coordinator::open(pool.clone(),settings).await.unwrap();
    let after=restored.peer(ID).unwrap();
    assert_eq!(after.endpoints,before.endpoints); assert_eq!(after.last_announces,before.last_announces);
    assert_eq!((after.created_at,after.updated_at,after.state_version),(at,at+30,5));
    assert!(after.completion_reported); assert!(after.connectable);
    let endpoint=after.endpoints.iter().find(|e| e.family.number()==4).unwrap();
    assert_eq!(endpoint.connectivity_checked_at,Some(at+30));
    let Operation::Announce(mut announce)=request(6,1100,Event::Completed) else {unreachable!()};
    announce.downloaded=100;
    assert_eq!(restored.publish_at(ID,Operation::Announce(announce),Credit::default(),None,at+40,false).unwrap().completed_delta,0);
    restored.shutdown().await.unwrap();
    assert_eq!(credit(&pool).await,100);
    assert_eq!(sqlx::query_scalar::<_,u64>("SELECT downloaded FROM users WHERE id=12001").fetch_one(&pool).await.unwrap(),100);
    let row=sqlx::query("SELECT completed_at,seedtime,state_version FROM history WHERE user_id=12001 AND torrent_id=12001").fetch_one(&pool).await.unwrap();
    assert_eq!(row.get::<Option<chrono::NaiveDateTime>,_>("completed_at"),Some(completed_at));
    assert_eq!(row.get::<u64,_>("seedtime"),30); assert_eq!(row.get::<u64,_>("state_version"),6);
    assert_eq!(sqlx::query_scalar::<_,i32>("SELECT times_completed FROM torrents WHERE id=12001").fetch_one(&pool).await.unwrap(),1);
    println!("PASS TIMESTAMP e DATETIME preenchidos, probe e conclusao restaurados, seedtime 30 e credito 100/100 sem duplicacao");
    response::run(&pool,settings).await;
    retention::run(&pool,settings).await;
    admin::run(&pool,settings).await;
    failures::run(&pool,settings).await;
    recovery::run(&pool,settings).await;
    writer::run(&pool,settings).await;
    endpoints::run(&pool,settings).await;
    println!("RUST_MYSQL_COORDINATOR_PASSED");
}
