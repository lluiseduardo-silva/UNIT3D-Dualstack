use super::*;

async fn drained(c:&Coordinator) {
    tokio::time::timeout(Duration::from_secs(8),async {
        while c.backlog()>0 {tokio::time::sleep(Duration::from_millis(10)).await;}
    }).await.expect("Journal nao drenou");
}

pub async fn run(pool:&MySqlPool,settings:Settings) {
    for (seconds,stop_during) in [(9,false),(12,false),(9,true)] {
        reset(pool).await;
        let c=Arc::new(Coordinator::open(pool.clone(),settings).await.unwrap());
        for (family,upload) in [(4,1000),(6,1100)] {c.publish(ID,request(family,upload,Event::Started),Credit::default(),None).unwrap();}
        let mut blocker=pool.begin().await.unwrap();
        sqlx::query("SELECT id FROM users WHERE id=12001 FOR UPDATE").fetch_one(&mut *blocker).await.unwrap();
        let (stop_tx,stop_rx)=tokio::sync::watch::channel(false);
        let task={let c=c.clone();tokio::spawn(async move {c.run(stop_rx).await})};
        tokio::time::sleep(Duration::from_secs(3)).await;
        if stop_during {stop_tx.send(true).unwrap();}
        tokio::time::sleep(Duration::from_secs(seconds-3)).await;
        assert!(!task.is_finished(),"Nao pode descartar transacao/fila por demora");
        assert_eq!(credit(pool).await,0);assert_eq!(c.backlog(),2);
        if seconds>10 || stop_during {
            assert!(matches!(c.publish(ID,request(4,1200,Event::Completed),Credit::default(),None),Err(Error::Unavailable)));
        }
        blocker.rollback().await.unwrap();
        drained(&c).await;
        if !stop_during {
            tokio::time::timeout(Duration::from_secs(3),async {
                loop {
                    match c.publish(ID,request(4,1200,Event::Completed),Credit::default(),None) {
                        Ok(_) => break,
                        Err(Error::Unavailable) => tokio::time::sleep(Duration::from_millis(10)).await,
                        Err(e) => panic!("Falha apos recuperacao: {e}"),
                    }
                }
            }).await.unwrap();
            stop_tx.send(true).unwrap();
        }
        tokio::time::timeout(Duration::from_secs(8),task).await.unwrap().unwrap().unwrap();
        assert_eq!(credit(pool).await,if stop_during {100} else {200});
        assert_eq!(c.backlog(),0);assert_eq!(count(pool,"peer_ips").await,2);
        assert!(matches!(c.publish(ID,request(4,1300,Event::Completed),Credit::default(),None),Err(Error::Unavailable)));
        let live:i64=sqlx::query_scalar("SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM tracker_ownership WHERE id=1").fetch_one(pool).await.unwrap();
        assert_eq!(live,0);
        println!("PASS lote bloqueado {seconds}s, parada={stop_during}: sem perda/duplicacao, credito exato, lease liberada");
    }

    // Timeout de renovacao com aquisicao real por outro coordenador antes do retry.
    reset(pool).await;
    let c=Arc::new(Coordinator::open(pool.clone(),settings).await.unwrap());
    for (family,upload) in [(4,1000),(6,1100)] {c.publish(ID,request(family,upload,Event::Started),Credit::default(),None).unwrap();}
    let mut blocker=pool.begin().await.unwrap();
    sqlx::query("SELECT id FROM tracker_ownership WHERE id=1 FOR UPDATE").fetch_one(&mut *blocker).await.unwrap();
    let (_stop_tx,stop_rx)=tokio::sync::watch::channel(false);
    let task={let c=c.clone();tokio::spawn(async move {c.run(stop_rx).await})};
    tokio::time::sleep(Duration::from_millis(3400)).await;
    assert!(!task.is_finished());assert_eq!(c.backlog(),2);
    // UTC_TIMESTAMP e fixado no inicio da query, antes da espera do lock.
    // Expirar so "agora - 1s" ainda permite a renovacao enviada ha 3s.
    // Vencimento anterior a TODAS as consultas pendentes; aquisicao pelo produto.
    sqlx::query("UPDATE tracker_ownership SET lease_expires_at='2000-01-01 00:00:00' WHERE id=1").execute(&mut *blocker).await.unwrap();
    blocker.commit().await.unwrap();
    let next=Coordinator::open(pool.clone(),settings).await.unwrap();
    assert!(next.generation()>c.generation());
    assert!(matches!(tokio::time::timeout(Duration::from_secs(8),task).await.unwrap().unwrap(),Err(Error::Unavailable)));
    assert_eq!(c.backlog(),2);assert_eq!(credit(pool).await,0);
    assert!(c.persist_batch(&c.batch()).await.is_err());
    assert!(matches!(c.publish(ID,request(4,1200,Event::Completed),Credit::default(),None),Err(Error::Unavailable)));
    next.publish(ID,request(4,1000,Event::Started),Credit::default(),None).unwrap();
    next.publish(ID,request(6,1100,Event::Started),Credit::default(),None).unwrap();
    next.shutdown().await.unwrap();assert_eq!(credit(pool).await,100);
    println!("PASS perda real de propriedade: geracao antiga nao renova/reabre/persiste; nova confirma credito uma vez");
}
