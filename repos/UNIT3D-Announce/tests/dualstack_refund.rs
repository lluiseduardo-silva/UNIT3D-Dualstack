use std::{env, path::Path, sync::Arc, time::Duration};

use sqlx::{
    Row,
    mysql::{MySqlConnectOptions, MySqlPoolOptions},
};
use unit3d_announce::dualstack::{
    coordinator::{Coordinator, Credit, Identity, Settings},
    peer::{Announce, Event, Family, Operation, Outcome, Policy},
};

async fn wait_signal(name: &str) {
    tokio::time::timeout(Duration::from_secs(90), async {
        while !Path::new(&format!("/signals/{name}")).exists() {
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .expect("Sinal do consumidor reembolso nao chegou");
}

fn announce(family: u8, uploaded: u64) -> Operation {
    Operation::Announce(Announce {
        event: Event::Empty,
        ip: if family == 4 {
            "192.0.2.30"
        } else {
            "2001:db8::30"
        }
        .parse()
        .unwrap(),
        port: 6881,
        uploaded,
        downloaded: uploaded - 1000,
        left: 0,
        visible: true,
        agent: "dualstack-refund-test".into(),
    })
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Exige runner reembolso/PHP, MySQL real e diretorio de sinais isolado"]
async fn refund_and_rust_writer_contention() {
    assert_eq!(env::var("DUALSTACK_REFUND_TESTS").as_deref(), Ok("1"));
    wait_signal("prepared").await;
    let options = MySqlConnectOptions::new()
        .host("172.29.92.20")
        .username(&env::var("MYSQL_USER").unwrap())
        .password(&env::var("MYSQL_PASSWORD").unwrap())
        .database("unit3d_dualstack_journal_test");
    let pool = MySqlPoolOptions::new()
        .max_connections(8)
        .acquire_timeout(Duration::from_secs(3))
        .connect_with(options)
        .await
        .expect("MySQL isolado indisponivel");
    let database: String = sqlx::query_scalar("SELECT DATABASE()")
        .fetch_one(&pool)
        .await
        .unwrap();
    assert_eq!(database, "unit3d_dualstack_journal_test");
    let isolation: String = sqlx::query_scalar("SELECT @@transaction_isolation")
        .fetch_one(&pool)
        .await
        .unwrap();
    assert_eq!(isolation, "REPEATABLE-READ");
    let c = Arc::new(
        Coordinator::open(
            pool.clone(),
            Settings {
                peer: Policy {
                    min_interval: 0,
                    ..Policy::default()
                },
                batch_size: 500,
                ..Settings::default()
            },
        )
        .await
        .unwrap(),
    );
    let at = c.now() - 3600;
    for user_id in 12001..=12003 {
        for torrent_id in 12001..=12002 {
            let id = Identity {
                user_id,
                torrent_id,
                peer_id: [b'B'; 20],
            };
            for family in [4, 6] {
                assert_eq!(
                    c.publish_at(
                        id,
                        announce(family, 1000),
                        Credit::default(),
                        None,
                        at,
                        false
                    )
                    .unwrap()
                    .outcome,
                    Outcome::Accepted
                );
            }
            let endpoint = c
                .peer(id)
                .unwrap()
                .endpoints
                .get(Family::V6)
                .unwrap()
                .clone();
            assert_eq!(
                c.publish_at(
                    id,
                    Operation::Probe {
                        ip: endpoint.ip,
                        port: endpoint.port,
                        revision: endpoint.revision,
                        connectable: true
                    },
                    Credit::default(),
                    None,
                    at,
                    false
                )
                .unwrap()
                .outcome,
                Outcome::Accepted
            );
        }
    }
    c.flush().await.unwrap();
    for step in 1..=80 {
        for user_id in 12001..=12003 {
            for torrent_id in 12001..=12002 {
                let id = Identity {
                    user_id,
                    torrent_id,
                    peer_id: [b'B'; 20],
                };
                c.publish(id, announce(4, 1000 + step * 100), Credit::default(), None)
                    .unwrap();
            }
        }
    }
    let batch = c.batch();
    assert_eq!(batch.len(), 480);
    std::fs::write("/signals/ready", b"ready").unwrap();
    wait_signal("go").await;
    c.renew().await.unwrap();
    let mut writers = Vec::new();
    for _ in 0..4 {
        let c = c.clone();
        let batch = batch.clone();
        writers.push(tokio::spawn(async move {
            for change in batch {
                c.persist_batch(&[change]).await.unwrap();
            }
        }));
    }
    for writer in writers {
        writer.await.unwrap();
    }
    c.shutdown().await.unwrap();
    assert_eq!(c.backlog(), 0);
    for user_id in 12001..=12003 {
        let row = sqlx::query("SELECT uploaded FROM users WHERE id=?")
            .bind(user_id)
            .fetch_one(&pool)
            .await
            .unwrap();
        assert_eq!(row.get::<u64, _>("uploaded"), 16000);
    }
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM peers")
            .fetch_one(&pool)
            .await
            .unwrap(),
        6
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM peer_ips")
            .fetch_one(&pool)
            .await
            .unwrap(),
        12
    );
    std::fs::write("/signals/rust-done", b"done").unwrap();
    println!(
        "PASS quatro tarefas Rust com um gravador SQL, 480 transicoes reentregues, credito unico, seis peers e doze endpoints"
    );
}
