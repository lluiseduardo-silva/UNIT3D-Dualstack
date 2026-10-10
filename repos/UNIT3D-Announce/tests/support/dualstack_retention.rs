use super::*;

fn inactive(c: &Coordinator, id: Identity, at: u64) {
    let Operation::Announce(mut first) = request(4, 1000, Event::Started) else {
        unreachable!()
    };
    first.left = 100;
    c.publish_at(
        id,
        Operation::Announce(first),
        Credit::default(),
        None,
        at,
        false,
    )
    .unwrap();
    c.publish_at(
        id,
        request(4, 1100, Event::Completed),
        Credit::default(),
        None,
        at + 1,
        false,
    )
    .unwrap();
    c.publish_at(
        id,
        request(4, 1100, Event::Stopped),
        Credit::default(),
        None,
        at + 2,
        false,
    )
    .unwrap();
}

pub async fn run(pool: &MySqlPool, settings: Settings) {
    let settings = Settings {
        inactive_retention: 7200,
        batch_size: 1,
        ..settings
    };
    reset(pool).await;
    let c = Coordinator::open(pool.clone(), settings).await.unwrap();
    let old = c.now() - 8000;
    inactive(&c, ID, old);
    assert_eq!(
        c.retire().await.unwrap(),
        0,
        "Transicoes pendentes nao podem ser apagadas"
    );
    while c.backlog() > 0 {
        c.flush().await.unwrap();
    }
    let second = Identity {
        peer_id: [b'2'; 20],
        ..ID
    };
    let recent = Identity {
        peer_id: [b'3'; 20],
        ..ID
    };
    let active = Identity {
        peer_id: [b'4'; 20],
        ..ID
    };
    inactive(&c, second, old + 3);
    inactive(&c, recent, c.now());
    c.publish(
        active,
        request(6, 1000, Event::Started),
        Credit::default(),
        None,
    )
    .unwrap();
    while c.backlog() > 0 {
        c.flush().await.unwrap();
    }
    assert_eq!(
        c.retire().await.unwrap(),
        1,
        "Retencao respeita limite do lote"
    );
    assert!(c.peer(ID).is_none());
    assert_eq!(c.retire().await.unwrap(), 1);
    assert_eq!(c.retire().await.unwrap(), 0);
    assert_eq!(count(pool, "peers").await, 2);
    assert!(c.peer(recent).is_some() && c.peer(active).is_some());
    assert_eq!(credit(pool).await, 300);
    assert_eq!(count(pool, "history").await, 1);
    let result = c
        .publish(ID, request(4, 50, Event::Started), Credit::default(), None)
        .unwrap();
    assert_eq!(
        (result.upload_delta, result.peer.unwrap().state_version),
        (0, 1)
    );
    c.publish(ID, request(6, 50, Event::Started), Credit::default(), None)
        .unwrap();
    c.publish(
        ID,
        request(6, 60, Event::Completed),
        Credit::default(),
        None,
    )
    .unwrap();
    c.shutdown().await.unwrap();
    assert_eq!(credit(pool).await, 310);
    assert_eq!(
        sqlx::query_scalar::<_, i32>("SELECT times_completed FROM torrents WHERE id=12001")
            .fetch_one(pool)
            .await
            .unwrap(),
        1
    );
    let c = Coordinator::open(pool.clone(), settings).await.unwrap();
    assert_eq!(c.peer(ID).unwrap().uploaded, 60);
    assert!(c.peer(second).is_none());
    c.shutdown().await.unwrap();
    println!(
        "PASS retencao somente confirmada, lote limitado, preserva recente/ativo/historico e reconexao sem duplicar credito ou conclusao"
    );

    reset(pool).await;
    let c = Arc::new(Coordinator::open(pool.clone(), settings).await.unwrap());
    inactive(&c, ID, c.now() - 8000);
    while c.backlog() > 0 {
        c.flush().await.unwrap();
    }
    let mut blocker = pool.begin().await.unwrap();
    sqlx::query("SELECT user_id FROM peers WHERE user_id=12001 FOR UPDATE")
        .fetch_all(&mut *blocker)
        .await
        .unwrap();
    let retire = {
        let c = c.clone();
        tokio::spawn(async move { c.retire().await })
    };
    tokio::time::timeout(Duration::from_secs(3), async {
        while !c.is_retiring(ID) {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
    assert!(matches!(
        c.publish(
            ID,
            request(4, 2000, Event::Started),
            Credit::default(),
            None
        ),
        Err(Error::Unavailable)
    ));
    c.publish(
        second,
        request(6, 1000, Event::Started),
        Credit::default(),
        None,
    )
    .unwrap();
    assert_eq!(c.peer(ID).unwrap().uploaded, 1100);
    assert_eq!(credit(pool).await, 100);
    blocker.rollback().await.unwrap();
    assert_eq!(retire.await.unwrap().unwrap(), 1);
    c.publish(
        ID,
        request(4, 2000, Event::Started),
        Credit::default(),
        None,
    )
    .unwrap();
    c.shutdown().await.unwrap();
    assert_eq!(credit(pool).await, 100);
    assert_eq!(count(pool, "peers").await, 2);
    println!(
        "PASS retencao bloqueada no SQL recusa somente a identidade reservada e preserva announces de outros peers"
    );

    reset(pool).await;
    let c = Arc::new(Coordinator::open(pool.clone(), settings).await.unwrap());
    inactive(&c, ID, c.now() - 8000);
    while c.backlog() > 0 {
        c.flush().await.unwrap();
    }
    let mut blocker = pool.begin().await.unwrap();
    sqlx::query("SELECT user_id FROM peers WHERE user_id=12001 FOR UPDATE")
        .fetch_all(&mut *blocker)
        .await
        .unwrap();
    let retire = {
        let c = c.clone();
        tokio::spawn(async move { c.retire().await })
    };
    tokio::time::timeout(Duration::from_secs(3), async {
        while !c.is_retiring(ID) {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
    retire.abort();
    assert!(retire.await.unwrap_err().is_cancelled());
    assert!(matches!(
        c.publish(
            second,
            request(4, 2000, Event::Started),
            Credit::default(),
            None
        ),
        Err(Error::Unavailable)
    ));
    blocker.rollback().await.unwrap();
    c.shutdown().await.unwrap();
    assert_eq!(count(pool, "peers").await, 1);
    assert_eq!(credit(pool).await, 100);
    let restored = Coordinator::open(pool.clone(), settings).await.unwrap();
    assert_eq!(restored.retire().await.unwrap(), 1);
    restored.shutdown().await.unwrap();
    assert_eq!(credit(pool).await, 100);
    println!(
        "PASS cancelamento da retencao fecha entrada, rollback preserva referencia e bootstrap permite concluir limpeza"
    );
}
