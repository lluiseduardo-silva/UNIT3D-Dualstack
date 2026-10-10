use super::*;
use unit3d_announce::dualstack::peer::Family;

// Contadores SQL do servidor isolado: nenhum outro escritor roda neste ensaio.
// SHOW STATUS dispensa SUPER, triggers e alteracoes na politica de binlog.
async fn commands(pool:&MySqlPool)->[u64;2] {
    let mut counts=[0;2];
    for row in sqlx::query("SHOW GLOBAL STATUS WHERE Variable_name IN ('Com_insert','Com_delete')").fetch_all(pool).await.unwrap() {
        let name:String=row.get(0);
        counts[usize::from(name=="Com_delete")]=row.get::<String,_>(1).parse().unwrap();
    }
    counts
}

async fn writes(pool:&MySqlPool,before:&mut [u64;2])->[u64;2] {
    let after=commands(pool).await;
    let delta=[after[0]-before[0],after[1]-before[1]];
    *before=after; delta
}

async fn snapshot(pool:&MySqlPool,family:u8)->String {
    sqlx::query_scalar("SELECT CAST(JSON_OBJECT('ip',HEX(ip),'port',port,'connectable',connectable,'last_announced_at',last_announced_at,'connectivity_checked_at',connectivity_checked_at,'revision',revision,'created_at',created_at,'updated_at',updated_at) AS CHAR) FROM peer_ips WHERE user_id=12001 AND torrent_id=12001 AND family=?")
        .bind(family).fetch_one(pool).await.unwrap()
}

async fn reprepares(pool:&MySqlPool)->u64 {
    sqlx::query("SHOW GLOBAL STATUS LIKE 'Com_stmt_reprepare'").fetch_one(pool).await.unwrap().get::<String,_>(1).parse().unwrap()
}

