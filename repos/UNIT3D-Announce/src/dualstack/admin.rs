//! Contrato administrativo aditivo; nenhum dado de autenticacao e exportado aqui.
use std::{collections::BTreeMap, net::IpAddr};

use serde::Serialize;

use super::{
    coordinator::{Coordinator, Identity},
    peer::Peer,
    response::SwarmCounts,
};

#[derive(Serialize)]
pub struct Capabilities {
    pub coordinated_deletion: bool,
    pub dualstack: bool,
    pub peer_schema: u8,
    pub peer_count: &'static str,
    pub max_endpoints: u8,
}

impl Capabilities {
    pub fn legacy() -> Self {
        Self {
            coordinated_deletion: false,
            dualstack: false,
            peer_schema: 0,
            peer_count: "unique",
            max_endpoints: 1,
        }
    }
}

#[derive(Serialize)]
pub struct Endpoint {
    family: u8,
    ip_address: IpAddr,
    port: u16,
    connectable: Option<bool>,
    last_announced_at: u64,
    connectivity_checked_at: Option<u64>,
    revision: u64,
}

#[derive(Serialize)]
pub struct LogicalPeer {
    pub endpoints: Vec<Endpoint>,
    // Projecao de compatibilidade; consumidores schema 1 leem endpoints.
    ip_address: Option<IpAddr>,
    port: u16,
    agent: String,
    uploaded: String,
    downloaded: String,
    left: String,
    is_seeder: bool,
    is_active: bool,
    is_visible: bool,
    connectable: bool,
    created_at: u64,
    updated_at: u64,
    state_version: u64,
    session_generation: u64,
}

impl LogicalPeer {
    fn from_peer(p: &Peer, now: u64, ttl: u64) -> Self {
        let endpoints: Vec<_> = p
            .endpoints
            .iter()
            .filter(|e| e.is_current(now, ttl))
            .map(|e| Endpoint {
                family: e.family.number(),
                ip_address: e.ip,
                port: e.port,
                connectable: e.connectable,
                last_announced_at: e.last_announced_at,
                connectivity_checked_at: e.connectivity_checked_at,
                revision: e.revision,
            })
            .collect();
        let connectable = endpoints.iter().any(|e| e.connectable == Some(true));
        let projection = endpoints
            .iter()
            .find(|e| e.connectable == Some(true))
            .or_else(|| endpoints.first());
        let (ip_address, port) = projection
            .map(|e| (Some(e.ip_address), e.port))
            .unwrap_or((None, 0));
        Self {
            is_active: !endpoints.is_empty(),
            ip_address,
            port,
            endpoints,
            connectable,
            agent: p.agent.clone(),
            uploaded: p.uploaded.to_string(),
            downloaded: p.downloaded.to_string(),
            left: p.left.to_string(),
            is_seeder: p.seeder,
            is_visible: p.visible,
            created_at: p.created_at,
            updated_at: p.updated_at,
            state_version: p.state_version,
            session_generation: p.session_generation,
        }
    }
}

#[derive(Serialize)]
pub struct TorrentSnapshot {
    pub capabilities: Capabilities,
    #[serde(flatten)]
    pub counts: SwarmCounts,
    pub times_completed: u64,
    pub peers: BTreeMap<String, LogicalPeer>,
}

impl Coordinator {
    pub fn capabilities(&self) -> Capabilities {
        Capabilities {
            coordinated_deletion: true,
            dualstack: true,
            peer_schema: 1,
            peer_count: "unique",
            max_endpoints: self.settings.peer.max_endpoints,
        }
    }

    /// Atualizacoes administrativas de metadados nao baixam totais em memoria.
    pub fn register_torrent(&self, id: u32, completed: u64) {
        self.state.lock().completed.entry(id).or_insert(completed);
    }

    pub fn torrent_snapshot(&self, torrent_id: u32) -> TorrentSnapshot {
        let now = self.now();
        let state = self.state.lock();
        let mut result = TorrentSnapshot {
            capabilities: self.capabilities(),
            counts: SwarmCounts::default(),
            times_completed: state.completed.get(&torrent_id).copied().unwrap_or(0),
            peers: BTreeMap::new(),
        };
        if let Some(peers) = state.peers.torrent(torrent_id) {
            for (id, p) in peers {
                if state.deleted_users.contains(&id.user_id) || state.deleted_torrents.contains(&id.torrent_id) {continue;}
                result.counts.add(p.counts(
                    self.settings.require_connectivity,
                    Some(now),
                    self.settings.peer.endpoint_ttl,
                ));
                let hex: String = id
                    .peer_id
                    .iter()
                    .map(|byte| format!("{byte:02x}"))
                    .collect();
                result.peers.insert(
                    format!("{}-{hex}", id.user_id),
                    LogicalPeer::from_peer(p, now, self.settings.peer.endpoint_ttl),
                );
            }
        }
        result
    }

    pub fn user_counts(&self, user_id: u32) -> SwarmCounts {
        let now = self.now();
        let state = self.state.lock();
        let mut counts = SwarmCounts::default();
        let first = Identity {
            user_id,
            torrent_id: 0,
            peer_id: [0; 20],
        };
        let last = Identity {
            user_id,
            torrent_id: u32::MAX,
            peer_id: [u8::MAX; 20],
        };
        for (id, peer) in state.peers.range(first..=last) {
            if state.deleted_users.contains(&id.user_id) || state.deleted_torrents.contains(&id.torrent_id) {continue;}
            counts.add(peer.counts(
                self.settings.require_connectivity,
                Some(now),
                self.settings.peer.endpoint_ttl,
            ));
        }
        counts
    }
}
