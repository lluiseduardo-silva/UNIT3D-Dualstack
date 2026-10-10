use super::*;
use unit3d_announce::dualstack::{
    peer::Family,
    response::{ListRequest, SwarmCounts},
};

pub async fn run(pool: &MySqlPool, settings: Settings) {
    reset(pool).await;
    let settings = Settings {
        peer: Policy {
            endpoint_ttl: 7200,
            ..settings.peer
        },
        ..settings
    };
    let c = Coordinator::open(pool.clone(), settings).await.unwrap();
    let at = c.now();
    for (family, time) in [(6, at - 100), (4, at - 1)] {
        c.publish_at(
            ID,
            request(family, 1000, Event::Started),
            Credit::default(),
            None,
            time,
            false,
        )
        .unwrap();
    }
    let leecher = Identity {
        user_id: 12002,
        ..ID
    };
    for family in [4, 6] {
        let Operation::Announce(mut announce) = request(family, 1000, Event::Started) else {
            unreachable!()
        };
        announce.port = 6882;
        announce.left = 100;
        c.publish_at(
            leecher,
            Operation::Announce(announce),
            Credit::default(),
            None,
            at - 1,
            false,
        )
        .unwrap();
    }
    c.publish_at(
        Identity {
            torrent_id: 12002,
            ..ID
        },
        request(4, 1000, Event::Started),
        Credit::default(),
        None,
        at - 1,
        false,
    )
    .unwrap();
    let request = ListRequest {
        torrent_id: 12001,
        user_id: 12006,
        numwant: 1,
        seeds: true,
        leeches: true,
    };
    let counts = SwarmCounts {
        seeders: 1,
        leechers: 1,
        seeders_ipv4: 1,
        seeders_ipv6: 1,
        leechers_ipv4: 1,
        leechers_ipv6: 1,
    };
    let questions = |pool: MySqlPool| async move {
        sqlx::query("SHOW GLOBAL STATUS LIKE 'Questions'")
            .fetch_one(&pool)
            .await
            .unwrap()
            .get::<String, _>(1)
            .parse::<u64>()
            .unwrap()
    };
    let before = questions(pool.clone()).await;
    let list = c.select_at(request, at).unwrap();
    assert_eq!(list.counts, counts);
    assert_eq!(list.logical_peers, 1);
    assert_eq!(list.ipv4.len(), 6);
    assert_eq!(list.ipv6.len(), 18);
    assert_eq!(&list.ipv4[4..], 6881_u16.to_be_bytes());
    assert_eq!(&list.ipv6[16..], 6881_u16.to_be_bytes());
    let mut expected=b"d8:completei1e10:downloadedi0e10:incompletei1e8:intervali1800e12:min intervali1530e5:peers6:".to_vec();
    expected.extend([192, 0, 2, 30]);
    expected.extend(6881_u16.to_be_bytes());
    expected.extend(b"6:peers618:");
    expected.extend(
        "2001:db8::30"
            .parse::<std::net::Ipv6Addr>()
            .unwrap()
            .octets(),
    );
    expected.extend(6881_u16.to_be_bytes());
    expected.extend("15:warning message8:conexãoe".as_bytes());
    assert_eq!(list.encode(0, 1800, 1530, Some("conexão")), expected);
    for wanted in [0, 1, 2, usize::MAX] {
        let list = c
            .select_at(
                ListRequest {
                    numwant: wanted,
                    ..request
                },
                at,
            )
            .unwrap();
        assert_eq!(list.counts, counts);
        assert_eq!(list.logical_peers, wanted.min(2));
        assert_eq!(list.ipv4.len() + list.ipv6.len(), 24 * list.logical_peers);
    }
    let own = c
        .select_at(
            ListRequest {
                user_id: 12001,
                ..request
            },
            at,
        )
        .unwrap();
    assert_eq!(own.counts, counts);
    assert_eq!(own.logical_peers, 1);
    assert_eq!(&own.ipv4[4..], 6882_u16.to_be_bytes());
    let blocked = c
        .select_at(
            ListRequest {
                seeds: false,
                leeches: false,
                ..request
            },
            at,
        )
        .unwrap();
    assert_eq!(blocked.counts, counts);
    assert_eq!(blocked.logical_peers, 0);
    assert_eq!(
        c.select_at(
            ListRequest {
                torrent_id: 987654,
                ..request
            },
            at
        )
        .unwrap()
        .counts,
        SwarmCounts::default()
    );
    assert_eq!(
        questions(pool.clone()).await - before,
        1,
        "Selecao e codificacao nao consultam MySQL"
    );

    c.shutdown().await.unwrap();
    assert!(matches!(c.select(request), Err(Error::Unavailable)));
    let c = Coordinator::open(pool.clone(), settings).await.unwrap();
    assert_eq!(c.select_at(request, at).unwrap().counts, counts);
    // Folga para o bootstrap real; a expiracao usa apenas o relogio de ensaio.
    let expiry = at + 7101;
    let expired = c.select_at(request, expiry).unwrap();
    assert_eq!(
        expired.counts,
        SwarmCounts {
            seeders_ipv6: 0,
            ..counts
        }
    );
    assert_eq!(expired.ipv4.len(), 6);
    assert!(expired.ipv6.is_empty());
    assert_eq!(
        c.peer(ID).unwrap().endpoints.len(),
        2,
        "Filtro temporal nao depende de limpeza fisica"
    );
    let stop = super::request(4, 1000, Event::Stopped);
    c.publish_at(ID, stop, Credit::default(), None, expiry + 1, false)
        .unwrap();
    assert_eq!(
        c.select_at(request, expiry + 1).unwrap().counts,
        SwarmCounts {
            seeders: 0,
            seeders_ipv4: 0,
            seeders_ipv6: 0,
            ..counts
        }
    );
    c.shutdown().await.unwrap();

    let c = Coordinator::open(
        pool.clone(),
        Settings {
            require_connectivity: true,
            ..settings
        },
    )
    .await
    .unwrap();
    assert_eq!(
        c.select_at(request, expiry + 1).unwrap().counts,
        SwarmCounts::default()
    );
    let peer = c.peer(leecher).unwrap();
    for (family, connectable) in [(Family::V4, true), (Family::V6, false)] {
        let endpoint = peer.endpoints.get(family).unwrap();
        c.publish_at(
            leecher,
            Operation::Probe {
                ip: endpoint.ip,
                port: endpoint.port,
                revision: endpoint.revision,
                connectable,
            },
            Credit::default(),
            None,
            expiry + 1,
            false,
        )
        .unwrap();
    }
    let list = c.select_at(request, expiry + 1).unwrap();
    assert_eq!(
        list.counts,
        SwarmCounts {
            leechers: 1,
            leechers_ipv4: 1,
            ..SwarmCounts::default()
        }
    );
    assert_eq!(list.logical_peers, 1);
    assert_eq!(list.ipv4.len(), 6);
    assert!(list.ipv6.is_empty());
    c.shutdown().await.unwrap();

    // Mais candidatos que vagas: priorizar seeders, preencher com leechers e
    // manter os dois endpoints do mesmo peer, sem duplicar a amostra.
    reset(pool).await;
    let c = Coordinator::open(pool.clone(), settings).await.unwrap();
    let at = c.now();
    for offset in 0..5 {
        for family in [4, 6] {
            let Operation::Announce(mut announce) = super::request(family, 1000, Event::Started)
            else {
                unreachable!()
            };
            announce.port = 6881 + offset as u16;
            announce.left = if offset < 2 { 0 } else { 100 };
            c.publish_at(
                Identity {
                    user_id: 12001 + offset,
                    ..ID
                },
                Operation::Announce(announce),
                Credit::default(),
                None,
                at,
                false,
            )
            .unwrap();
        }
    }
    for _ in 0..64 {
        let list = c
            .select_at(
                ListRequest {
                    numwant: 3,
                    ..request
                },
                at,
            )
            .unwrap();
        assert_eq!(list.counts.seeders, 2);
        assert_eq!(list.counts.leechers, 3);
        assert_eq!(list.logical_peers, 3);
        let ports4: std::collections::BTreeSet<_> = list
            .ipv4
            .chunks_exact(6)
            .map(|e| u16::from_be_bytes([e[4], e[5]]))
            .collect();
        let ports6: std::collections::BTreeSet<_> = list
            .ipv6
            .chunks_exact(18)
            .map(|e| u16::from_be_bytes([e[16], e[17]]))
            .collect();
        assert_eq!(ports4.len(), 3);
        assert_eq!(ports4, ports6);
        assert!(ports4.contains(&6881) && ports4.contains(&6882));
        assert_eq!(ports4.range(6883..=6885).count(), 1);
    }
    let own = c
        .select_at(
            ListRequest {
                user_id: 12001,
                numwant: 10,
                ..request
            },
            at,
        )
        .unwrap();
    assert_eq!(own.logical_peers, 4);
    assert!(
        !own.ipv4
            .chunks_exact(6)
            .any(|e| e[4..] == 6881_u16.to_be_bytes())
    );
    c.shutdown().await.unwrap();
    println!(
        "PASS selecao por torrent, uniao de peers, numwant 0/1/2, ambos endpoints, payload, bencode, TTL, conectividade e restart sem SQL na leitura"
    );
}
