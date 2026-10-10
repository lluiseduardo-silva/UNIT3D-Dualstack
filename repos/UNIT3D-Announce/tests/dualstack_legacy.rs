use std::{env, time::Duration};
use sqlx::{Row, mysql::MySqlPoolOptions};
use unit3d_announce::dualstack::{coordinator::{Coordinator, Credit, Identity, Settings}, peer::{Announce, Event, Operation, Policy}};

#[tokio::test]
#[ignore="Exige DUALSTACK_LEGACY_TESTS=1 e ensaio sequencial com tags originais no banco isolado"]
async fn resumes_original_legacy_projection() {
    assert_eq!(env::var("DUALSTACK_LEGACY_TESTS").as_deref(), Ok("1"));
    let options=sqlx::mysql::MySqlConnectOptions::new().host("172.29.92.20")
        .username(&env::var("MYSQL_USER").unwrap()).password(&env::var("MYSQL_PASSWORD").unwrap())
        .database("unit3d_dualstack_journal_test");
    let pool=MySqlPoolOptions::new().max_connections(4).acquire_timeout(Duration::from_secs(3)).connect_with(options).await.unwrap();
    assert_eq!(sqlx::query_scalar::<_,String>("SELECT DATABASE()").fetch_one(&pool).await.unwrap(),"unit3d_dualstack_journal_test");
    let settings=Settings {peer:Policy {min_interval:0,allow_private_addresses:true,..Policy::default()},..Settings::default()};
    let id=Identity {user_id:12001,torrent_id:12001,peer_id:*b"-DS9200-000000000092"};
    let c=Coordinator::open(pool.clone(),settings).await.unwrap();
    let before=c.peer(id).unwrap();
    assert_eq!(before.uploaded,1400);
    assert_eq!(before.endpoints.iter().count(),1);
    assert!(before.state_version>0);
    assert_eq!(sqlx::query_scalar::<_,u64>("SELECT uploaded FROM users WHERE id=12001").fetch_one(&pool).await.unwrap(),400);
    for (family,upload,delta) in [(4,1400,0),(6,1400,0),(4,1500,100),(6,1500,0)] {
        let result=c.publish(id,Operation::Announce(Announce {event:Event::Started,
            ip:if family==4 {"172.29.92.30"} else {"fd42:756e:6974:92::30"}.parse().unwrap(),port:6881,
            uploaded:upload,downloaded:0,left:0,visible:true,agent:"libtorrent/2.0.10".into()}),Credit::default(),None).unwrap();
        assert_eq!(result.upload_delta,delta);
    }
    c.shutdown().await.unwrap();
    assert_eq!(sqlx::query_scalar::<_,u64>("SELECT uploaded FROM users WHERE id=12001").fetch_one(&pool).await.unwrap(),500);
    let row=sqlx::query("SELECT active,actual_uploaded FROM history WHERE user_id=12001 AND torrent_id=12001").fetch_one(&pool).await.unwrap();
    assert!(row.get::<bool,_>("active"));
    assert_eq!(row.get::<u64,_>("actual_uploaded"),500);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT COUNT(*) FROM peer_ips").fetch_one(&pool).await.unwrap(),2);
    println!("PASS Rust novo restaura referencia 1400 e um endpoint; duas familias geram somente 100 de credito novo (saldo 500)");
}
