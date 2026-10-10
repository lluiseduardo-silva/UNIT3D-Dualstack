use super::*;

pub async fn run(pool:&MySqlPool,settings:Settings) {
    reset(pool).await;
    let generation:u64=sqlx::query_scalar("SELECT generation FROM tracker_ownership WHERE id=1").fetch_one(pool).await.unwrap();
    for batch_size in [0,501] {
        assert!(matches!(Coordinator::open(pool.clone(),Settings {batch_size,..settings}).await,Err(Error::Configuration)));
    }
    assert_eq!(sqlx::query_scalar::<_,u64>("SELECT generation FROM tracker_ownership WHERE id=1").fetch_one(pool).await.unwrap(),generation);

    // Cem transacoes reais: a cadencia antiga exige ~10 s mesmo com fila cheia.
    let c=Arc::new(Coordinator::open(pool.clone(),Settings {batch_size:1,..settings}).await.unwrap());
    for n in 0..100 { c.publish(ID,request(if n%2==0 {4} else {6},1000+n,Event::Started),Credit::default(),None).unwrap(); }
    let (stop_tx,stop_rx)=tokio::sync::watch::channel(false);
    let worker={let c=c.clone(); tokio::spawn(async move {c.run(stop_rx).await})};
    let drained=tokio::time::timeout(Duration::from_secs(3),async {
        while c.backlog()>0 {tokio::time::sleep(Duration::from_millis(5)).await;}
    }).await;
    stop_tx.send(true).unwrap();
    tokio::time::timeout(Duration::from_secs(5),worker).await.unwrap().unwrap().unwrap();
    assert!(drained.is_ok(),"Backlog cheio ainda limitado pelo timer de 100 ms");
    assert_eq!(credit(pool).await,99);
    assert_eq!(count(pool,"peer_ips").await,2);
    println!("PASS 100 lotes de uma transicao drenados em menos de 3 s, encerramento e credito unico");

    reset(pool).await;
    let c=Coordinator::open(pool.clone(),Settings {batch_size:500,..settings}).await.unwrap();
    for n in 0..1001 {c.publish(ID,request(if n%2==0 {4} else {6},1000+n,Event::Started),Credit::default(),None).unwrap();}
    assert_eq!(c.flush().await.unwrap(),500);
    assert_eq!(credit(pool).await,499);
    assert_eq!(c.flush().await.unwrap(),500);
    assert_eq!(credit(pool).await,999);
    c.shutdown().await.unwrap();
    assert_eq!(credit(pool).await,1000);
    assert_eq!(count(pool,"peer_ips").await,2);
    println!("PASS lotes 500/500/1 confirmam 1001 versoes sem duplicar credito; limites 0/501 recusados antes da lease");
}