pub async fn run(pool:&MySqlPool,settings:Settings) {
    reset(pool).await;
    let c=Coordinator::open(pool.clone(),settings).await.unwrap();
    let at=c.now();
    let mut previous=commands(pool).await;
    for (family,time) in [(4,at),(6,at+1)] {c.publish_at(ID,request(family,1000,Event::Started),Credit::default(),None,time,false).unwrap();}
    c.flush().await.unwrap();
    assert_eq!(writes(pool,&mut previous).await,[3,0]);
    let v6=snapshot(pool,6).await;
    let original=c.peer(ID).unwrap().endpoints.get(Family::V4).unwrap().clone();

    c.publish_at(ID,request(4,1100,Event::Empty),Credit::default(),None,at+2,false).unwrap();
    c.flush().await.unwrap();
    assert_eq!(writes(pool,&mut previous).await,[3,0]);
    assert_eq!(snapshot(pool,6).await,v6);
    c.publish_at(ID,request(4,1200,Event::Empty),Credit::default(),None,at+2,false).unwrap();
    c.flush().await.unwrap();
    assert_eq!(writes(pool,&mut previous).await,[2,0],"Somente peers e history: endpoint igual dispensa SQL");
    assert_eq!(credit(pool).await,200);

    let e=c.peer(ID).unwrap().endpoints.get(Family::V6).unwrap().clone();
    c.publish_at(ID,Operation::Probe {ip:e.ip,port:e.port,revision:e.revision,connectable:true},Credit::default(),None,at+3,false).unwrap();
    c.flush().await.unwrap();
    assert_eq!(writes(pool,&mut previous).await,[3,0]);
    assert_eq!(sqlx::query_scalar::<_,Option<bool>>("SELECT connectable FROM peer_ips WHERE family=6").fetch_one(pool).await.unwrap(),Some(true));
    let Operation::Announce(mut rotated)=request(4,1200,Event::Empty) else {unreachable!()};
    rotated.ip="192.0.2.31".parse().unwrap(); rotated.port=6882;
    c.publish_at(ID,Operation::Announce(rotated.clone()),Credit::default(),None,at+4,false).unwrap();
    c.flush().await.unwrap();
    assert_eq!(writes(pool,&mut previous).await,[3,0]);
    let stored=sqlx::query("SELECT INET6_NTOA(ip) AS ip,port,revision,connectable FROM peer_ips WHERE family=4").fetch_one(pool).await.unwrap();
    assert_eq!(stored.get::<String,_>("ip"),"192.0.2.31"); assert_eq!(stored.get::<u16,_>("port"),6882);
    assert_eq!(stored.get::<u64,_>("revision"),c.peer(ID).unwrap().endpoints.get(Family::V4).unwrap().revision);
    assert_eq!(stored.get::<Option<bool>,_>("connectable"),None);
    assert_eq!(c.publish_at(ID,Operation::Probe {ip:original.ip,port:original.port,revision:original.revision,connectable:true},Credit::default(),None,at+5,false).unwrap().outcome,Outcome::Ignored);
    assert_eq!(c.publish_at(ID,request(4,1200,Event::Stopped),Credit::default(),None,at+5,false).unwrap().outcome,Outcome::Ignored);
    assert_eq!(c.backlog(),0);

    // Remocao e nova encarnacao no mesmo lote: upsert preserva a ultima revisao.
    c.publish_at(ID,request(6,1200,Event::Stopped),Credit::default(),None,at+5,false).unwrap();
    c.publish_at(ID,request(6,1200,Event::Started),Credit::default(),None,at+6,false).unwrap();
    c.flush().await.unwrap();
    assert_eq!(writes(pool,&mut previous).await,[3,0]);
    let created:chrono::DateTime<chrono::Utc>=sqlx::query_scalar("SELECT created_at FROM peer_ips WHERE family=6").fetch_one(pool).await.unwrap();
    assert_eq!(created.timestamp(),(at+6) as i64);
    assert_eq!(sqlx::query_scalar::<_,Option<bool>>("SELECT connectable FROM peer_ips WHERE family=6").fetch_one(pool).await.unwrap(),None);
    assert_eq!(c.peer(ID).unwrap().endpoints.get(Family::V6).unwrap().connectable,None);

    // Primeiro item confirmado sem ACK; replay parcial nao ressuscita o removido.
    c.publish_at(ID,request(6,1200,Event::Stopped),Credit::default(),None,at+8,false).unwrap();
    c.publish_at(ID,request(6,1200,Event::Started),Credit::default(),None,at+9,false).unwrap();
    let batch=c.batch();
    assert_eq!(c.persist_batch(&batch[..1]).await.unwrap(),1);
    assert_eq!(writes(pool,&mut previous).await,[2,1]);
    assert_eq!(c.flush().await.unwrap(),2);
    assert_eq!(writes(pool,&mut previous).await,[3,0]);
    assert_eq!(c.persist_batch(&batch).await.unwrap(),0);
    assert_eq!(writes(pool,&mut previous).await,[0,0]);

    // Forcar falha depois dos endpoints desfaz upsert e delete na mesma transacao.
    let reprepare_before=reprepares(pool).await;
    sqlx::query("ALTER TABLE history ADD CONSTRAINT dualstack_endpoint_fail CHECK (uploaded=200)").execute(pool).await.unwrap();
    rotated.uploaded=1300;
    c.publish_at(ID,Operation::Announce(rotated.clone()),Credit::default(),None,at+10,false).unwrap();
    c.publish_at(ID,request(6,1300,Event::Stopped),Credit::default(),None,at+11,false).unwrap();
    let before=[snapshot(pool,4).await,snapshot(pool,6).await];
    assert!(c.persist_batch(&c.batch()).await.is_err());
    assert_eq!([snapshot(pool,4).await,snapshot(pool,6).await],before);
    writes(pool,&mut previous).await; assert_eq!(credit(pool).await,200);
    sqlx::query("ALTER TABLE history DROP CHECK dualstack_endpoint_fail").execute(pool).await.unwrap();
    writes(pool,&mut previous).await;
    c.flush().await.unwrap();
    let recovered=writes(pool,&mut previous).await;
    // ALTER invalida statements em cache. A contagem exata de INSERT foi
    // verificada acima sem DDL; aqui conferir remocao e estado confirmado.
    println!("INFO comandos apos DDL/rollback: {recovered:?}, reprepares: {}",reprepares(pool).await-reprepare_before);
    assert_eq!(recovered[1],1);
    assert_eq!(credit(pool).await,300);
    assert_eq!(count(pool,"peer_ips").await,1);

    // Expiracao independente depois de atualizar a outra familia.
    c.publish_at(ID,request(6,1300,Event::Started),Credit::default(),None,at+20,false).unwrap();
    c.flush().await.unwrap(); writes(pool,&mut previous).await;
    c.publish_at(ID,Operation::Expire,Credit::default(),None,at+10+settings.peer.endpoint_ttl,false).unwrap();
    c.flush().await.unwrap();
    assert_eq!(writes(pool,&mut previous).await[1],1);
    assert_eq!(count(pool,"peer_ips").await,1);
    assert_eq!(sqlx::query_scalar::<_,u8>("SELECT family FROM peer_ips").fetch_one(pool).await.unwrap(),6);
    c.publish_at(ID,Operation::Expire,Credit::default(),None,at+20+settings.peer.endpoint_ttl,false).unwrap();
    c.flush().await.unwrap();
    assert_eq!(writes(pool,&mut previous).await[1],1);
    c.shutdown().await.unwrap();
    let restored=Coordinator::open(pool.clone(),settings).await.unwrap();
    assert!(!restored.peer(ID).unwrap().active); assert_eq!(credit(pool).await,300);
    restored.shutdown().await.unwrap();
    println!("PASS comandos SQL sem DELETE desnecessario e snapshots por familia: identidade, timestamps, contador sem escrita de endpoint, troca, coalescencia, replay parcial, rollback e expiracao");
}
