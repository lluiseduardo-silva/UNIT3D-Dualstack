//! Ensaios de escala opt-in, somente no banco descartavel do laboratorio.
use std::{collections::BTreeMap, env, time::{Duration, Instant}};
use serde_json::{Value, json};
use sqlx::{Connection, Executor, MySqlConnection, Row, mysql::MySqlPoolOptions};
use super::{coordinator::{Coordinator, Settings}, peer::Policy, persistence::reconciliation_query};

async fn handlers(connection: &mut MySqlConnection) -> BTreeMap<String,u64> {
    sqlx::query("SHOW SESSION STATUS WHERE Variable_name IN ('Handler_read_key','Handler_read_next','Handler_read_rnd_next')")
        .fetch_all(connection).await.unwrap().into_iter().map(|r|
            (r.get::<String,_>(0),r.get::<String,_>(1).parse().unwrap())).collect()
}

fn legacy_query() -> String {
    let mut query=String::from("UPDATE torrents t LEFT JOIN (SELECT p.torrent_id,");
    let fields=["seeders","leechers","seeders_ipv4","seeders_ipv6","leechers_ipv4","leechers_ipv6"];
    for (i,field) in fields.iter().enumerate() {
        if i>0 {query.push(',');}
        let seeder=if field.starts_with("seeders") {1} else {0};
        let family=if field.ends_with('4') {" AND e.family=4"} else if field.ends_with('6') {" AND e.family=6"} else {""};
        // Controle adverso deliberado: reproduzir o indice observado no incidente.
        query.push_str(&format!("SUM(p.active=1 AND p.visible=1 AND p.seeder={seeder} AND EXISTS(SELECT 1 FROM peer_ips e FORCE INDEX (peer_ips_torrent_family_live) WHERE e.user_id=p.user_id AND e.torrent_id=p.torrent_id AND e.peer_id=p.peer_id{family})) AS {field}"));
    }
    query.push_str(" FROM peers p GROUP BY p.torrent_id) c ON c.torrent_id=t.id SET ");
    query.push_str(&fields.iter().map(|f|format!("t.{f}=COALESCE(c.{f},0)")).collect::<Vec<_>>().join(","));
    query
}

