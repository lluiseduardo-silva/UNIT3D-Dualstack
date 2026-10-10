use super::*;

pub async fn run(pool: &MySqlPool, settings: Settings) {
    reset(pool).await;
    let c = Coordinator::open(pool.clone(), settings).await.unwrap();
    for family in [4, 6] {
        c.publish(
            ID,
            request(family, u64::MAX, Event::Started),
            Credit::default(),
            None,
        )
        .unwrap();
    }
    let other = Identity {
        user_id: 12002,
        ..ID
    };
    c.publish(
        other,
        request(4, 1000, Event::Started),
        Credit::default(),
        None,
    )
    .unwrap();
    let snapshot = serde_json::to_value(c.torrent_snapshot(ID.torrent_id)).unwrap();
    assert_eq!(snapshot["capabilities"]["peer_schema"], 1);
    assert_eq!(snapshot["capabilities"]["dualstack"], true);
    assert_eq!(snapshot["seeders"], 2);
    assert_eq!(snapshot["seeders_ipv4"], 2);
    assert_eq!(snapshot["seeders_ipv6"], 1);
    assert_eq!(snapshot["peers"].as_object().unwrap().len(), 2);
    let hex: String = ID.peer_id.iter().map(|b| format!("{b:02x}")).collect();
    let key = format!("12001-{hex}");
    let peer = &snapshot["peers"][&key];
    assert_eq!(peer["uploaded"], u64::MAX.to_string());
    assert_eq!(peer["endpoints"].as_array().unwrap().len(), 2);
    assert!(peer["endpoints"][0]["connectable"].is_null());
    assert_eq!(c.user_counts(12001).seeders, 1);
    c.register_torrent(ID.torrent_id, 999);
    assert_eq!(
        c.torrent_snapshot(ID.torrent_id).times_completed,
        0,
        "Refresh administrativo nao sobrepoe contagem corrente"
    );
    for family in [4, 6] {
        c.publish(
            ID,
            request(family, u64::MAX, Event::Stopped),
            Credit::default(),
            None,
        )
        .unwrap();
    }
    let snapshot = serde_json::to_value(c.torrent_snapshot(ID.torrent_id)).unwrap();
    assert_eq!(snapshot["seeders"], 1);
    assert_eq!(snapshot["peers"][&key]["is_active"], false);
    assert_eq!(snapshot["peers"][&key]["endpoints"], serde_json::json!([]));
    assert_eq!(c.user_counts(12001).seeders, 0);
    c.shutdown().await.unwrap();
    let restored = Coordinator::open(pool.clone(), settings).await.unwrap();
    assert_eq!(
        serde_json::to_value(restored.torrent_snapshot(ID.torrent_id)).unwrap(),
        snapshot
    );
    restored.shutdown().await.unwrap();
    println!(
        "PASS API logica com endpoints, identidade entre usuarios, uint64 exato, contadores correntes e inativos preservados apos restart"
    );
}
