use std::{env, time::Duration};

use serde_json::Value;
use sqlx::{
    Row,
    mysql::{MySqlConnectOptions, MySqlPoolOptions},
};
use unit3d_announce::dualstack::{
    coordinator::{Coordinator, Credit, Identity, Settings},
    peer::{Announce, Event, Family, Operation, Outcome, Policy},
};

#[tokio::test]
#[ignore = "Exige fixture compartilhada history-v1 e banco MySQL isolado"]
async fn shared_history_contract() {
    assert_eq!(env::var("DUALSTACK_HISTORY_TESTS").as_deref(), Ok("1"));
    let contract: Value =
        serde_json::from_str(&std::fs::read_to_string("/lab/fixtures/history-v1.json").unwrap())
            .unwrap();
    let options = MySqlConnectOptions::new()
        .host("172.29.92.20")
        .username(&env::var("MYSQL_USER").unwrap())
        .password(&env::var("MYSQL_PASSWORD").unwrap())
        .database("unit3d_dualstack_journal_test");
    let pool = MySqlPoolOptions::new()
        .max_connections(4)
        .acquire_timeout(Duration::from_secs(3))
        .connect_with(options)
        .await
        .unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT DATABASE()")
            .fetch_one(&pool)
            .await
            .unwrap(),
        "unit3d_dualstack_journal_test"
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM tracker_ownership WHERE id=1"
        )
        .fetch_one(&pool)
        .await
        .unwrap(),
        0
    );
    for statement in [
        "DELETE FROM peers",
        "DELETE FROM history",
        "UPDATE users SET uploaded=0,downloaded=0",
        "UPDATE torrents SET seeders=0,leechers=0,seeders_ipv4=0,seeders_ipv6=0,leechers_ipv4=0,leechers_ipv6=0,times_completed=0",
    ] {
        sqlx::query(statement).execute(&pool).await.unwrap();
    }
    let c = Coordinator::open(
        pool.clone(),
        Settings {
            peer: Policy {
                endpoint_ttl: contract["endpoint_ttl"].as_u64().unwrap(),
                min_interval: 0,
                ..Policy::default()
            },
            seedtime_max_interval: contract["seedtime_max_interval"].as_u64().unwrap(),
            ..Settings::default()
        },
    )
    .await
    .unwrap();
    let base = c.now();
    for (step, op) in contract["operations"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
    {
        let id = Identity {
            user_id: 12001,
            torrent_id: 12001,
            peer_id: [op["peer"].as_str().unwrap().as_bytes()[0]; 20],
        };
        let family = if op["family"].as_u64().unwrap_or(4) == 4 {
            Family::V4
        } else {
            Family::V6
        };
        let operation = match op["kind"].as_str().unwrap_or("announce") {
            "expire" => Operation::Expire,
            "probe" => {
                let endpoint = c.peer(id).unwrap().endpoints.get(family).unwrap().clone();
                Operation::Probe {
                    ip: endpoint.ip,
                    port: endpoint.port,
                    revision: endpoint.revision,
                    connectable: true,
                }
            }
            _ => {
                let event = match op["event"].as_str().unwrap_or("") {
                    "started" => Event::Started,
                    "completed" => Event::Completed,
                    "stopped" => Event::Stopped,
                    _ => Event::Empty,
                };
                Operation::Announce(Announce {
                    event,
                    ip: if family == Family::V4 {
                        "192.0.2.30"
                    } else {
                        "2001:db8::30"
                    }
                    .parse()
                    .unwrap(),
                    port: if event == Event::Stopped { 0 } else { 6881 },
                    uploaded: 1000,
                    downloaded: 0,
                    left: op["left"].as_str().unwrap_or("0").parse().unwrap(),
                    visible: true,
                    agent: "history-contract".into(),
                })
            }
        };
        let result = c
            .publish_at(
                id,
                operation,
                Credit::default(),
                None,
                base + op["at"].as_u64().unwrap(),
                false,
            )
            .unwrap();
        assert_eq!(
            result.outcome,
            if op["ignored"].as_bool().unwrap_or(false) {
                Outcome::Ignored
            } else {
                Outcome::Accepted
            },
            "step {step}"
        );
        let batch = c.batch();
        c.persist_batch(&batch).await.unwrap();
        assert_eq!(c.persist_batch(&batch).await.unwrap(), 0);
        c.flush().await.unwrap();
        let h = sqlx::query(
            "SELECT seedtime,active,seeder FROM history WHERE user_id=12001 AND torrent_id=12001",
        )
        .fetch_one(&pool)
        .await
        .unwrap();
        let t = sqlx::query("SELECT seeders,leechers,times_completed FROM torrents WHERE id=12001")
            .fetch_one(&pool)
            .await
            .unwrap();
        let seeders = op["seeders"].as_i64().unwrap();
        let leechers = op["leechers"].as_i64().unwrap();
        assert_eq!(
            h.get::<u64, _>("seedtime"),
            op["seedtime"].as_u64().unwrap(),
            "step {step}"
        );
        assert_eq!(h.get::<bool, _>("active"), seeders + leechers > 0);
        assert_eq!(h.get::<bool, _>("seeder"), seeders > 0);
        assert_eq!(i64::from(t.get::<i32, _>("seeders")), seeders);
        assert_eq!(i64::from(t.get::<i32, _>("leechers")), leechers);
        assert_eq!(
            i64::from(t.get::<i32, _>("times_completed")),
            op["completed"].as_i64().unwrap()
        );
        assert_eq!(
            sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM peer_ips")
                .fetch_one(&pool)
                .await
                .unwrap(),
            op["endpoints"].as_i64().unwrap()
        );
        assert_eq!(
            sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM history")
                .fetch_one(&pool)
                .await
                .unwrap(),
            1
        );
        assert_eq!(
            sqlx::query_scalar::<_, u64>("SELECT uploaded FROM users WHERE id=12001")
                .fetch_one(&pool)
                .await
                .unwrap(),
            0
        );
    }
    c.shutdown().await.unwrap();
    println!(
        "PASS contrato compartilhado: 23 operacoes, seedtime 251, uma conclusao e historico unico"
    );
}
