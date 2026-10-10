use sqlx::{MySqlPool, mysql::MySqlPoolOptions};
use std::{env, sync::Arc, time::Duration};
use unit3d_announce::dualstack::{
    coordinator::{Coordinator, Credit, Identity, Settings},
    peer::{Announce, Event, Operation, Policy},
};

const ID: Identity = Identity {
    user_id: 12001,
    torrent_id: 12001,
    peer_id: *b"-DS9200-000000000092",
};
fn request(family: u8, uploaded: u64) -> Operation {
    Operation::Announce(Announce {
        event: Event::Started,
        ip: if family == 4 {
            "192.0.2.30"
        } else {
            "2001:db8::30"
        }
        .parse()
        .unwrap(),
        port: 6881,
        uploaded,
        downloaded: 0,
        left: 0,
        visible: true,
        agent: "deletion-test".into(),
    })
}
async fn reset(pool: &MySqlPool) {
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM tracker_ownership WHERE id=1"
        )
        .fetch_one(pool)
        .await
        .unwrap(),
        0
    );
    sqlx::query("DELETE FROM peers")
        .execute(pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM history")
        .execute(pool)
        .await
        .unwrap();
    sqlx::query("UPDATE users SET uploaded=0,downloaded=0,deleted_at=NULL,tracker_removal_state=0 WHERE id BETWEEN 12001 AND 12020").execute(pool).await.unwrap();
    sqlx::query("UPDATE torrents SET deleted_at=NULL,tracker_removal_state=0,seeders=0,leechers=0,seeders_ipv4=0,seeders_ipv6=0,leechers_ipv4=0,leechers_ipv6=0,times_completed=0,balance=0 WHERE id BETWEEN 12001 AND 12020").execute(pool).await.unwrap();
}
async fn credit(pool: &MySqlPool) -> u64 {
    sqlx::query_scalar("SELECT uploaded FROM users WHERE id=12001")
        .fetch_one(pool)
        .await
        .unwrap()
}
async fn count(pool: &MySqlPool, table: &str) -> i64 {
    sqlx::query_scalar(&format!("SELECT COUNT(*) FROM {table}"))
        .fetch_one(pool)
        .await
        .unwrap()
}
async fn settle(c: &Coordinator) {
    for _ in 0..20 {
        c.renew().await.unwrap();
        if !c.remove_deleted().await.unwrap() {
            return;
        }
    }
    panic!("Remocao nao drenou");
}
async fn seed(c: &Coordinator) {
    c.publish(ID, request(4, 1000), Credit::default(), None)
        .unwrap();
    c.publish(ID, request(6, 1000), Credit::default(), None)
        .unwrap();
    c.flush().await.unwrap();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Exige MySQL real, DUALSTACK_MYSQL_TESTS=1 e banco isolado"]
async fn deletion_contract() {
    assert_eq!(env::var("DUALSTACK_MYSQL_TESTS").as_deref(), Ok("1"));
    let options = sqlx::mysql::MySqlConnectOptions::new()
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
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT DATABASE()")
            .fetch_one(&pool)
            .await
            .unwrap(),
        "unit3d_dualstack_journal_test"
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT @@transaction_isolation")
            .fetch_one(&pool)
            .await
            .unwrap(),
        "REPEATABLE-READ"
    );
    assert_eq!(
        sqlx::query_scalar::<_, u64>("SELECT @@innodb_lock_wait_timeout")
            .fetch_one(&pool)
            .await
            .unwrap(),
        10
    );
    let metrics = sqlx::query_as::<_, (String, i64)>(
        "SELECT NAME,COUNT FROM information_schema.INNODB_METRICS WHERE NAME IN ('lock_deadlocks','lock_timeouts') ORDER BY NAME",
    );
    let before = metrics.fetch_all(&pool).await.unwrap();
    let settings = Settings {
        max_peers: 300,
        peer: Policy {
            min_interval: 0,
            ..Policy::default()
        },
        ..Settings::default()
    };

    for table in ["users", "torrents"] {
        reset(&pool).await;
        let c = Coordinator::open(pool.clone(), settings).await.unwrap();
        seed(&c).await;
        c.publish(ID, request(6, 1100), Credit::default(), None)
            .unwrap();
        let old = c.batch();
        // Lote confirmado mas ainda presente na fila simula perda do reconhecimento.
        c.persist_batch(&old).await.unwrap();
        sqlx::query(&format!(
            "UPDATE {table} SET deleted_at=UTC_TIMESTAMP() WHERE id=12001"
        ))
        .execute(&pool)
        .await
        .unwrap();
        settle(&c).await;
        assert_eq!(c.persist_batch(&old).await.unwrap(), 0);
        assert_eq!(credit(&pool).await, 100);
        for t in ["peers", "peer_ips", "history"] {
            assert_eq!(count(&pool, t).await, 0);
        }
        assert!(
            c.publish(ID, request(4, 9999), Credit::default(), None)
                .is_err()
        );
        assert_eq!(
            sqlx::query_scalar::<_, u8>(&format!(
                "SELECT tracker_removal_state FROM {table} WHERE id=12001"
            ))
            .fetch_one(&pool)
            .await
            .unwrap(),
            2
        );
        assert_eq!(
            sqlx::query_scalar::<_, i32>("SELECT seeders FROM torrents WHERE id=12001")
                .fetch_one(&pool)
                .await
                .unwrap(),
            0
        );
        c.shutdown().await.unwrap();
        let restored = Coordinator::open(pool.clone(), settings).await.unwrap();
        assert!(
            restored
                .publish(ID, request(6, 1200), Credit::default(), None)
                .is_err()
        );
        restored.shutdown().await.unwrap();
        assert_eq!(credit(&pool).await, 100);
        println!(
            "PASS remocao {table}, dois endpoints, credito pendente 100, reentrega e restart sem ressurreicao"
        );
    }

    reset(&pool).await;
    let c = Coordinator::open(pool.clone(), settings).await.unwrap();
    seed(&c).await;
    let other = Identity {
        user_id: 12002,
        ..ID
    };
    c.publish(other, request(4, 1000), Credit::default(), None)
        .unwrap();
    c.publish(other, request(4, 1100), Credit::default(), None)
        .unwrap();
    sqlx::query("UPDATE users SET deleted_at=UTC_TIMESTAMP() WHERE id=12001")
        .execute(&pool)
        .await
        .unwrap();
    settle(&c).await;
    assert_eq!(count(&pool, "peers").await, 1);
    let counts: (i32, u32, u32) =
        sqlx::query_as("SELECT seeders,seeders_ipv4,seeders_ipv6 FROM torrents WHERE id=12001")
            .fetch_one(&pool)
            .await
            .unwrap();
    assert_eq!(counts, (1, 1, 0));
    c.publish(other, request(6, 1200), Credit::default(), None)
        .unwrap();
    c.shutdown().await.unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, u64>("SELECT uploaded FROM users WHERE id=12002")
            .fetch_one(&pool)
            .await
            .unwrap(),
        200
    );
    println!("PASS preserva outro usuario no torrent e contadores logicos por familia");

    reset(&pool).await;
    let c = Coordinator::open(pool.clone(), settings).await.unwrap();
    seed(&c).await;
    c.publish(ID, request(4, 1100), Credit::default(), None)
        .unwrap();
    sqlx::query("UPDATE users SET deleted_at=UTC_TIMESTAMP() WHERE id=12001")
        .execute(&pool)
        .await
        .unwrap();
    let name: String = sqlx::query_scalar("SELECT name FROM torrents WHERE id=12001")
        .fetch_one(&pool)
        .await
        .unwrap();
    sqlx::query("UPDATE torrents SET name='dualstack-deletion-failure' WHERE id=12001")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("ALTER TABLE torrents ADD CONSTRAINT dualstack_deletion_failure CHECK (name<>'dualstack-deletion-failure' OR seeders>0)").execute(&pool).await.unwrap();
    let failed = c.remove_deleted().await;
    sqlx::query("ALTER TABLE torrents DROP CHECK dualstack_deletion_failure")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("UPDATE torrents SET name=? WHERE id=12001")
        .bind(name)
        .execute(&pool)
        .await
        .unwrap();
    assert!(failed.is_err());
    assert_eq!(count(&pool, "peers").await, 1);
    assert_eq!(count(&pool, "peer_ips").await, 2);
    assert_eq!(credit(&pool).await, 100);
    assert_eq!(
        sqlx::query_scalar::<_, u8>("SELECT tracker_removal_state FROM users WHERE id=12001")
            .fetch_one(&pool)
            .await
            .unwrap(),
        1
    );
    // Simula a expiracao depois da queda, somente no banco exclusivo.
    sqlx::query("UPDATE tracker_ownership SET lease_expires_at=UTC_TIMESTAMP(3)-INTERVAL 1 SECOND WHERE id=1").execute(&pool).await.unwrap();
    let restored = Coordinator::open(pool.clone(), settings).await.unwrap();
    settle(&restored).await;
    restored.shutdown().await.unwrap();
    assert_eq!(credit(&pool).await, 100);
    assert_eq!(count(&pool, "history").await, 0);
    println!(
        "PASS falha CHECK reverte remocao, preserva credito e nova geracao retoma estado selado"
    );

    reset(&pool).await;
    let c = Arc::new(Coordinator::open(pool.clone(), settings).await.unwrap());
    seed(&c).await;
    sqlx::query("UPDATE users SET deleted_at=UTC_TIMESTAMP() WHERE id=12001")
        .execute(&pool)
        .await
        .unwrap();
    let mut lock = pool.begin().await.unwrap();
    sqlx::query("SELECT id FROM users WHERE id=12001 FOR UPDATE")
        .fetch_one(&mut *lock)
        .await
        .unwrap();
    let task = {
        let c = c.clone();
        tokio::spawn(async move { c.remove_deleted().await })
    };
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if c.publish(ID, request(4, 1000), Credit::default(), None)
                .is_err()
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    c.publish(other, request(4, 1000), Credit::default(), None)
        .unwrap();
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    lock.rollback().await.unwrap();
    assert!(
        c.publish(other, request(4, 1100), Credit::default(), None)
            .is_err()
    );
    assert_eq!(count(&pool, "peers").await, 1);
    c.shutdown().await.unwrap();
    assert_eq!(count(&pool, "peers").await, 1);
    println!(
        "PASS remocao sob lock bloqueia alvo, preserva outro recurso e cancelamento fecha entrada"
    );

    reset(&pool).await;
    let c = Coordinator::open(pool.clone(), settings).await.unwrap();
    seed(&c).await;
    for n in 0..205 {
        let mut id = ID;
        id.peer_id = [b'X'; 20];
        id.peer_id[..4].copy_from_slice(&u32::to_be_bytes(n));
        c.publish(id, request(4, 1000), Credit::default(), None)
            .unwrap();
    }
    sqlx::query("UPDATE users SET deleted_at=UTC_TIMESTAMP() WHERE id=12001")
        .execute(&pool)
        .await
        .unwrap();
    c.remove_deleted().await.unwrap();
    assert_eq!(count(&pool, "peers").await, 6);
    settle(&c).await;
    c.shutdown().await.unwrap();
    assert_eq!(count(&pool, "peers").await, 0);
    assert_eq!(before,sqlx::query_as::<_,(String,i64)>("SELECT NAME,COUNT FROM information_schema.INNODB_METRICS WHERE NAME IN ('lock_deadlocks','lock_timeouts') ORDER BY NAME").fetch_all(&pool).await.unwrap());
    println!("PASS lotes de 200, contencao real sem aumento de deadlocks/timeouts");
    reset(&pool).await;
    println!("RUST_DELETION_PASSED");
}
