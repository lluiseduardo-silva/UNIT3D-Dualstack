use std::{env, fs, net::IpAddr};

use serde_json::{Value, json};
use unit3d_announce::dualstack::peer::{
    Announce, Event, Family, Operation, Peer, Policy, TransitionError, apply, credit_percent,
    observed_address,
};

fn request(value: &Value) -> Operation {
    let address = || value["ip"].as_str().unwrap().parse::<IpAddr>().unwrap();
    let port = || u16::try_from(value["port"].as_u64().unwrap()).unwrap();
    match value["kind"].as_str().unwrap_or("announce") {
        "expire" => Operation::Expire,
        "probe" => Operation::Probe {
            ip: address(),
            port: port(),
            revision: value["revision"].as_u64().unwrap(),
            connectable: value["connectable"].as_bool().unwrap(),
        },
        "announce" => Operation::Announce(Announce {
            event: match value["event"].as_str().unwrap() {
                "" => Event::Empty,
                "started" => Event::Started,
                "completed" => Event::Completed,
                "stopped" => Event::Stopped,
                "paused" => Event::Paused,
                other => panic!("Evento desconhecido na fixture: {other}"),
            },
            ip: address(),
            port: port(),
            uploaded: value["uploaded"].as_str().unwrap().parse().unwrap(),
            downloaded: value["downloaded"].as_str().unwrap().parse().unwrap(),
            left: value["left"].as_str().unwrap().parse().unwrap(),
            visible: value["visible"].as_bool().unwrap(),
            agent: value["agent"].as_str().unwrap().to_owned(),
        }),
        other => panic!("Operacao desconhecida na fixture: {other}"),
    }
}

#[test]
#[ignore = "Exige DUALSTACK_PEER_FIXTURES apontando para o contrato compartilhado peer-v1.json"]
fn shared_peer_contract() {
    let path = env::var("DUALSTACK_PEER_FIXTURES").expect("Defina DUALSTACK_PEER_FIXTURES");
    let contract: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    assert_eq!(contract["version"], 1);
    let mut trace = Vec::new();
    let cases = contract["cases"].as_array().unwrap();
    for case in cases {
        let mut config = contract["defaults"].as_object().unwrap().clone();
        if let Some(overrides) = case["config"].as_object() {
            config.extend(overrides.clone());
        }
        let policy = Policy {
            endpoint_ttl: config["endpoint_ttl"].as_u64().unwrap(),
            max_endpoints: u8::try_from(config["max_endpoints"].as_u64().unwrap()).unwrap(),
            min_interval: config["min_interval"].as_u64().unwrap(),
            allow_private_addresses: config
                .get("allow_private_addresses")
                .and_then(Value::as_bool)
                .unwrap_or(false),
        };
        let mut state: Option<Peer> = None;
        for (index, operation) in case["operations"].as_array().unwrap().iter().enumerate() {
            let mut merged = contract["request_defaults"].as_object().unwrap().clone();
            merged.extend(operation.as_object().unwrap().clone());
            let at = operation["at"].as_u64().unwrap();
            let result =
                apply(state.as_ref(), &request(&Value::Object(merged)), at, policy).unwrap();
            let transition = serde_json::to_value(&result).unwrap();
            state = result.peer;
            let mut observed = state
                .as_ref()
                .map(|p| {
                    serde_json::to_value(p)
                        .unwrap()
                        .as_object()
                        .unwrap()
                        .clone()
                })
                .unwrap_or_default();
            observed.extend(transition.as_object().unwrap().clone());
            let families: Vec<_> = state
                .as_ref()
                .map(|p| p.endpoints.iter().map(|e| e.family.number()).collect())
                .unwrap_or_default();
            observed.insert("families".into(), json!(families));
            observed.insert("exists".into(), json!(state.is_some()));
            for family in [Family::V4, Family::V6] {
                let endpoint = state.as_ref().and_then(|p| p.endpoints.get(family));
                observed.insert(
                    format!("ipv{}", family.number()),
                    json!(endpoint.map(|e| e.ip.to_string())),
                );
                observed.insert(
                    format!("revision{}", family.number()),
                    json!(endpoint.map(|e| e.revision)),
                );
                observed.insert(
                    format!("connectable{}", family.number()),
                    json!(endpoint.and_then(|e| e.connectable)),
                );
            }
            let mut expected = json!({"outcome": "accepted"}).as_object().unwrap().clone();
            if let Some(fields) = operation["expect"].as_object() {
                expected.extend(fields.clone());
            }
            for (field, value) in expected {
                assert_eq!(
                    observed.get(&field),
                    Some(&value),
                    "{} operacao {index}: {field}",
                    case["name"]
                );
            }
            assert!(families.len() <= usize::from(policy.max_endpoints));
            let counts = |required, now| {
                state
                    .as_ref()
                    .map(|p| p.counts(required, now, policy.endpoint_ttl))
                    .unwrap_or_default()
            };
            trace.push(json!({
                "case": case["name"], "operation": index, "transition": transition,
                "counts": counts(false, None), "connectable_counts": counts(true, None),
                "current_counts": counts(false, Some(at)), "current_connectable_counts": counts(true, Some(at)),
            }));
        }
    }
    println!(
        "Contrato Rust: {} casos, {} operacoes verificadas",
        cases.len(),
        trace.len()
    );
    if let Ok(output) = env::var("DUALSTACK_CONTRACT_TRACE") {
        fs::write(
            output,
            serde_json::to_vec_pretty(&json!({"version": 1, "steps": trace})).unwrap(),
        )
        .unwrap();
    }
}

