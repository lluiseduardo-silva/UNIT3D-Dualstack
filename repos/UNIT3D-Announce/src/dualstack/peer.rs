//! Uma identidade logica e ate um endpoint por familia. Nenhuma operacao faz I/O.
use std::net::IpAddr;

use serde::{Serialize, Serializer, ser::SerializeMap};
use thiserror::Error;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Family {
    V4,
    V6,
}

impl Family {
    pub fn number(self) -> u8 {
        match self {
            Self::V4 => 4,
            Self::V6 => 6,
        }
    }

    pub(crate) fn index(self) -> usize {
        match self {
            Self::V4 => 0,
            Self::V6 => 1,
        }
    }

    pub fn of(ip: IpAddr) -> Self {
        match ip {
            IpAddr::V4(_) => Self::V4,
            IpAddr::V6(_) => Self::V6,
        }
    }
}

impl Serialize for Family {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_u8(self.number())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Event {
    Empty,
    Started,
    Completed,
    Stopped,
    Paused,
}

#[derive(Clone, Debug)]
pub struct Announce {
    pub event: Event,
    pub ip: IpAddr,
    pub port: u16,
    pub uploaded: u64,
    pub downloaded: u64,
    pub left: u64,
    pub visible: bool,
    pub agent: String,
}

#[derive(Clone, Debug)]
pub enum Operation {
    Announce(Announce),
    Expire,
    Probe {
        ip: IpAddr,
        port: u16,
        revision: u64,
        connectable: bool,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Policy {
    pub endpoint_ttl: u64,
    pub max_endpoints: u8,
    pub min_interval: u64,
    pub allow_private_addresses: bool,
}

impl Default for Policy {
    fn default() -> Self {
        Self {
            endpoint_ttl: 7200,
            max_endpoints: 2,
            min_interval: 1530,
            allow_private_addresses: false,
        }
    }
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum TransitionError {
    #[error("Configuracao dualstack invalida")]
    InvalidPolicy,
    #[error("Endereco de origem nao publicavel")]
    InvalidAddress,
    #[error("Porta de announce invalida")]
    InvalidPort,
    #[error("Limite de versao ou contador excedido")]
    Overflow,
    #[error("Fator de credito invalido")]
    InvalidCreditFactor,
}

/// Normaliza somente IPv4 mapeado; nunca aceita IP alternativo fornecido pelo cliente.
pub fn observed_address(ip: IpAddr, allow_private: bool) -> Result<IpAddr, TransitionError> {
    let normalized = match ip {
        IpAddr::V6(v6) => v6.to_ipv4_mapped().map(IpAddr::V4).unwrap_or(ip),
        _ => ip,
    };
    let (invalid, private) = match normalized {
        IpAddr::V4(v4) => {
            let [first, second, _, _] = v4.octets();
            (
                first == 0 || first == 127 || first >= 224 || (first == 169 && second == 254),
                v4.is_private() || (first == 100 && (64..=127).contains(&second)),
            )
        }
        IpAddr::V6(v6) => (
            v6.is_unspecified()
                || v6.is_loopback()
                || v6.is_multicast()
                || v6.is_unicast_link_local(),
            v6.is_unique_local(),
        ),
    };
    if invalid || (private && !allow_private) {
        return Err(TransitionError::InvalidAddress);
    }
    Ok(normalized)
}

/// O intermediario largo evita overflow antes da divisao, sem ponto flutuante.
pub fn credit_percent(value: u64, percent: u16) -> Result<u64, TransitionError> {
    if percent > u16::from(u8::MAX) {
        return Err(TransitionError::InvalidCreditFactor);
    }
    u64::try_from(u128::from(value) * u128::from(percent) / 100)
        .map_err(|_| TransitionError::Overflow)
}

fn decimal<S: Serializer>(value: &u64, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_str(&value.to_string())
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct Endpoint {
    pub family: Family,
    pub ip: IpAddr,
    pub port: u16,
    pub connectable: Option<bool>,
    pub connectivity_checked_at: Option<u64>,
    pub revision: u64,
    pub created_at: u64,
    pub last_announced_at: u64,
}

impl Endpoint {
    pub fn is_current(&self, at: u64, ttl: u64) -> bool {
        // Equivalente a last + ttl > at, sem overflow de adicao.
        at < self.last_announced_at || at - self.last_announced_at < ttl
    }
}

/// Slots privados: cardinalidade fisicamente limitada, sem historico de IPs antigos.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct Endpoints([Option<Endpoint>; 2]);

impl Endpoints {
    pub fn get(&self, family: Family) -> Option<&Endpoint> {
        self.0[family.index()].as_ref()
    }

    pub fn iter(&self) -> impl Iterator<Item = &Endpoint> {
        self.0.iter().flatten()
    }

    pub fn len(&self) -> usize {
        self.iter().count()
    }

    pub fn is_empty(&self) -> bool {
        self.0.iter().all(Option::is_none)
    }

    pub(crate) fn put(&mut self, endpoint: Endpoint) {
        let index = endpoint.family.index();
        self.0[index] = Some(endpoint);
    }

    fn remove(&mut self, family: Family) {
        self.0[family.index()] = None;
    }

    fn expire(&mut self, at: u64, ttl: u64) {
        for endpoint in &mut self.0 {
            if endpoint.as_ref().is_some_and(|e| !e.is_current(at, ttl)) {
                *endpoint = None;
            }
        }
    }
}

impl Serialize for Endpoints {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut map = serializer.serialize_map(Some(self.len()))?;
        for endpoint in self.iter() {
            map.serialize_entry(&endpoint.family.number(), endpoint)?;
        }
        map.end()
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct LastAnnounces(pub(crate) [Option<u64>; 2]);

impl Serialize for LastAnnounces {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut map = serializer.serialize_map(None)?;
        for family in [Family::V4, Family::V6] {
            if let Some(at) = self.0[family.index()] {
                map.serialize_entry(&family.number(), &at)?;
            }
        }
        map.end()
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct Peer {
    #[serde(serialize_with = "decimal")]
    pub uploaded: u64,
    #[serde(serialize_with = "decimal")]
    pub downloaded: u64,
    #[serde(serialize_with = "decimal")]
    pub left: u64,
    pub agent: String,
    pub visible: bool,
    pub endpoints: Endpoints,
    pub last_announces: LastAnnounces,
    pub session_generation: u64,
    pub completion_reported: bool,
    pub created_at: u64,
    pub session_started_at: u64,
    pub legacy_endpoint: Option<Endpoint>,
    pub state_version: u64,
    pub updated_at: u64,
    pub active: bool,
    pub seeder: bool,
    pub connectable: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Outcome {
    Accepted,
    Ignored,
    Rejected,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Rejection {
    Interval,
    EndpointLimit,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct Transition {
    pub outcome: Outcome,
    pub reason: Option<Rejection>,
    pub peer: Option<Peer>,
    #[serde(serialize_with = "decimal")]
    pub upload_delta: u64,
    #[serde(serialize_with = "decimal")]
    pub download_delta: u64,
    pub completed_delta: u8,
}

impl Transition {
    fn unchanged(before: Option<&Peer>, reason: Option<Rejection>) -> Self {
        Self {
            outcome: if reason.is_some() {
                Outcome::Rejected
            } else {
                Outcome::Ignored
            },
            reason,
            peer: before.cloned(),
            upload_delta: 0,
            download_delta: 0,
            completed_delta: 0,
        }
    }

    fn accepted(
        mut peer: Peer,
        version: u64,
        at: u64,
        upload: u64,
        download: u64,
        completed: u8,
    ) -> Self {
        peer.state_version = version;
        peer.updated_at = at;
        peer.active = !peer.endpoints.is_empty();
        peer.seeder = peer.left == 0;
        peer.connectable = peer.endpoints.iter().any(|e| e.connectable == Some(true));
        if peer.active {
            peer.legacy_endpoint = peer
                .endpoints
                .iter()
                .find(|e| e.connectable == Some(true))
                .or_else(|| peer.endpoints.iter().next())
                .cloned();
        }
        Self {
            outcome: Outcome::Accepted,
            reason: None,
            peer: Some(peer),
            upload_delta: upload,
            download_delta: download,
            completed_delta: completed,
        }
    }
}

/// Calcula um candidato imutavel. O chamador deve confirmar estado e enfileiramento
/// na mesma secao de sincronizacao; esta funcao nunca publica efeitos por conta propria.
pub fn apply(
    before: Option<&Peer>,
    operation: &Operation,
    at: u64,
    policy: Policy,
) -> Result<Transition, TransitionError> {
    if policy.endpoint_ttl == 0 || !(1..=2).contains(&policy.max_endpoints) {
        return Err(TransitionError::InvalidPolicy);
    }
    let at = at.max(before.map_or(0, |peer| peer.updated_at));
    let version = before
        .map_or(0, |peer| peer.state_version)
        .checked_add(1)
        .ok_or(TransitionError::Overflow)?;
    let mut state = before.cloned();
    if let Some(peer) = &mut state {
        peer.endpoints.expire(at, policy.endpoint_ttl);
    }
    match operation {
        Operation::Expire => {
            let Some(peer) = state else {
                return Ok(Transition::unchanged(before, None));
            };
            if before.is_some_and(|old| old.endpoints == peer.endpoints) {
                return Ok(Transition::unchanged(before, None));
            }
            return Ok(Transition::accepted(peer, version, at, 0, 0, 0));
        }
        Operation::Probe {
            ip,
            port,
            revision,
            connectable,
        } => {
            let ip = observed_address(*ip, policy.allow_private_addresses)?;
            let family = Family::of(ip);
            let endpoint = state.as_ref().and_then(|p| p.endpoints.get(family));
            if !endpoint.is_some_and(|e| e.ip == ip && e.port == *port && e.revision == *revision) {
                return Ok(Transition::unchanged(before, None));
            }
            let mut endpoint = endpoint.unwrap().clone();
            endpoint.connectable = Some(*connectable);
            endpoint.connectivity_checked_at = Some(at);
            let mut peer = state.unwrap();
            peer.endpoints.put(endpoint);
            return Ok(Transition::accepted(peer, version, at, 0, 0, 0));
        }
        Operation::Announce(_) => {}
    }
    let Operation::Announce(request) = operation else {
        unreachable!()
    };
    let ip = observed_address(request.ip, policy.allow_private_addresses)?;
    let family = Family::of(ip);
    if request.port < 1024 && request.event != Event::Stopped {
        return Err(TransitionError::InvalidPort);
    }
    let endpoint = state
        .as_ref()
        .and_then(|p| p.endpoints.get(family))
        .cloned();
    if request.event == Event::Stopped && !endpoint.as_ref().is_some_and(|e| e.ip == ip) {
        return Ok(Transition::unchanged(before, None));
    }
    let new_session = state
        .as_ref()
        .is_none_or(|p| p.endpoints.is_empty() && request.event == Event::Started);
    if !new_session
        && !matches!(request.event, Event::Completed | Event::Stopped)
        && state
            .as_ref()
            .and_then(|p| p.last_announces.0[family.index()])
            .is_some_and(|last| at.saturating_sub(last) < policy.min_interval)
    {
        return Ok(Transition::unchanged(before, Some(Rejection::Interval)));
    }
    if endpoint.is_none()
        && request.event != Event::Stopped
        && state.as_ref().map_or(0, |p| p.endpoints.len()) >= usize::from(policy.max_endpoints)
    {
        return Ok(Transition::unchanged(
            before,
            Some(Rejection::EndpointLimit),
        ));
    }
    let upload = if new_session {
        0
    } else {
        request
            .uploaded
            .saturating_sub(state.as_ref().unwrap().uploaded)
    };
    let download = if new_session {
        0
    } else {
        request
            .downloaded
            .saturating_sub(state.as_ref().unwrap().downloaded)
    };
    let stale = !new_session
        && state.as_ref().is_some_and(|p| {
            request.downloaded < p.downloaded
                || (request.downloaded == p.downloaded && request.uploaded < p.uploaded)
        });
    let mut peer = if new_session {
        Peer {
            uploaded: request.uploaded,
            downloaded: request.downloaded,
            left: request.left,
            agent: request.agent.clone(),
            visible: request.visible,
            endpoints: Endpoints::default(),
            last_announces: LastAnnounces::default(),
            session_generation: before
                .map_or(0, |p| p.session_generation)
                .checked_add(1)
                .ok_or(TransitionError::Overflow)?,
            completion_reported: request.left == 0,
            created_at: before.map_or(at, |p| p.created_at),
            session_started_at: at,
            legacy_endpoint: before.and_then(|p| p.legacy_endpoint.clone()),
            state_version: 0,
            updated_at: 0,
            active: false,
            seeder: false,
            connectable: false,
        }
    } else {
        let mut peer = state.take().unwrap();
        peer.uploaded = peer.uploaded.max(request.uploaded);
        peer.downloaded = peer.downloaded.max(request.downloaded);
        if !stale {
            peer.left = request.left;
        }
        peer.agent = request.agent.clone();
        peer.visible = request.visible;
        peer
    };
    let completed = !new_session
        && !stale
        && request.event == Event::Completed
        && request.left == 0
        && !peer.completion_reported;
    peer.completion_reported |= completed;
    peer.last_announces.0[family.index()] = Some(at);
    if request.event == Event::Stopped {
        peer.endpoints.remove(family);
    } else {
        let mut endpoint = endpoint
            .filter(|e| e.ip == ip && e.port == request.port)
            .unwrap_or(Endpoint {
                family,
                ip,
                port: request.port,
                connectable: None,
                connectivity_checked_at: None,
                revision: version,
                created_at: at,
                last_announced_at: at,
            });
        endpoint.last_announced_at = at;
        peer.endpoints.put(endpoint);
    }
    Ok(Transition::accepted(
        peer,
        version,
        at,
        upload,
        download,
        u8::from(completed),
    ))
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct Counts {
    pub seeders: u8,
    pub leechers: u8,
    pub seeders_ipv4: u8,
    pub seeders_ipv6: u8,
    pub leechers_ipv4: u8,
    pub leechers_ipv6: u8,
}

impl Peer {
    /// Contribuicao de um peer, independente do truncamento da lista de resposta.
    pub fn counts(&self, require_connectivity: bool, at: Option<u64>, ttl: u64) -> Counts {
        let mut result = Counts::default();
        if !self.active || !self.visible {
            return result;
        }
        for endpoint in self.endpoints.iter().filter(|e| {
            at.is_none_or(|now| e.is_current(now, ttl))
                && (!require_connectivity || e.connectable == Some(true))
        }) {
            match (self.seeder, endpoint.family) {
                (true, Family::V4) => result.seeders_ipv4 = 1,
                (true, Family::V6) => result.seeders_ipv6 = 1,
                (false, Family::V4) => result.leechers_ipv4 = 1,
                (false, Family::V6) => result.leechers_ipv6 = 1,
            }
            if self.seeder {
                result.seeders = 1;
            } else {
                result.leechers = 1;
            }
        }
        result
    }
}
