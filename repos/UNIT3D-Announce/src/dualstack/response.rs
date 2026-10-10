//! Selecao limitada a peers do torrent; contadores independem da lista enviada.
use std::{net::IpAddr, time::Instant};

use rand::{Rng, rng, seq::IndexedRandom};
use serde::Serialize;

use super::{
    coordinator::{Coordinator, Error},
    peer::{Counts, Endpoint},
};

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct SwarmCounts {
    pub seeders: u64,
    pub leechers: u64,
    pub seeders_ipv4: u64,
    pub seeders_ipv6: u64,
    pub leechers_ipv4: u64,
    pub leechers_ipv6: u64,
}

impl SwarmCounts {
    pub(crate) fn add(&mut self, c: Counts) {
        self.seeders += u64::from(c.seeders);
        self.leechers += u64::from(c.leechers);
        self.seeders_ipv4 += u64::from(c.seeders_ipv4);
        self.seeders_ipv6 += u64::from(c.seeders_ipv6);
        self.leechers_ipv4 += u64::from(c.leechers_ipv4);
        self.leechers_ipv6 += u64::from(c.leechers_ipv6);
    }
}

#[derive(Clone, Copy, Debug)]
pub struct ListRequest {
    pub torrent_id: u32,
    pub user_id: u32,
    /// Ja limitado pela configuracao do handler.
    pub numwant: usize,
    pub seeds: bool,
    pub leeches: bool,
}

#[derive(Debug, Default)]
pub struct PeerList {
    pub completed: u64,
    pub counts: SwarmCounts,
    pub logical_peers: usize,
    pub ipv4: Vec<u8>,
    pub ipv6: Vec<u8>,
}

impl PeerList {
    fn push(&mut self, e: &Endpoint) {
        let target = match e.ip {
            IpAddr::V4(ip) => {
                self.ipv4.extend(ip.octets());
                &mut self.ipv4
            }
            IpAddr::V6(ip) => {
                self.ipv6.extend(ip.octets());
                &mut self.ipv6
            }
        };
        target.extend(e.port.to_be_bytes());
    }

    /// Campos ordenados, tamanhos em bytes e ambos os caminhos de cada peer.
    pub fn encode(
        &self,
        completed: u64,
        interval: u32,
        min_interval: u32,
        warning: Option<&str>,
    ) -> Vec<u8> {
        let mut result = Vec::with_capacity(
            160 + self.ipv4.len() + self.ipv6.len() + warning.map_or(0, str::len),
        );
        result.extend(format!("d8:completei{}e10:downloadedi{completed}e10:incompletei{}e8:intervali{interval}e12:min intervali{min_interval}e5:peers{}:",self.counts.seeders,self.counts.leechers,self.ipv4.len()).as_bytes());
        result.extend(&self.ipv4);
        result.extend(format!("6:peers6{}:", self.ipv6.len()).as_bytes());
        result.extend(&self.ipv6);
        if let Some(warning) = warning {
            result.extend(format!("15:warning message{}:", warning.len()).as_bytes());
            result.extend(warning.as_bytes());
        }
        result.push(b'e');
        result
    }
}

impl Coordinator {
    /// Sem I/O. O indice evita percorrer peers de torrents alheios.
    pub fn select(&self, request: ListRequest) -> Result<PeerList, Error> {
        self.select_at(request, self.now())
    }

    #[doc(hidden)]
    pub fn select_at(&self, request: ListRequest, at: u64) -> Result<PeerList, Error> {
        let state = self.state.lock();
        if !state.ready || Instant::now() >= state.deadline {
            return Err(Error::Unavailable);
        }
        let mut result = PeerList::default();
        result.completed = state
            .completed
            .get(&request.torrent_id)
            .copied()
            .unwrap_or(0);
        let Some(peers) = state.peers.torrent(request.torrent_id) else {
            return Ok(result);
        };
        let eligible = |e: &&Endpoint| {
            e.is_current(at, self.settings.peer.endpoint_ttl)
                && (!self.settings.require_connectivity || e.connectable == Some(true))
        };
        if state.deleted_torrents.contains(&request.torrent_id) {
            return Ok(result);
        }
        let limit = request.numwant.min(peers.len());
        let mut seeds = Vec::new();
        let mut leeches = Vec::new();
        let mut seeds_seen = 0;
        let mut leeches_seen = 0;
        let mut random = rng();
        // Contagem e amostragem compartilham uma leitura de cada peer. Reservas
        // de no maximo numwant por tipo mantem a memoria temporaria limitada.
        for (id, peer) in peers {
            if state.deleted_users.contains(&id.user_id) {
                continue;
            }
            let counts = peer.counts(
                self.settings.require_connectivity,
                Some(at),
                self.settings.peer.endpoint_ttl,
            );
            result.counts.add(counts);
            if limit == 0
                || id.user_id == request.user_id
                || counts.seeders + counts.leechers == 0
                || (peer.seeder && !request.seeds)
                || (!peer.seeder && !request.leeches)
            {
                continue;
            }
            let (sample, seen) = if peer.seeder {
                (&mut seeds, &mut seeds_seen)
            } else {
                (&mut leeches, &mut leeches_seen)
            };
            *seen += 1;
            if sample.len() < limit {
                sample.push(peer);
            } else {
                let index = random.random_range(0..*seen);
                if index < limit {
                    sample[index] = peer;
                }
            }
        }
        let mut selected = seeds;
        // Reamostrar preserva a distribuicao uniforme quando seeders ocupam
        // parte das vagas; truncar o reservatorio poderia enviesar o resultado.
        selected.extend(
            leeches
                .choose_multiple(&mut random, limit - selected.len())
                .copied(),
        );
        result.logical_peers = selected.len();
        for peer in selected {
            for endpoint in peer.endpoints.iter().filter(eligible) {
                result.push(endpoint);
            }
        }
        Ok(result)
    }
}