#[test]
fn exact_financial_factors_and_overflow() {
    assert_eq!(
        credit_percent(9_007_199_254_740_993, 200),
        Ok(18_014_398_509_481_986)
    );
    assert_eq!(credit_percent(101, 75), Ok(75));
    // A configuracao original aceita fatores u8, inclusive acima de 200.
    assert_eq!(credit_percent(100, 255), Ok(255));
    assert_eq!(credit_percent(u64::MAX, 0), Ok(0));
    assert_eq!(credit_percent(u64::MAX, 100), Ok(u64::MAX));
    assert_eq!(
        credit_percent(u64::MAX, 200),
        Err(TransitionError::Overflow)
    );
    assert_eq!(
        credit_percent(1, 256),
        Err(TransitionError::InvalidCreditFactor)
    );
}

#[test]
fn addresses_respect_origin_policy_including_mapped_ipv4() {
    for address in [
        "0.0.0.0",
        "127.0.0.1",
        "224.0.0.1",
        "255.255.255.255",
        "169.254.1.2",
        "::",
        "::1",
        "ff02::1",
        "fe80::1",
        "::ffff:127.0.0.1",
    ] {
        for allow_private in [false, true] {
            assert_eq!(
                observed_address(address.parse().unwrap(), allow_private),
                Err(TransitionError::InvalidAddress),
                "{address}"
            );
        }
    }
    for address in [
        "10.0.0.1",
        "172.29.92.30",
        "192.168.1.2",
        "100.64.1.2",
        "fd42:756e:6974:92::30",
        "::ffff:10.0.0.1",
    ] {
        assert_eq!(
            observed_address(address.parse().unwrap(), false),
            Err(TransitionError::InvalidAddress),
            "{address}"
        );
        assert!(
            observed_address(address.parse().unwrap(), true).is_ok(),
            "{address}"
        );
    }
    assert_eq!(
        observed_address("::ffff:192.0.2.1".parse().unwrap(), false),
        Ok("192.0.2.1".parse().unwrap())
    );
}

fn sample(ip: &str, upload: u64) -> Operation {
    Operation::Announce(Announce {
        event: Event::Completed,
        ip: ip.parse().unwrap(),
        port: 6881,
        uploaded: upload,
        downloaded: 0,
        left: 0,
        visible: true,
        agent: "fixture".into(),
    })
}

#[test]
fn rotating_addresses_remains_bounded_and_preserves_uint64() {
    let policy = Policy {
        min_interval: 0,
        ..Policy::default()
    };
    let mut peer = apply(None, &sample("192.0.2.1", u64::MAX - 1), 1000, policy)
        .unwrap()
        .peer;
    let mut total_credit = 0;
    for index in 1..=10_000 {
        let operation = sample(&format!("2001:db8::{index:x}"), u64::MAX);
        let transition = apply(peer.as_ref(), &operation, 1000 + index, policy).unwrap();
        total_credit += transition.upload_delta;
        peer = transition.peer;
        // Atualiza IPv4 de tempos em tempos para preservar os dois caminhos vivos.
        if index % 1000 == 0 {
            peer = apply(
                peer.as_ref(),
                &sample("192.0.2.1", u64::MAX),
                1000 + index,
                policy,
            )
            .unwrap()
            .peer;
        }
        assert_eq!(peer.as_ref().unwrap().endpoints.len(), 2);
    }
    assert_eq!(total_credit, 1);
    let peer = peer.unwrap();
    assert_eq!(peer.uploaded, u64::MAX);
    assert_eq!(peer.counts(false, Some(11_000), 7200).seeders, 1);
    assert_eq!(peer.counts(false, Some(11_000), 7200).seeders_ipv4, 1);
    assert_eq!(peer.counts(false, Some(11_000), 7200).seeders_ipv6, 1);
    assert_eq!(peer.counts(true, Some(11_000), 7200).seeders, 0);
}

#[test]
fn rejected_input_leaves_the_reference_untouched() {
    let policy = Policy::default();
    let peer = apply(None, &sample("192.0.2.1", 1000), 1000, policy)
        .unwrap()
        .peer
        .unwrap();
    let original = peer.clone();
    assert_eq!(
        apply(Some(&peer), &sample("::1", 2000), 1001, policy),
        Err(TransitionError::InvalidAddress)
    );
    assert_eq!(
        apply(
            Some(&peer),
            &Operation::Expire,
            1001,
            Policy {
                endpoint_ttl: 0,
                ..policy
            }
        ),
        Err(TransitionError::InvalidPolicy)
    );
    assert_eq!(peer, original);
}
