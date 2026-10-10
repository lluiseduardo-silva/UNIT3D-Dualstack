//! Estado unico por peer, contiguo por torrent; chaves ordenadas para manutencao.
use std::{
    collections::{BTreeMap, BTreeSet},
    ops::RangeBounds,
};

use indexmap::IndexMap;

use super::{coordinator::Identity, peer::Peer};

#[derive(Default)]
pub(crate) struct PeerIndex {
    torrents: BTreeMap<u32, IndexMap<Identity, Peer>>,
    identities: BTreeSet<Identity>,
}

impl PeerIndex {
    pub fn get(&self, id: &Identity) -> Option<&Peer> {
        self.torrents.get(&id.torrent_id)?.get(id)
    }

    /// Usado no bootstrap, antes de abrir o processamento de announces.
    pub fn get_mut(&mut self, id: &Identity) -> Option<&mut Peer> {
        self.torrents.get_mut(&id.torrent_id)?.get_mut(id)
    }

    pub fn insert(&mut self, id: Identity, peer: Peer) -> Option<Peer> {
        let previous = self
            .torrents
            .entry(id.torrent_id)
            .or_default()
            .insert(id, peer);
        if previous.is_none() {
            self.identities.insert(id);
        }
        previous
    }

    pub fn remove(&mut self, id: &Identity) -> Option<Peer> {
        let torrent = self.torrents.get_mut(&id.torrent_id)?;
        let removed = torrent.swap_remove(id)?;
        self.identities.remove(id);
        if torrent.is_empty() {
            self.torrents.remove(&id.torrent_id);
        }
        Some(removed)
    }

    pub fn torrent(&self, id: u32) -> Option<&IndexMap<Identity, Peer>> {
        self.torrents.get(&id)
    }

    /// Mantem a ordem user/torrent/peer usada pelos lotes de manutencao.
    pub fn iter(&self) -> impl Iterator<Item = (&Identity, &Peer)> {
        self.identities
            .iter()
            .map(|id| (id, self.get(id).expect("indice de peer inconsistente")))
    }

    pub fn range(
        &self,
        range: impl RangeBounds<Identity>,
    ) -> impl Iterator<Item = (&Identity, &Peer)> {
        self.identities
            .range(range)
            .map(|id| (id, self.get(id).expect("indice de peer inconsistente")))
    }

    pub fn values(&self) -> impl Iterator<Item = &Peer> {
        self.torrents.values().flat_map(|torrent| torrent.values())
    }

    pub fn iter_mut(&mut self) -> impl Iterator<Item = (&Identity, &mut Peer)> {
        self.torrents
            .values_mut()
            .flat_map(|torrent| torrent.iter_mut())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dualstack::peer::{self, Announce, Event, Operation, Policy};

    fn peer(uploaded: u64) -> Peer {
        peer::apply(
            None,
            &Operation::Announce(Announce {
                event: Event::Started,
                ip: "192.0.2.1".parse().unwrap(),
                port: 6881,
                uploaded,
                downloaded: 0,
                left: 0,
                visible: true,
                agent: "index-test".into(),
            }),
            1000,
            Policy::default(),
        )
        .unwrap()
        .peer
        .unwrap()
    }

    #[test]
    fn updates_removals_and_bootstrap_mutations_preserve_all_views() {
        let mut index = PeerIndex::default();
        let mut expected = BTreeMap::new();
        // Mesmo peer_id em varios usuarios e torrents; ordem de chegada diferente
        // da ordem de manutencao e remocoes que movimentam o ultimo slot do torrent.
        for step in 0..4000_u64 {
            let id = Identity {
                user_id: (step % 11) as u32,
                torrent_id: ((step * 7) % 13) as u32,
                peer_id: [42; 20],
            };
            if step % 5 == 0 {
                assert_eq!(index.remove(&id), expected.remove(&id));
            } else {
                let peer = peer(step);
                assert_eq!(index.insert(id, peer.clone()), expected.insert(id, peer));
            }
            if step % 71 == 0 {
                assert!(index.iter().eq(expected.iter()));
                for torrent_id in 0..13 {
                    let actual: BTreeMap<_, _> = index
                        .torrent(torrent_id)
                        .into_iter()
                        .flat_map(|torrent| torrent.iter())
                        .collect();
                    let wanted: BTreeMap<_, _> = expected
                        .iter()
                        .filter(|(id, _)| id.torrent_id == torrent_id)
                        .collect();
                    assert_eq!(actual, wanted);
                }
            }
        }
        for (id, peer) in index.iter_mut() {
            peer.uploaded += 1;
            expected.get_mut(id).unwrap().uploaded += 1;
        }
        for user_id in 0..11 {
            let first = Identity {
                user_id,
                torrent_id: 0,
                peer_id: [0; 20],
            };
            let last = Identity {
                user_id,
                torrent_id: u32::MAX,
                peer_id: [255; 20],
            };
            assert!(index.range(first..=last).eq(expected.range(first..=last)));
        }
        for id in expected.keys() {
            assert_eq!(index.get_mut(id).unwrap(), expected.get(id).unwrap());
            index.remove(id).unwrap();
        }
        assert!(index.torrents.is_empty());
        assert!(index.identities.is_empty());
        assert_eq!(index.values().count(), 0);
    }

    #[test]
    fn repeated_replacement_keeps_one_state_and_one_identity() {
        let id = Identity {
            user_id: 1,
            torrent_id: 1,
            peer_id: [1; 20],
        };
        let mut index = PeerIndex::default();
        for uploaded in 0..10_000 {
            index.insert(id, peer(uploaded));
        }
        assert_eq!(index.get(&id).unwrap().uploaded, 9999);
        assert_eq!(index.identities.len(), 1);
        assert_eq!(index.torrents.len(), 1);
        assert_eq!(index.torrent(1).unwrap().len(), 1);
    }
}
