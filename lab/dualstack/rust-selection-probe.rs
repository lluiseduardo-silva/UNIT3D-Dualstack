//! Diagnostico isolado da selecao; nao e um benchmark HTTP de homologacao.
use std::{env, hint::black_box, time::{Duration, Instant}};

use serde_json::json;
use sqlx::mysql::{MySqlConnectOptions, MySqlPoolOptions};
use unit3d_announce::dualstack::{coordinator::{Coordinator, Settings}, peer::Policy, response::ListRequest};

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    assert_eq!(env::var("DUALSTACK_SELECTION_PROBE").as_deref(), Ok("1"));
    let expected: i64 = env::var("PROBE_EXPECTED_PEERS").unwrap().parse().unwrap();
    assert!([1000, 54000, 100000].contains(&expected));
    let options = MySqlConnectOptions::new().host("172.29.92.20")
        .username(&env::var("MYSQL_USER").unwrap())
        .password(&env::var("MYSQL_PASSWORD").unwrap())
        .database("unit3d_dualstack_journal_test");
    let pool = MySqlPoolOptions::new().max_connections(2)
        .acquire_timeout(Duration::from_secs(3)).connect_with(options).await.unwrap();
    let actual: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM peers WHERE torrent_id=20000")
        .fetch_one(&pool).await.unwrap();
    assert_eq!(actual, expected, "Exige fixture concentrada do laboratorio");
    let settings = Settings { peer: Policy { allow_private_addresses: true, ..Policy::default() },
        ..Settings::default() };
    let coordinator = Coordinator::open(pool, settings).await.unwrap();
    let mut measurements = Vec::new();
    for repeat in 1..=3 {
        for numwant in [0, 25] {
            coordinator.renew().await.unwrap();
            let request = ListRequest { torrent_id: 20000, user_id: 19999, numwant,
                seeds: false, leeches: true };
            let at = coordinator.now();
            let validate = |result: &unit3d_announce::dualstack::response::PeerList| {
                assert_eq!(result.counts.seeders, (expected*4/5) as u64);
                assert_eq!(result.counts.leechers, (expected/5) as u64);
                assert_eq!(result.logical_peers, numwant);
                assert!(result.ipv4.len()+result.ipv6.len() <= 24*numwant);
            };
            validate(&coordinator.select_at(request, at).unwrap());
            for _ in 0..200 { black_box(coordinator.select_at(request, at).unwrap()); }
            let mut micros = Vec::with_capacity(2000);
            for _ in 0..2000 {
                let start = Instant::now();
                let result = black_box(coordinator.select_at(request, at).unwrap());
                micros.push(start.elapsed().as_secs_f64()*1e6);
                validate(&result);
            }
            micros.sort_by(f64::total_cmp);
            measurements.push(json!({"repeat":repeat,"numwant":numwant,
                "p50_us":micros[999],"p95_us":micros[1899],"p99_us":micros[1979]}));
        }
    }
    assert_eq!(coordinator.backlog(), 0);
    coordinator.shutdown().await.unwrap();
    println!("{}", json!({"status":"passed","diagnostic_only":true,
        "peers":expected,"iterations_per_sample":2000,"measurements":measurements}));
}
