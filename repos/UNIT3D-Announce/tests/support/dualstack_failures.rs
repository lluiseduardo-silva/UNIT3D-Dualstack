use super::*;
use std::time::Instant;

async fn metric(pool:&MySqlPool,name:&str)->u64 {
    assert!(matches!(name,"Innodb_row_lock_waits" | "Innodb_row_lock_current_waits"));
    sqlx::query(&format!("SHOW GLOBAL STATUS LIKE '{name}'")).fetch_one(pool).await.unwrap()
        .get::<String,_>(1).parse().unwrap()
}

pub async fn run(pool:&MySqlPool,settings:Settings) {
    reset(pool).await;
    let mut blocker=pool.begin().await.unwrap();
    sqlx::query("SELECT id FROM tracker_ownership WHERE id=1 FOR UPDATE").fetch_one(&mut *blocker).await.unwrap();
    let started=Instant::now();
    let result=Coordinator::open(pool.clone(),settings).await;
    assert!(matches!(result,Err(Error::Timeout("aquisicao da lease"))));
    assert!(started.elapsed()<Duration::from_secs(5));
    blocker.rollback().await.unwrap();
    println!("PASS aquisicao bloqueada termina em 3 s sem abrir entrada");

    let c=Coordinator::open(pool.clone(),settings).await.unwrap();
    let mut blocker=pool.begin().await.unwrap();
    sqlx::query("SELECT id FROM tracker_ownership WHERE id=1 FOR UPDATE").fetch_one(&mut *blocker).await.unwrap();
    let started=Instant::now();
    assert!(matches!(c.renew().await,Err(Error::Timeout("renovacao da lease"))));
    assert!(started.elapsed()<Duration::from_secs(5));
    assert!(matches!(c.publish(ID,request(4,1000,Event::Started),Credit::default(),None),Err(Error::Unavailable)));
    blocker.rollback().await.unwrap();
    c.shutdown().await.unwrap();
    println!("PASS renovacao bloqueada termina em 3 s e fecha entrada");

    let c=Coordinator::open(pool.clone(),settings).await.unwrap();
    let mut blocker=pool.begin().await.unwrap();
    sqlx::query("SELECT id FROM tracker_ownership WHERE id=1 FOR UPDATE").fetch_one(&mut *blocker).await.unwrap();
    let started=Instant::now();
    assert!(matches!(c.shutdown().await,Err(Error::Timeout("liberacao da lease"))));
    assert!(started.elapsed()<Duration::from_secs(5));
    blocker.rollback().await.unwrap();
    c.shutdown().await.unwrap();
    println!("PASS liberacao bloqueada termina em 3 s");

    // Apenas o pool deste ensaio usa lock wait curto; a configuracao global segue 10 s.
    let options=sqlx::mysql::MySqlConnectOptions::new().host("172.29.92.20")
        .username(&env::var("MYSQL_USER").unwrap()).password(&env::var("MYSQL_PASSWORD").unwrap())
        .database(&test_database());
    let retry_pool=MySqlPoolOptions::new().max_connections(4).acquire_timeout(Duration::from_secs(3))
        .after_connect(|connection,_| Box::pin(async move {
            sqlx::query("SET SESSION innodb_lock_wait_timeout=1").execute(connection).await?; Ok(())
        })).connect_with(options).await.unwrap();

    reset(pool).await;
    let c=Arc::new(Coordinator::open(retry_pool.clone(),settings).await.unwrap());
    for (family,upload) in [(4,1000),(6,1100)] { c.publish(ID,request(family,upload,Event::Started),Credit::default(),None).unwrap(); }
    let mut blocker=pool.begin().await.unwrap();
    sqlx::query("SELECT id FROM users WHERE id=12001 FOR UPDATE").fetch_one(&mut *blocker).await.unwrap();
    let writer={let c=c.clone(); tokio::spawn(async move {c.flush().await})};
    tokio::time::sleep(Duration::from_millis(2300)).await;
    blocker.rollback().await.unwrap();
    assert_eq!(writer.await.unwrap().unwrap(),2);
    assert_eq!(c.retry_count(),2); assert_eq!(credit(pool).await,100); assert_eq!(c.backlog(),0);
    c.shutdown().await.unwrap();
    println!("PASS lock wait 1205 repetido duas vezes, terceiro lote confirma credito 100 uma vez");

    reset(pool).await;
    let c=Coordinator::open(retry_pool.clone(),settings).await.unwrap();
    for (family,upload) in [(4,1000),(6,1100)] { c.publish(ID,request(family,upload,Event::Started),Credit::default(),None).unwrap(); }
    let mut blocker=pool.begin().await.unwrap();
    sqlx::query("SELECT id FROM users WHERE id=12001 FOR UPDATE").fetch_one(&mut *blocker).await.unwrap();
    let started=Instant::now();
    let error=c.flush().await.unwrap_err();
    assert!(error.retryable()); assert_eq!(c.retry_count(),2); assert!(started.elapsed()<Duration::from_secs(5));
    assert_eq!(c.backlog(),2); assert_eq!(credit(pool).await,0);
    assert!(matches!(c.publish(ID,request(4,1200,Event::Completed),Credit::default(),None),Err(Error::Unavailable)));
    blocker.rollback().await.unwrap();
    c.shutdown().await.unwrap(); assert_eq!(credit(pool).await,100);
    println!("PASS retry esgotado em tres tentativas preserva fila, fecha entrada e permite drenagem");

    reset(pool).await;
    let c=Arc::new(Coordinator::open(pool.clone(),settings).await.unwrap());
    for (family,upload) in [(4,1000),(6,1100)] { c.publish(ID,request(family,upload,Event::Started),Credit::default(),None).unwrap(); }
    let before_waits=metric(pool,"Innodb_row_lock_waits").await;
    let mut blocker=pool.begin().await.unwrap();
    // Mais undo que o escritor, para que InnoDB escolha o lote como vitima.
    sqlx::query("UPDATE users SET uploaded=uploaded+1 WHERE id BETWEEN 12002 AND 12006").execute(&mut *blocker).await.unwrap();
    sqlx::query("SELECT id FROM torrents WHERE id=12001 FOR UPDATE").fetch_one(&mut *blocker).await.unwrap();
    let writer={let c=c.clone(); tokio::spawn(async move {c.flush().await})};
    tokio::time::timeout(Duration::from_secs(3),async {
        while metric(pool,"Innodb_row_lock_current_waits").await==0 {tokio::time::sleep(Duration::from_millis(10)).await;}
    }).await.unwrap();
    sqlx::query("SELECT id FROM users WHERE id=12001 FOR UPDATE").fetch_one(&mut *blocker).await.unwrap();
    blocker.rollback().await.unwrap();
    assert_eq!(writer.await.unwrap().unwrap(),2);
    assert!(metric(pool,"Innodb_row_lock_waits").await>before_waits);
    assert_eq!(c.retry_count(),1); assert_eq!(c.deadlock_retry_count(),1); assert_eq!(credit(pool).await,100);
    c.shutdown().await.unwrap();
    println!("PASS deadlock 1213 real, espera InnoDB observada, retry confirma credito 100 uma vez");

    reset(pool).await;
    let c=Arc::new(Coordinator::open(pool.clone(),settings).await.unwrap());
    let (stop_tx,stop_rx)=tokio::sync::watch::channel(false);
    let worker={let c=c.clone(); tokio::spawn(async move {c.run(stop_rx).await})};
    c.publish(ID,request(4,1000,Event::Started),Credit::default(),None).unwrap();
    tokio::time::sleep(Duration::from_secs(12)).await;
    c.publish(ID,request(6,1100,Event::Started),Credit::default(),None).unwrap();
    stop_tx.send(true).unwrap();
    tokio::time::timeout(Duration::from_secs(5),worker).await.unwrap().unwrap().unwrap();
    assert_eq!(c.backlog(),0); assert_eq!(credit(pool).await,100);
    assert!(matches!(c.publish(ID,request(4,1200,Event::Completed),Credit::default(),None),Err(Error::Unavailable)));
    let live:i64=sqlx::query_scalar("SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM tracker_ownership WHERE id=1").fetch_one(pool).await.unwrap();
    assert_eq!(live,0);
    println!("PASS supervisor renova por 12 s, encerra, drena e libera lease");

    reset(pool).await;
    let c=Arc::new(Coordinator::open(pool.clone(),settings).await.unwrap());
    for (family,upload) in [(4,1000),(6,1100)] { c.publish(ID,request(family,upload,Event::Started),Credit::default(),None).unwrap(); }
    let mut blocker=pool.begin().await.unwrap();
    sqlx::query("SELECT id FROM tracker_ownership WHERE id=1 FOR UPDATE").fetch_one(&mut *blocker).await.unwrap();
    let (stop_tx,stop_rx)=tokio::sync::watch::channel(false);
    let worker={let c=c.clone(); tokio::spawn(async move {c.run(stop_rx).await})};
    tokio::time::sleep(Duration::from_millis(3500)).await;
    assert!(!worker.is_finished());
    assert_eq!(c.backlog(),2); assert_eq!(credit(pool).await,0);
    assert!(matches!(c.publish(ID,request(4,1200,Event::Completed),Credit::default(),None),Err(Error::Unavailable)));
    blocker.rollback().await.unwrap();
    stop_tx.send(true).unwrap();
    tokio::time::timeout(Duration::from_secs(8),worker).await.unwrap().unwrap().unwrap();
    assert_eq!(c.backlog(),0); assert_eq!(credit(pool).await,100);
    println!("PASS supervisor preserva fila apos timeout de renovacao e drena apos desbloqueio");

    reset(pool).await;
    let c=Arc::new(Coordinator::open(pool.clone(),settings).await.unwrap());
    for (family,upload) in [(4,1000),(6,1100)] { c.publish(ID,request(family,upload,Event::Started),Credit::default(),None).unwrap(); }
    sqlx::query("ALTER TABLE history ADD CONSTRAINT dualstack_test_fail CHECK (uploaded=0)").execute(pool).await.unwrap();
    let (_stop_tx,stop_rx)=tokio::sync::watch::channel(false);
    let result=tokio::time::timeout(Duration::from_secs(5),c.run(stop_rx)).await.unwrap();
    sqlx::query("ALTER TABLE history DROP CHECK dualstack_test_fail").execute(pool).await.unwrap();
    let error=result.unwrap_err(); assert!(!error.retryable()); assert_eq!(c.retry_count(),0);
    assert_eq!(c.backlog(),2); assert_eq!(credit(pool).await,0);
    assert!(matches!(c.publish(ID,request(4,1200,Event::Completed),Credit::default(),None),Err(Error::Unavailable)));
    c.shutdown().await.unwrap(); assert_eq!(credit(pool).await,100);
    println!("PASS supervisor falha fechada, sem retry de erro permanente, preserva fila e drena depois da correcao");
    retry_pool.close().await;
}