#[tokio::test(flavor="multi_thread",worker_threads=4)]
#[ignore="Fixture de 1k/54k/100k e MySQL real; executar run-bootstrap-scale.sh"]
async fn bootstrap_scale() {
    assert_eq!(env::var("DUALSTACK_MYSQL_TESTS").as_deref(),Ok("1"));
    let options=sqlx::mysql::MySqlConnectOptions::new().host("172.29.92.20")
        .username(&env::var("MYSQL_USER").unwrap()).password(&env::var("MYSQL_PASSWORD").unwrap())
        .database("unit3d_dualstack_journal_test");
    let pool=MySqlPoolOptions::new().max_connections(8).acquire_timeout(Duration::from_secs(3)).connect_with(options).await.unwrap();
    let total:i64=sqlx::query_scalar("SELECT COUNT(*) FROM peers").fetch_one(&pool).await.unwrap();
    assert!([1000,54000,100000].contains(&total));
    let torrents:i64=sqlx::query_scalar("SELECT COUNT(DISTINCT torrent_id) FROM peers").fetch_one(&pool).await.unwrap();
    assert!(torrents==1||torrents==total/250);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM tracker_ownership WHERE id=1").fetch_one(&pool).await.unwrap(),0);
    let mut report=json!({"peers":total,"torrents":torrents,"statistics_analyzed":false,"probes":[],"opens":[]});
    for (label,query) in [("legacy_forced_adverse_index",legacy_query()),("candidate",reconciliation_query(false))] {
        let plan:String=sqlx::query_scalar(&format!("EXPLAIN FORMAT=JSON {query}")).fetch_one(&pool).await.unwrap();
        let mut work=pool.acquire().await.unwrap();
        let mut control=pool.acquire().await.unwrap();
        let id:u64=sqlx::query_scalar("SELECT CONNECTION_ID()").fetch_one(&mut *work).await.unwrap();
        let before=handlers(&mut work).await;
        let mut tx=work.begin().await.unwrap();
        let started=Instant::now();
        let mut interrupted=false;
        let result={
            let run=sqlx::query(&query).execute(&mut *tx);
            tokio::pin!(run);
            tokio::select! {
                result=&mut run=>result,
                _=tokio::time::sleep(Duration::from_secs(2))=>{
                    interrupted=true;
                    control.execute(format!("KILL QUERY {id}").as_str()).await.unwrap();
                    tokio::time::timeout(Duration::from_secs(5),run).await.unwrap()
                }
            }
        };
        let elapsed=started.elapsed().as_secs_f64();
        if interrupted {
            assert!(matches!(&result,Err(sqlx::Error::Database(e)) if e.try_downcast_ref::<sqlx::mysql::MySqlDatabaseError>().is_some_and(|e|e.number()==1317)));
        } else {result.unwrap();}
        tx.rollback().await.unwrap();
        let after=handlers(&mut work).await;
        let reads=after.into_iter().map(|(k,v)| {let delta=v-before[&k];(k,delta)}).collect::<BTreeMap<_,_>>();
        report["probes"].as_array_mut().unwrap().push(json!({"variant":label,"seconds":elapsed,
            "interrupted_at_2s":interrupted,"handler_read_deltas":reads,"plan":serde_json::from_str::<Value>(&plan).unwrap()}));
        assert!(label!="candidate"||!interrupted,"Consulta candidata excedeu limite exploratorio de 2 s");
    }
    let settings=Settings {peer:Policy {allow_private_addresses:true,..Policy::default()},..Settings::default()};
    for repeat in 0..3 {
        sqlx::query("UPDATE torrents SET seeders=777,leechers=777,seeders_ipv4=777,seeders_ipv6=777,leechers_ipv4=777,leechers_ipv6=777").execute(&pool).await.unwrap();
        let started=Instant::now();
        let c=Coordinator::open(pool.clone(),settings).await.unwrap();
        let elapsed=started.elapsed().as_secs_f64();
        assert!(elapsed<30.,"Bootstrap excedeu uma janela de lease");
        assert_eq!(c.backlog(),0);
        assert_eq!(sqlx::query_scalar::<_,i64>("SELECT COUNT(*) FROM peers WHERE state_version<>0 OR uploaded<>0 OR downloaded<>0").fetch_one(&pool).await.unwrap(),0);
        assert_eq!(sqlx::query_scalar::<_,i64>("SELECT COUNT(*) FROM history WHERE uploaded<>0 OR downloaded<>0 OR actual_uploaded<>0 OR actual_downloaded<>0").fetch_one(&pool).await.unwrap(),0);
        assert_eq!(sqlx::query_scalar::<_,i64>("SELECT COUNT(*) FROM peer_ips").fetch_one(&pool).await.unwrap(),2*total);
        let totals:String=sqlx::query_scalar("SELECT CAST(JSON_ARRAY(SUM(seeders),SUM(leechers),SUM(seeders_ipv4),SUM(seeders_ipv6),SUM(leechers_ipv4),SUM(leechers_ipv6)) AS CHAR) FROM torrents").fetch_one(&pool).await.unwrap();
        assert_eq!(serde_json::from_str::<Vec<i64>>(&totals).unwrap(),vec![total*4/5,total/5,total*4/5,total*4/5,total/5,total/5]);
        c.shutdown().await.unwrap();
        report["opens"].as_array_mut().unwrap().push(json!({"repeat":repeat+1,"seconds":elapsed,"generation":c.generation(),"credit":0,"endpoints":2*total}));
    }
    println!("BOOTSTRAP_SCALE_JSON {report}");
}
