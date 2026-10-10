use std::{env,time::Duration};
use sqlx::{Row,mysql::MySqlPoolOptions};
use unit3d_announce::dualstack::{coordinator::{Coordinator,Credit,Error,Identity,Settings},peer::{Announce,Event,Operation,Policy}};

#[tokio::test]
#[ignore="Exige DUALSTACK_HANDOFF_TESTS=1 e fases PHP/Rust no banco isolado"]
async fn php_rust_handoff() {
    assert_eq!(env::var("DUALSTACK_HANDOFF_TESTS").as_deref(),Ok("1"));
    let phase=env::var("DUALSTACK_HANDOFF_PHASE").unwrap();
    assert!(matches!(phase.as_str(),"pending" | "resume" | "verify"));
    let options=sqlx::mysql::MySqlConnectOptions::new().host("172.29.92.20")
        .username(&env::var("MYSQL_USER").unwrap()).password(&env::var("MYSQL_PASSWORD").unwrap())
        .database("unit3d_dualstack_journal_test");
    let pool=MySqlPoolOptions::new().max_connections(4).acquire_timeout(Duration::from_secs(3)).connect_with(options).await.unwrap();
    let database:String=sqlx::query_scalar("SELECT DATABASE()").fetch_one(&pool).await.unwrap();
    assert_eq!(database,"unit3d_dualstack_journal_test");
    let settings=Settings {peer:Policy {min_interval:0,allow_private_addresses:true,..Policy::default()},..Settings::default()};
    let id=Identity {user_id:12001,torrent_id:12001,peer_id:*b"-DS9200-000000000092"};
    let generation:u64=sqlx::query_scalar("SELECT generation FROM tracker_ownership WHERE id=1").fetch_one(&pool).await.unwrap();
    if phase=="pending" {
        assert!(matches!(Coordinator::open(pool.clone(),settings).await,Err(Error::PendingPhpJournal)));
        assert_eq!(sqlx::query_scalar::<_,u64>("SELECT generation FROM tracker_ownership WHERE id=1").fetch_one(&pool).await.unwrap(),generation);
        assert_eq!(sqlx::query_scalar::<_,u64>("SELECT uploaded FROM users WHERE id=12001").fetch_one(&pool).await.unwrap(),0);
        println!("PASS Rust recusa journal PHP pendente sem alterar geracao ou credito");
        return;
    }
    let c=Coordinator::open(pool.clone(),settings).await.unwrap();
    assert!(c.generation()>generation);
    let before=c.peer(id).unwrap();
    let upload=if phase=="resume" {1200} else {1300};
    assert_eq!(before.uploaded,if phase=="resume" {1100} else {1300});
    assert_eq!(before.endpoints.iter().count(),if phase=="resume" {2} else {1});
    let result=c.publish(id,Operation::Announce(Announce {event:Event::Empty,ip:"172.29.92.30".parse().unwrap(),port:6881,
        uploaded:upload,downloaded:0,left:0,visible:true,agent:"dualstack-handoff-test".into()}),Credit::default(),None).unwrap();
    assert_eq!(result.upload_delta,if phase=="resume" {100} else {0});
    c.shutdown().await.unwrap();
    assert_eq!(sqlx::query_scalar::<_,u64>("SELECT uploaded FROM users WHERE id=12001").fetch_one(&pool).await.unwrap(),if phase=="resume" {200} else {300});
    let row=sqlx::query("SELECT active,actual_uploaded FROM history WHERE user_id=12001 AND torrent_id=12001").fetch_one(&pool).await.unwrap();
    assert!(row.get::<bool,_>("active"));
    assert_eq!(row.get::<u64,_>("actual_uploaded"),if phase=="resume" {200} else {300});
    println!("PASS PHP para Rust {phase}: endpoints e referencias restaurados, credito sem duplicacao");
}
