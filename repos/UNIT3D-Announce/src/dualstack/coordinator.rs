//! Estado e enfileiramento atomicos em memoria; I/O somente fora do mutex.
//! O bootstrap exige entrada fechada e filas de qualquer backend anterior drenadas.
use std::{collections::{BTreeMap, BTreeSet, VecDeque}, sync::{Arc, atomic::{AtomicBool, AtomicU64, Ordering}}, time::{Duration, Instant}};

use parking_lot::Mutex;
use sqlx::MySqlPool;
use thiserror::Error;

use super::{peer::{self, Family, Operation, Outcome, Peer, Policy, Transition, TransitionError}, persistence::{self, Lease}};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct Identity {
    pub user_id: u32,
    pub torrent_id: u32,
    pub peer_id: [u8; 20],
}

impl Identity {
    pub(crate) fn group(self) -> (u32, u32) { (self.user_id, self.torrent_id) }
}

#[derive(Clone, Copy, Debug)]
pub struct Credit {
    pub upload_percent: u16,
    pub download_percent: u16,
    pub immune: bool,
}

impl Default for Credit {
    fn default() -> Self { Self { upload_percent: 100, download_percent: 100, immune: false } }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Settings {
    pub peer: Policy,
    pub max_peers: usize,
    pub max_pending: usize,
    pub batch_size: usize,
    pub require_connectivity: bool,
    pub seedtime_max_interval: u64,
    pub inactive_retention: u64,
}

impl Default for Settings {
    fn default() -> Self {
        Self { peer: Policy::default(), max_peers: 3, max_pending: 100_000, batch_size: 200,
            require_connectivity: false, seedtime_max_interval: 5400, inactive_retention: 1_814_400 }
    }
}

#[derive(Debug, Error)]
pub enum Error {
    #[error("Entrada indisponivel ou lease expirada")]
    Unavailable,
    #[error("Journal em memoria atingiu o limite")]
    BacklogFull,
    #[error("Limite de peers logicos atingido")]
    PeerLimit,
    #[error("Configuracao de coordenador invalida")]
    Configuration,
    #[error("Versao ou geracao divergente na persistencia")]
    Version,
    #[error("Estado persistido invalido; reconciliacao offline necessaria")]
    StoredState,
    #[error("Outro backend possui o swarm")]
    Owned,
    #[error("Recupere e drene o journal PHP antes da troca de backend")]
    PendingPhpJournal,
    #[error("Reconciliacao legada pendente; execute dualstack:legacy reconcile --offline no UNIT3D")]
    LegacyReconciliation,
    #[error("Tempo limite de {0} excedido")]
    Timeout(&'static str),
    #[error("Cancelamento do bootstrap nao confirmado no MySQL; mantenha a entrada fechada")]
    BootstrapCancellation,
    #[error("Falha na persistencia MySQL")]
    Database(#[from] sqlx::Error),
    #[error(transparent)]
    Transition(#[from] TransitionError),
    #[error("Falha na serializacao do estado")]
    Serialization(#[from] serde_json::Error),
}

impl Error {
    /// SQLSTATE descreve a classe; number identifica 1205/1213 no MySQL.
    pub fn retryable(&self) -> bool {
        match self {
            Self::Database(sqlx::Error::Database(error)) => error.try_downcast_ref::<sqlx::mysql::MySqlDatabaseError>()
                .is_some_and(|error| matches!(error.number(),1205 | 1213)),
            Self::Database(sqlx::Error::Io(_) | sqlx::Error::PoolTimedOut) | Self::Timeout("persistencia") => true,
            _ => false,
        }
    }
}

#[derive(Clone, Debug)]
pub(crate) struct Member { pub seeder: bool, pub expires_at: u64 }

#[derive(Clone, Debug, Default)]
pub(crate) struct Group {
    pub version: u64,
    pub completed: bool,
    pub last_at: u64,
    pub members: BTreeMap<[u8; 20], Member>,
}

#[derive(Clone, Debug)]
pub struct Change {
    pub(crate) generation: u64,
    pub(crate) sequence: u64,
    pub(crate) identity: Identity,
    pub(crate) peer: Peer,
    // Diferenca contra a referencia anterior, confirmada junto com o snapshot.
    pub(crate) endpoint_changes: [bool; 2],
    pub(crate) group: Group,
    pub(crate) upload: u64,
    pub(crate) download: u64,
    pub(crate) credited_upload: u64,
    pub(crate) credited_download: u64,
    pub(crate) immune: Option<bool>,
    pub(crate) counts: [i64; 6],
    pub(crate) completed: u64,
    pub(crate) seedtime: u64,
}

pub(crate) struct Swarm {
    pub deleted_users: BTreeSet<u32>,
    pub deleted_torrents: BTreeSet<u32>,
    pub peers: super::index::PeerIndex,
    pub completed: BTreeMap<u32,u64>,
    pub retiring: BTreeSet<Identity>,
    pub groups: BTreeMap<(u32, u32), Group>,
    pub leechers: BTreeMap<u32, BTreeMap<Identity, u64>>,
    pub pending: VecDeque<Arc<Change>>,
    pub sequence: u64,
    pub ready: bool,
    pub deadline: Instant,
}

/// Um mutex delimita leitura, calculo, fila e troca do estado. O consumidor usa
/// outro mutex async; a fila inclui o lote em voo ate o commit ser confirmado.
pub struct Coordinator {
    pub(crate) state: Mutex<Swarm>,
    pub(crate) writer: tokio::sync::Mutex<()>,
    pub(crate) lease: Lease,
    pub(crate) pool: MySqlPool,
    pub(crate) settings: Settings,
    clock: (u64, Instant),
    retries: AtomicU64,
    deadlock_retries: AtomicU64,
    pub(crate) input_closed: AtomicBool,
}

impl Coordinator {
    /// Entrada permanece fechada durante bootstrap e expiracao inicial.
    /// A lease SQL exige confirmacao de drenagem do ultimo proprietario PHP.
    pub async fn open(pool: MySqlPool, settings: Settings) -> Result<Self, Error> {
        Self::open_with_bootstrap_timeout(pool,settings,Duration::from_secs(120)).await
    }

    /// Prazo explicito para validacao de falhas; o startup HTTP usa 120 segundos.
    #[doc(hidden)]
    pub async fn open_with_bootstrap_timeout(pool: MySqlPool, settings: Settings, limit: Duration) -> Result<Self, Error> {
        if settings.max_pending == 0 || settings.max_peers == 0 || settings.batch_size == 0
            || settings.batch_size > 500 || settings.peer.endpoint_ttl == 0
            || !(1..=2).contains(&settings.peer.max_endpoints) || settings.inactive_retention < 7200 || limit.is_zero() {
            return Err(Error::Configuration);
        }
        let started = Instant::now();
        let (lease, epoch) = Lease::acquire(&pool).await?;
        let result = async {
            let state = super::bootstrap::load(&pool, &lease, settings, limit).await?;
            let result = Self { state: Mutex::new(state), writer: tokio::sync::Mutex::new(()),
                lease: lease.clone(), pool: pool.clone(), settings, clock: (epoch, started),
                retries: AtomicU64::new(0), deadlock_retries: AtomicU64::new(0), input_closed: AtomicBool::new(false) };
            result.renew().await?;
            loop {
                let count = result.expire_at(result.now(), true)?;
                result.flush().await?;
                result.renew().await?;
                if count == 0 { break; }
            }
            result.state.lock().ready = true;
            Ok(result)
        }.await;
        if result.is_err() && !matches!(result,Err(Error::BootstrapCancellation)) { let _ = lease.release(&pool).await; }
        result
    }

    pub fn now(&self) -> u64 { self.clock.0 + self.clock.1.elapsed().as_secs() }
    pub fn generation(&self) -> u64 { self.lease.generation }
    pub fn backlog(&self) -> usize { self.state.lock().pending.len() }
    pub fn retry_count(&self) -> u64 { self.retries.load(Ordering::Relaxed) }
    pub fn deadlock_retry_count(&self) -> u64 { self.deadlock_retries.load(Ordering::Relaxed) }
    pub fn peer(&self, identity: Identity) -> Option<Peer> { self.state.lock().peers.get(&identity).cloned() }
    pub fn close_input(&self) {
        let mut state = self.state.lock();
        self.input_closed.store(true, Ordering::Relaxed);
        state.ready = false;
    }
    pub(crate) fn pause_input(&self) { self.state.lock().ready = false; }

    pub async fn renew(&self) -> Result<(), Error> {
        let started = Instant::now();
        if let Err(error) = self.lease.renew(&self.pool).await {
            self.pause_input();
            return Err(error);
        }
        let deadline = started + Duration::from_secs(10);
        if Instant::now() >= deadline { self.pause_input(); return Err(Error::Unavailable); }
        self.state.lock().deadline = deadline;
        Ok(())
    }

    /// Sem await, SQL ou Redis. O relogio de producao deriva do MySQL no bootstrap.
    pub fn publish(&self, identity: Identity, operation: Operation, credit: Credit, download_slots: Option<usize>) -> Result<Transition, Error> {
        self.publish_at(identity, operation, credit, download_slots, self.now(), false)
    }

    /// Relogio explicito permite ensaiar TTL sem aguardar duas horas; nao usar no HTTP.
    #[doc(hidden)]
    pub fn publish_at(&self, identity: Identity, operation: Operation, credit: Credit,
        download_slots: Option<usize>, now: u64, initializing: bool) -> Result<Transition, Error> {
        let mut swarm = self.state.lock();
        if (!swarm.ready && !initializing) || Instant::now() >= swarm.deadline { return Err(Error::Unavailable); }
        if swarm.retiring.contains(&identity) { return Err(Error::Unavailable); }
        if swarm.deleted_users.contains(&identity.user_id) || swarm.deleted_torrents.contains(&identity.torrent_id) { return Err(Error::Unavailable); }
        let before = swarm.peers.get(&identity);
        let mut group = swarm.groups.get(&identity.group()).cloned().unwrap_or(Group { last_at: now, ..Group::default() });
        let now = now.max(group.last_at);
        let mut result = peer::apply(before, &operation, now, self.settings.peer)?;
        if result.outcome != Outcome::Accepted { return Ok(result); }
        // Nao muda estado ou versoes quando nao consegue reservar o item da fila.
        if swarm.pending.len() >= self.settings.max_pending { return Err(Error::BacklogFull); }
        let state = result.peer.as_mut().ok_or(Error::StoredState)?;
        let deadline = group.members.values().filter(|m| m.seeder).map(|m| m.expires_at).max().unwrap_or(0);
        group.members.retain(|_, member| member.expires_at > now);
        if state.active && !group.members.contains_key(&identity.peer_id) && group.members.len() >= self.settings.max_peers {
            return Err(Error::PeerLimit);
        }
        if state.active && !state.seeder && let Some(slots) = download_slots {
            let leechers = swarm.leechers.get(&identity.user_id).map_or(0, |peers| peers.iter()
                .filter(|(id,expires)| **id != identity && **expires > now).count());
            state.visible = state.visible && leechers < slots;
        }
        if state.active {
            let expires_at = state.endpoints.iter().map(|e| e.last_announced_at.saturating_add(self.settings.peer.endpoint_ttl)).max().unwrap();
            group.members.insert(identity.peer_id, Member { seeder: state.seeder, expires_at });
        } else { group.members.remove(&identity.peer_id); }
        group.version = group.version.checked_add(1).ok_or(Error::Version)?;
        let completed = u64::from(result.completed_delta != 0 && !group.completed);
        let total_completed = swarm.completed.get(&identity.torrent_id).copied().unwrap_or(0)
            .checked_add(completed).ok_or(Error::StoredState)?;
        group.completed |= completed != 0;
        let probe = matches!(operation, Operation::Probe { .. });
        let seedtime = if !probe && now - group.last_at <= self.settings.seedtime_max_interval { now.min(deadline).saturating_sub(group.last_at) } else { 0 };
        if !probe { group.last_at = now; }
        let counts = |p: Option<&Peer>| {
            let c = p.map(|p| p.counts(self.settings.require_connectivity, None, self.settings.peer.endpoint_ttl)).unwrap_or_default();
            [c.seeders, c.leechers, c.seeders_ipv4, c.seeders_ipv6, c.leechers_ipv4, c.leechers_ipv6].map(i64::from)
        };
        let old = counts(before);
        let new = counts(Some(state));
        let sequence = swarm.sequence.checked_add(1).ok_or(Error::Version)?;
        let change = Arc::new(Change { generation: self.lease.generation, sequence, identity,
            endpoint_changes: [Family::V4,Family::V6].map(|family|
                before.and_then(|p| p.endpoints.get(family)) != state.endpoints.get(family)),
            peer: state.clone(), group: group.clone(), upload: result.upload_delta, download: result.download_delta,
            credited_upload: peer::credit_percent(result.upload_delta, credit.upload_percent)?,
            credited_download: peer::credit_percent(result.download_delta, credit.download_percent)?,
            immune: matches!(operation, Operation::Announce(_)).then_some(credit.immune),
            counts: std::array::from_fn(|i| new[i] - old[i]), completed, seedtime });
        swarm.pending.push_back(change);
        swarm.completed.insert(identity.torrent_id,total_completed);
        swarm.sequence = sequence;
        let leechers = swarm.leechers.entry(identity.user_id).or_default();
        leechers.retain(|_, expires| *expires > now);
        if state.active && state.visible && !state.seeder {
            leechers.insert(identity, state.endpoints.iter().map(|e| e.last_announced_at.saturating_add(self.settings.peer.endpoint_ttl)).max().unwrap());
        } else { leechers.remove(&identity); }
        if leechers.is_empty() { swarm.leechers.remove(&identity.user_id); }
        swarm.peers.insert(identity, state.clone());
        swarm.groups.insert(identity.group(), group);
        result.completed_delta = completed as u8;
        Ok(result)
    }

    pub fn expire(&self) -> Result<usize, Error> { self.expire_at(self.now(), false) }
    #[doc(hidden)]
    pub fn expire_at(&self, now: u64, initializing: bool) -> Result<usize, Error> {
        let swarm = self.state.lock();
        let due: Vec<_> = swarm.peers.iter().filter(|(id, p)| !swarm.deleted_users.contains(&id.user_id) && !swarm.deleted_torrents.contains(&id.torrent_id) && p.endpoints.iter().any(|e| !e.is_current(now, self.settings.peer.endpoint_ttl)))
            .take(self.settings.batch_size.min(self.settings.max_pending)).map(|(id, _)| *id).collect();
        drop(swarm);
        let mut accepted = 0;
        for identity in due {
            let result = self.publish_at(identity, Operation::Expire, Credit::default(), None, now, initializing)?;
            accepted += usize::from(result.outcome == Outcome::Accepted);
        }
        Ok(accepted)
    }

    /// Snapshot nao retira mensagens; crash depois do commit pode reentregar o lote.
    pub fn batch(&self) -> Vec<Arc<Change>> { self.state.lock().pending.iter().take(self.settings.batch_size).cloned().collect() }

    pub async fn persist_batch(&self, batch: &[Arc<Change>]) -> Result<usize, Error> {
        // Serializa inclusive chamadas de teste/reentrega. SQL acontece sem o mutex do swarm.
        let _writer = self.writer.lock().await;
        persistence::persist(&self.pool, &self.lease, batch).await
    }

    pub async fn flush(&self) -> Result<usize, Error> {
        let _writer = self.writer.lock().await;
        let batch = self.batch();
        if batch.is_empty() { return Ok(0); }
        let mut last = None;
        for attempt in 0..3 {
            match persistence::persist(&self.pool, &self.lease, &batch).await {
                Ok(_) => {
                    let last_sequence = batch.last().unwrap().sequence;
                    let mut swarm = self.state.lock();
                    while swarm.pending.front().is_some_and(|item| item.sequence <= last_sequence) { swarm.pending.pop_front(); }
                    return Ok(batch.len());
                }
                Err(error) => {
                    let retryable = error.retryable();
                    let deadlock = matches!(&error,Error::Database(sqlx::Error::Database(error))
                        if error.try_downcast_ref::<sqlx::mysql::MySqlDatabaseError>().is_some_and(|error| error.number()==1213));
                    last = Some(error);
                    if !retryable || attempt == 2 { break; }
                    self.retries.fetch_add(1,Ordering::Relaxed);
                    if deadlock { self.deadlock_retries.fetch_add(1,Ordering::Relaxed); }
                    tokio::time::sleep(Duration::from_millis(50 * (1 << attempt))).await;
                }
            }
        }
        self.close_input();
        Err(last.unwrap())
    }

    // O runtime renova entre tentativas: nao segura o escritor durante retries.
    pub(crate) async fn flush_once(&self) -> Result<usize, Error> {
        let _writer = self.writer.lock().await;
        let batch = self.batch();
        if batch.is_empty() { return Ok(0); }
        persistence::persist(&self.pool, &self.lease, &batch).await?;
        let last = batch.last().unwrap().sequence;
        let mut state = self.state.lock();
        while state.pending.front().is_some_and(|item| item.sequence <= last) { state.pending.pop_front(); }
        Ok(batch.len())
    }

    pub(crate) fn record_retry(&self, error: &Error) {
        self.retries.fetch_add(1, Ordering::Relaxed);
        if matches!(error, Error::Database(sqlx::Error::Database(e))
            if e.try_downcast_ref::<sqlx::mysql::MySqlDatabaseError>().is_some_and(|e| e.number()==1213)) {
            self.deadlock_retries.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub async fn shutdown(&self) -> Result<(), Error> {
        self.close_input();
        tokio::time::timeout(Duration::from_secs(120), async {
            while self.backlog() > 0 {
                self.renew().await?;
                self.flush().await?;
            }
            while self.remove_deleted().await? { self.renew().await?; }
            self.lease.release(&self.pool).await
        }).await.map_err(|_| Error::Timeout("encerramento"))?
    }

    /// O runtime conserva a operacao em voo e renova entre transacoes.
    pub async fn run(&self, stop: tokio::sync::watch::Receiver<bool>) -> Result<(), Error> {
        let result=super::runtime::run(self, stop).await;
        self.close_input();
        if let Err(error) = &result {
            tracing::error!(generation=self.generation(), pending=self.backlog(), error=%error,
                "Coordenador encerrado com entrada fechada; transicoes pendentes nao foram confirmadas");
        }
        result
    }
}
