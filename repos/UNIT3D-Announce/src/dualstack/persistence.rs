use std::{collections::{BTreeMap, BTreeSet, VecDeque}, net::IpAddr, sync::Arc, time::{Duration, Instant}};

use chrono::{DateTime, NaiveDateTime, Utc};
use futures_util::TryStreamExt;
use serde_json::{Value, json};
use sqlx::{Connection, MySql, MySqlConnection, MySqlPool, QueryBuilder, Row, Transaction, mysql::MySqlRow};

use super::{coordinator::{Change, Error, Group, Identity, Member, Settings, Swarm}, peer::{Endpoint, Endpoints, Family, LastAnnounces, Peer, observed_address}};

#[derive(Clone)]
pub(crate) struct Lease { pub generation: u64, owner: String }

impl Lease {
    pub async fn acquire(pool: &MySqlPool) -> Result<(Self, u64), Error> {
        tokio::time::timeout(Duration::from_secs(3),Self::acquire_inner(pool)).await
            .map_err(|_| Error::Timeout("aquisicao da lease"))?
    }

    async fn acquire_inner(pool: &MySqlPool) -> Result<(Self, u64), Error> {
        let mut tx = pool.begin().await?;
        let row = sqlx::query("SELECT generation, backend, php_journal_drained, legacy_reconciliation_required, COALESCE(lease_expires_at > UTC_TIMESTAMP(3), 0) AS live, UUID() AS owner, CAST(UNIX_TIMESTAMP(UTC_TIMESTAMP()) AS UNSIGNED) AS epoch FROM tracker_ownership WHERE id=1 FOR UPDATE")
            .fetch_one(&mut *tx).await?;
        if row.try_get::<i64,_>("live")? != 0 { return Err(Error::Owned); }
        if row.try_get::<bool,_>("legacy_reconciliation_required")? { return Err(Error::LegacyReconciliation); }
        if row.try_get::<Option<String>,_>("backend")?.as_deref()==Some("php") && !row.try_get::<bool,_>("php_journal_drained")? {
            return Err(Error::PendingPhpJournal);
        }
        let generation = row.try_get::<u64,_>("generation")?.checked_add(1).ok_or(Error::Version)?;
        let lease = Self { generation, owner: row.try_get("owner")? };
        sqlx::query("UPDATE tracker_ownership SET generation=?, owner_id=?, backend='rust', lease_expires_at=UTC_TIMESTAMP(3)+INTERVAL 30 SECOND WHERE id=1")
            .bind(generation).bind(&lease.owner).execute(&mut *tx).await?;
        tx.commit().await?;
        Ok((lease, row.try_get("epoch")?))
    }

    pub async fn renew(&self, pool: &MySqlPool) -> Result<(), Error> {
        let result = tokio::time::timeout(Duration::from_secs(3),sqlx::query("UPDATE tracker_ownership SET lease_expires_at=UTC_TIMESTAMP(3)+INTERVAL 30 SECOND WHERE id=1 AND owner_id=? AND generation=? AND lease_expires_at > UTC_TIMESTAMP(3)")
            .bind(&self.owner).bind(self.generation).execute(pool)).await.map_err(|_| Error::Timeout("renovacao da lease"))??;
        if result.rows_affected() != 1 { return Err(Error::Unavailable); }
        Ok(())
    }

    pub async fn release(&self, pool: &MySqlPool) -> Result<(), Error> {
        tokio::time::timeout(Duration::from_secs(3),sqlx::query("UPDATE tracker_ownership SET lease_expires_at=UTC_TIMESTAMP(3) WHERE id=1 AND owner_id=? AND generation=?")
            .bind(&self.owner).bind(self.generation).execute(pool)).await.map_err(|_| Error::Timeout("liberacao da lease"))??;
        Ok(())
    }

    pub(crate) async fn release_on(&self, connection: &mut MySqlConnection) -> Result<(), Error> {
        tokio::time::timeout(Duration::from_secs(3),sqlx::query("UPDATE tracker_ownership SET lease_expires_at=UTC_TIMESTAMP(3) WHERE id=1 AND owner_id=? AND generation=?")
            .bind(&self.owner).bind(self.generation).execute(connection)).await.map_err(|_| Error::Timeout("liberacao da lease"))??;
        Ok(())
    }

    pub(crate) async fn fence(&self, tx: &mut Transaction<'_, MySql>) -> Result<(), Error> {
        let row = sqlx::query("SELECT generation, owner_id, COALESCE(lease_expires_at > UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1 FOR SHARE")
            .fetch_one(&mut **tx).await?;
        if row.try_get::<u64,_>("generation")? != self.generation || row.try_get::<String,_>("owner_id")? != self.owner
            || row.try_get::<i64,_>("live")? != 1 { return Err(Error::Unavailable); }
        Ok(())
    }
}

fn identity(row: &MySqlRow) -> Result<Identity, Error> {
    Ok(Identity { user_id: row.try_get("user_id")?, torrent_id: row.try_get("torrent_id")?,
        peer_id: row.try_get::<Vec<u8>,_>("peer_id")?.try_into().map_err(|_| Error::StoredState)? })
}
fn epoch(row: &MySqlRow, name: &str) -> Result<u64, Error> {
    // Colunas TIMESTAMP usam o codec UTC; completed_at (DATETIME) e lido separadamente.
    let date: Option<DateTime<Utc>> = row.try_get(name)?;
    Ok(date.map(|t| t.timestamp()).unwrap_or(0).try_into().map_err(|_| Error::StoredState)?)
}
fn date(at: u64) -> Result<NaiveDateTime, Error> {
    DateTime::from_timestamp(at.try_into().map_err(|_| Error::StoredState)?, 0).map(|d| d.naive_utc()).ok_or(Error::StoredState)
}
fn ip(row: &MySqlRow, column: &str, private: bool) -> Result<IpAddr, Error> {
    let ip: String = row.try_get(column)?;
    Ok(observed_address(ip.parse().map_err(|_| Error::StoredState)?, private)?)
}
fn binary(ip: IpAddr) -> Vec<u8> { match ip { IpAddr::V4(ip) => ip.octets().to_vec(), IpAddr::V6(ip) => ip.octets().to_vec() } }

/// Leitura por streaming, quatro consultas de dados; nenhuma consulta por peer.
/// Historicos sem peers guardam somente versao/conclusao para deduplicar reconexao.
pub(crate) async fn load(connection: &mut MySqlConnection, pool: &MySqlPool, lease: &Lease, settings: Settings) -> Result<Swarm, Error> {
    let mut state = Swarm { deleted_users: BTreeSet::new(), deleted_torrents: BTreeSet::new(), peers: super::index::PeerIndex::default(), completed: BTreeMap::new(), retiring: BTreeSet::new(), groups: BTreeMap::new(), leechers: BTreeMap::new(), pending: VecDeque::new(), sequence: 0, ready: false, deadline: Instant::now() };
    for (table, deleted) in [("users", &mut state.deleted_users), ("torrents", &mut state.deleted_torrents)] {
        let query=format!("SELECT id FROM {table} WHERE deleted_at IS NOT NULL ORDER BY id");
        let mut rows=sqlx::query_scalar::<_,u32>(&query).fetch(&mut *connection);
        let mut count=0;
        while let Some(id)=rows.try_next().await? {
            deleted.insert(id); count+=1;
            if count%500==0 { lease.renew(pool).await?; }
        }
    }
    let mut n = 0;
    let mut torrents = sqlx::query("SELECT id,times_completed FROM torrents ORDER BY id").fetch(&mut *connection);
    while let Some(row) = torrents.try_next().await? {
        state.completed.insert(row.try_get("id")?,u64::try_from(row.try_get::<i32,_>("times_completed")?).map_err(|_|Error::StoredState)?);
        n += 1;
        if n % 500 == 0 { lease.renew(pool).await?; }
    }
    drop(torrents);
    let mut history = sqlx::query("SELECT user_id,torrent_id,state_version,completed_at,swarm_updated_at,updated_at FROM history ORDER BY user_id,torrent_id").fetch(&mut *connection);
    while let Some(row) = history.try_next().await? {
        let swarm_at = epoch(&row, "swarm_updated_at")?;
        state.groups.insert((row.try_get("user_id")?, row.try_get("torrent_id")?), Group {
            version: row.try_get("state_version")?, completed: row.try_get::<Option<NaiveDateTime>,_>("completed_at")?.is_some(),
            last_at: if swarm_at != 0 { swarm_at } else { epoch(&row, "updated_at")? }, members: BTreeMap::new() });
        n += 1;
        if n % 500 == 0 { lease.renew(pool).await?; }
    }
    drop(history);
    let mut peers = sqlx::query("SELECT *,INET6_NTOA(ip) AS address FROM peers ORDER BY user_id,torrent_id,peer_id").fetch(&mut *connection);
    while let Some(row) = peers.try_next().await? {
        let key = identity(&row)?;
        let address = ip(&row, "address", settings.peer.allow_private_addresses)?;
        let updated = epoch(&row, "updated_at")?;
        let created = epoch(&row, "created_at")?;
        let protocol: Option<Value> = row.try_get("protocol_state")?;
        let mut last = LastAnnounces::default();
        for family in [Family::V4, Family::V6] {
            last.0[family.index()] = protocol.as_ref().and_then(|v| v["last_announces"][family.number().to_string()].as_u64());
        }
        let legacy = Endpoint { family: Family::of(address), ip: address, port: row.try_get("port")?,
            connectable: Some(row.try_get("connectable")?), connectivity_checked_at: None,
            revision: row.try_get("state_version")?, created_at: created, last_announced_at: updated };
        let peer = Peer { uploaded: row.try_get("uploaded")?, downloaded: row.try_get("downloaded")?, left: row.try_get("left")?,
            agent: row.try_get("agent")?, visible: row.try_get("visible")?, endpoints: Endpoints::default(), last_announces: last,
            session_generation: row.try_get("session_generation")?, completion_reported: row.try_get("completion_reported")?,
            created_at: created, session_started_at: protocol.as_ref().and_then(|v| v["session_started_at"].as_u64()).unwrap_or(updated),
            legacy_endpoint: Some(legacy), state_version: row.try_get("state_version")?, updated_at: updated,
            active: row.try_get("active")?, seeder: row.try_get("seeder")?, connectable: false };
        state.groups.entry(key.group()).or_insert(Group { last_at: updated, ..Group::default() });
        state.peers.insert(key, peer);
        n += 1;
        if n % 500 == 0 { lease.renew(pool).await?; }
    }
    drop(peers);
    let mut endpoints = sqlx::query("SELECT *,INET6_NTOA(ip) AS address FROM peer_ips ORDER BY user_id,torrent_id,peer_id,family").fetch(&mut *connection);
    while let Some(row) = endpoints.try_next().await? {
        let key = identity(&row)?;
        let peer = state.peers.get_mut(&key).ok_or(Error::StoredState)?;
        if !peer.active { continue; }
        let address = ip(&row, "address", settings.peer.allow_private_addresses)?;
        let family = Family::of(address);
        if family.number() != row.try_get::<u8,_>("family")? { return Err(Error::StoredState); }
        let last = epoch(&row, "last_announced_at")?;
        let checked = epoch(&row, "connectivity_checked_at")?;
        let endpoint = Endpoint { family, ip: address, port: row.try_get("port")?, connectable: row.try_get("connectable")?,
            connectivity_checked_at: (checked != 0).then_some(checked), revision: row.try_get("revision")?,
            created_at: epoch(&row, "created_at")?, last_announced_at: last };
        peer.connectable |= endpoint.connectable == Some(true);
        peer.endpoints.put(endpoint);
        peer.last_announces.0[family.index()].get_or_insert(last);
        let group = state.groups.get_mut(&key.group()).unwrap();
        group.members.entry(key.peer_id).and_modify(|m| m.expires_at = m.expires_at.max(last.saturating_add(settings.peer.endpoint_ttl)))
            .or_insert(Member { seeder: peer.seeder, expires_at: last.saturating_add(settings.peer.endpoint_ttl) });
        n += 1;
        if n % 500 == 0 { lease.renew(pool).await?; }
    }
    drop(endpoints);
    if state.peers.values().any(|p| p.active && p.endpoints.is_empty()) { return Err(Error::StoredState); }
    for (id,p) in state.peers.iter_mut() {
        if p.active {
            p.legacy_endpoint = p.endpoints.iter().find(|e| e.connectable == Some(true)).or_else(|| p.endpoints.iter().next()).cloned();
            if p.visible && !p.seeder {
                let expires = p.endpoints.iter().map(|e| e.last_announced_at.saturating_add(settings.peer.endpoint_ttl)).max().unwrap();
                state.leechers.entry(id.user_id).or_default().insert(*id, expires);
            }
        }
    }
    // Reconciliacao confirmada sem TTL; a expiracao inicial gera as transicoes seguintes.
    let mut tx = connection.begin().await?;
    lease.fence(&mut tx).await?;
    let query = reconciliation_query(settings.require_connectivity);
    sqlx::query(&query).execute(&mut *tx).await?;
    tx.commit().await?;
    state.deadline = Instant::now() + Duration::from_secs(10);
    Ok(state)
}

pub(crate) fn reconciliation_query(require_connectivity: bool) -> String {
    let connected = if require_connectivity { " WHERE connectable=1" } else { "" };
    let mut query = String::from("UPDATE torrents t LEFT JOIN (SELECT p.torrent_id,");
    let fields = ["seeders", "leechers", "seeders_ipv4", "seeders_ipv6", "leechers_ipv4", "leechers_ipv6"];
    for (i, field) in fields.iter().enumerate() {
        if i > 0 { query.push(','); }
        let seeder = if field.starts_with("seeders") { 1 } else { 0 };
        let family = if field.ends_with('4') { " AND e.ipv4=1" } else if field.ends_with('6') { " AND e.ipv6=1" } else { "" };
        query.push_str(&format!("SUM(p.seeder={seeder}{family}) AS {field}"));
    }
    // GROUP BY materializa uma linha por identidade; a juncao seguinte consulta
    // uma unica chave primaria. A densidade de um torrent nao amplia cada lookup.
    query.push_str(&format!(" FROM (SELECT user_id,torrent_id,peer_id,MAX(family=4) AS ipv4,MAX(family=6) AS ipv6 FROM peer_ips{connected} GROUP BY user_id,torrent_id,peer_id) e STRAIGHT_JOIN peers p FORCE INDEX (PRIMARY) ON p.user_id=e.user_id AND p.torrent_id=e.torrent_id AND p.peer_id=e.peer_id WHERE p.active=1 AND p.visible=1 GROUP BY p.torrent_id) c ON c.torrent_id=t.id SET "));
    query.push_str(&fields.iter().map(|f| format!("t.{f}=COALESCE(c.{f},0)")).collect::<Vec<_>>().join(","));
    query
}

#[derive(Clone)]
struct History {
    user: u32, torrent: u32, agent: String, uploaded: u64, downloaded: u64,
    actual_uploaded: u64, actual_downloaded: u64, client_uploaded: u64, client_downloaded: u64,
    active: bool, seeder: bool, immune: bool, seedtime: u64, created_at: NaiveDateTime,
    updated_at: NaiveDateTime, completed_at: Option<NaiveDateTime>, version: u64, swarm_at: NaiveDateTime,
}
impl History {
    fn row(row: MySqlRow) -> Result<Self, Error> {
        Ok(Self { user: row.try_get("user_id")?, torrent: row.try_get("torrent_id")?, agent: row.try_get("agent")?,
            uploaded: row.try_get("uploaded")?, downloaded: row.try_get("downloaded")?, actual_uploaded: row.try_get("actual_uploaded")?, actual_downloaded: row.try_get("actual_downloaded")?,
            client_uploaded: row.try_get("client_uploaded")?, client_downloaded: row.try_get("client_downloaded")?,
            active: row.try_get("active")?, seeder: row.try_get("seeder")?, immune: row.try_get("immune")?, seedtime: row.try_get("seedtime")?,
            created_at: date(epoch(&row,"created_at")?)?, updated_at: date(epoch(&row,"updated_at")?)?, completed_at: row.try_get("completed_at")?,
            version: row.try_get("state_version")?, swarm_at: date(epoch(&row,"swarm_updated_at")?)? })
    }
    fn initial(change: &Change) -> Result<Self, Error> {
        let at = date(change.peer.updated_at)?;
        Ok(Self { user: change.identity.user_id, torrent: change.identity.torrent_id, agent: change.peer.agent.clone(),
            uploaded: 0, downloaded: 0, actual_uploaded: 0, actual_downloaded: 0, client_uploaded: 0, client_downloaded: 0,
            active: false, seeder: false, immune: change.immune.unwrap_or(false), seedtime: 0,
            created_at: at, updated_at: at, completed_at: None, version: 0, swarm_at: at })
    }
    fn advance(&mut self, c: &Change) -> Result<(), Error> {
        let add = |a: u64, b: u64| a.checked_add(b).ok_or(Error::Transition(super::peer::TransitionError::Overflow));
        self.uploaded = add(self.uploaded, c.credited_upload)?; self.downloaded = add(self.downloaded, c.credited_download)?;
        self.actual_uploaded = add(self.actual_uploaded, c.upload)?; self.actual_downloaded = add(self.actual_downloaded, c.download)?;
        self.client_uploaded = c.peer.uploaded; self.client_downloaded = c.peer.downloaded;
        self.agent = c.peer.agent.clone(); self.active = !c.group.members.is_empty();
        self.seeder = c.group.members.values().any(|m| m.seeder); self.immune &= c.immune.unwrap_or(true);
        self.seedtime = add(self.seedtime, c.seedtime)?; self.version = c.group.version;
        self.updated_at = date(c.peer.updated_at)?; self.swarm_at = date(c.group.last_at)?;
        if c.completed != 0 && self.completed_at.is_none() { self.completed_at = Some(self.updated_at); }
        Ok(())
    }
}

pub(crate) fn peer_tuples(query: &mut QueryBuilder<'_, MySql>, ids: impl Iterator<Item=Identity>) {
    let mut list = query.separated(",");
    for id in ids { list.push("(").push_bind_unseparated(id.user_id).push_unseparated(",")
        .push_bind_unseparated(id.torrent_id).push_unseparated(",").push_bind_unseparated(id.peer_id.to_vec()).push_unseparated(")"); }
}

/// Exclusao limitada e cercada pela mesma geracao dos lotes financeiros.
pub(crate) async fn retire(pool: &MySqlPool, lease: &Lease, candidates: &[(Identity,u64)], cutoff: u64) -> Result<(), Error> {
    if candidates.is_empty() || candidates.len()>500 { return Err(Error::Configuration); }
    let mut tx=pool.begin().await?;
    lease.fence(&mut tx).await?;
    let mut query=QueryBuilder::<MySql>::new("DELETE FROM peers WHERE active=0 AND updated_at<");
    query.push_bind(date(cutoff)?).push(" AND (user_id,torrent_id,peer_id,state_version) IN (");
    {
        let mut list=query.separated(",");
        for (id,version) in candidates {
            list.push("(").push_bind_unseparated(id.user_id).push_unseparated(",")
                .push_bind_unseparated(id.torrent_id).push_unseparated(",")
                .push_bind_unseparated(id.peer_id.to_vec()).push_unseparated(",")
                .push_bind_unseparated(*version).push_unseparated(")");
        }
    }
    query.push(")");
    if query.build().execute(&mut *tx).await?.rows_affected()!=candidates.len() as u64 { return Err(Error::Version); }
    tx.commit().await?;
    Ok(())
}

/// Lock global: proprietario compartilhado, usuarios, torrents, historicos, peers.
/// Ordens identicas ao consumidor PHP. Um lote confirma snapshots e efeitos juntos.
pub(crate) async fn persist(pool: &MySqlPool, lease: &Lease, batch: &[Arc<Change>]) -> Result<usize, Error> {
    tokio::time::timeout(Duration::from_secs(15), persist_inner(pool, lease, batch)).await.map_err(|_| Error::Timeout("persistencia"))?
}

async fn persist_inner(pool: &MySqlPool, lease: &Lease, batch: &[Arc<Change>]) -> Result<usize, Error> {
    if batch.is_empty() { return Ok(0); }
    if batch.len() > 500 || batch.iter().any(|c| c.generation != lease.generation) { return Err(Error::Version); }
    let mut ordered = batch.to_vec();
    ordered.sort_by_key(|c| (c.identity.user_id, c.identity.torrent_id, c.group.version));
    let users: BTreeSet<_> = ordered.iter().map(|c| c.identity.user_id).collect();
    let torrents: BTreeSet<_> = ordered.iter().map(|c| c.identity.torrent_id).collect();
    let groups: BTreeSet<_> = ordered.iter().map(|c| c.identity.group()).collect();
    let identities: BTreeSet<_> = ordered.iter().map(|c| c.identity).collect();
    let mut tx = pool.begin().await?;
    lease.fence(&mut tx).await?;
    let mut sealed_users=BTreeSet::new();
    let mut sealed_torrents=BTreeSet::new();
    for (table, ids) in [("users", &users), ("torrents", &torrents)] {
        let mut q = QueryBuilder::<MySql>::new(format!("SELECT id,(deleted_at IS NOT NULL AND tracker_removal_state>0) AS sealed FROM {table} WHERE id IN ("));
        { let mut values = q.separated(","); for id in ids { values.push_bind(*id); } }
        q.push(") ORDER BY id FOR UPDATE");
        let rows=q.build().fetch_all(&mut *tx).await?;
        if rows.len() != ids.len() { return Err(Error::StoredState); }
        for row in rows { if row.try_get::<i64,_>("sealed")?!=0 {
            if table=="users" { sealed_users.insert(row.try_get::<u32,_>("id")?); }
            else { sealed_torrents.insert(row.try_get::<u32,_>("id")?); }
        } }
    }
    let mut q = QueryBuilder::<MySql>::new("SELECT * FROM history WHERE (user_id,torrent_id) IN (");
    { let mut tuples = q.separated(","); for (user,torrent) in groups { tuples.push("(").push_bind_unseparated(user).push_unseparated(",").push_bind_unseparated(torrent).push_unseparated(")"); } }
    q.push(") ORDER BY user_id,torrent_id FOR UPDATE");
    let mut histories = BTreeMap::new();
    for row in q.build().fetch_all(&mut *tx).await? { let h = History::row(row)?; histories.insert((h.user,h.torrent),h); }
    let mut q = QueryBuilder::<MySql>::new("SELECT user_id,torrent_id,peer_id,state_version FROM peers WHERE (user_id,torrent_id,peer_id) IN (");
    peer_tuples(&mut q, identities.iter().copied()); q.push(") ORDER BY user_id,torrent_id,peer_id FOR UPDATE");
    let mut versions = BTreeMap::new();
    for row in q.build().fetch_all(&mut *tx).await? { versions.insert(identity(&row)?, row.try_get::<u64,_>("state_version")?); }
    let mut final_peers = BTreeMap::new();
    let mut endpoint_changes = BTreeMap::new();
    let mut changed_histories = BTreeSet::new();
    let mut user_deltas: BTreeMap<u32,[u64;2]> = BTreeMap::new();
    let mut torrent_deltas: BTreeMap<u32,[i128;8]> = BTreeMap::new();
    let mut applied = 0;
    for change in &ordered {
        let key = change.identity;
        if sealed_users.contains(&key.user_id) || sealed_torrents.contains(&key.torrent_id) { continue; }
        let history = histories.entry(key.group()).or_insert(History::initial(change)?);
        if change.group.version <= history.version { continue; }
        if history.version.checked_add(1) != Some(change.group.version)
            || versions.get(&key).copied().unwrap_or(0).checked_add(1) != Some(change.peer.state_version) { return Err(Error::Version); }
        history.advance(change)?;
        changed_histories.insert(key.group()); versions.insert(key,change.peer.state_version);
        final_peers.insert(key,change.peer.clone());
        // Reentregas ignoradas acima nao podem restaurar endpoints antigos.
        // A ultima mudanca por familia vence dentro do lote, inclusive remocoes.
        for (index,family) in [Family::V4,Family::V6].into_iter().enumerate() {
            if change.endpoint_changes[index] {
                endpoint_changes.insert((key,family.number()),(change.peer.endpoints.get(family),change.peer.updated_at));
            }
        }
        let user = user_deltas.entry(key.user_id).or_default();
        user[0] = user[0].checked_add(change.credited_upload).ok_or(Error::StoredState)?;
        user[1] = user[1].checked_add(change.credited_download).ok_or(Error::StoredState)?;
        let torrent = torrent_deltas.entry(key.torrent_id).or_default();
        for (index, delta) in change.counts.iter().enumerate() { torrent[index] += i128::from(*delta); }
        torrent[6] += i128::from(change.completed);
        torrent[7] += i128::from(change.upload) - i128::from(change.download);
        applied += 1;
    }
    if applied == 0 { tx.commit().await?; return Ok(0); }
    let mut q = QueryBuilder::<MySql>::new("INSERT INTO peers (user_id,torrent_id,peer_id,agent,uploaded,downloaded,`left`,seeder,active,visible,ip,port,connectable,created_at,updated_at,state_version,session_generation,completion_reported,protocol_state) ");
    // Valida timestamps e projecao antes de construir o lote.
    for peer in final_peers.values() { date(peer.created_at)?; date(peer.updated_at)?; if peer.legacy_endpoint.is_none() { return Err(Error::StoredState); } }
    q.push_values(&final_peers, |mut b,(id,p)| {
        let legacy = p.legacy_endpoint.as_ref().unwrap();
        b.push_bind(id.user_id).push_bind(id.torrent_id).push_bind(id.peer_id.to_vec()).push_bind(p.agent.clone())
            .push_bind(p.uploaded).push_bind(p.downloaded).push_bind(p.left).push_bind(p.seeder).push_bind(p.active).push_bind(p.visible)
            .push_bind(binary(legacy.ip)).push_bind(legacy.port).push_bind(p.connectable).push_bind(date(p.created_at).unwrap()).push_bind(date(p.updated_at).unwrap())
            .push_bind(p.state_version).push_bind(p.session_generation).push_bind(p.completion_reported)
            .push_bind(json!({"last_announces":p.last_announces,"session_started_at":p.session_started_at}));
    });
    q.push(" ON DUPLICATE KEY UPDATE agent=VALUES(agent),uploaded=VALUES(uploaded),downloaded=VALUES(downloaded),`left`=VALUES(`left`),seeder=VALUES(seeder),active=VALUES(active),visible=VALUES(visible),ip=VALUES(ip),port=VALUES(port),connectable=VALUES(connectable),updated_at=VALUES(updated_at),state_version=VALUES(state_version),session_generation=VALUES(session_generation),completion_reported=VALUES(completion_reported),protocol_state=VALUES(protocol_state)");
    q.build().execute(&mut *tx).await?;
    // Persistir somente familias alteradas nas transicoes ainda nao confirmadas.
    let removed:Vec<_>=endpoint_changes.iter().filter(|(_, (endpoint,_))| endpoint.is_none()).map(|(key,_)| key).collect();
    if !removed.is_empty() {
        let mut q=QueryBuilder::<MySql>::new("DELETE FROM peer_ips WHERE (user_id,torrent_id,peer_id,family) IN (");
        {
            let mut tuples=q.separated(",");
            for (id,family) in removed {
                tuples.push("(").push_bind_unseparated(id.user_id).push_unseparated(",")
                    .push_bind_unseparated(id.torrent_id).push_unseparated(",").push_bind_unseparated(id.peer_id.to_vec())
                    .push_unseparated(",").push_bind_unseparated(*family).push_unseparated(")");
            }
        }
        q.push(")"); q.build().execute(&mut *tx).await?;
    }
    let endpoints:Vec<_>=endpoint_changes.iter().filter_map(|((id,_),(endpoint,at))| endpoint.map(|e| (id,e,*at))).collect();
    if !endpoints.is_empty() {
        for (_,e,at) in &endpoints { date(*at)?; date(e.last_announced_at)?; date(e.created_at)?; if let Some(at)=e.connectivity_checked_at { date(at)?; } }
        let mut q = QueryBuilder::<MySql>::new("INSERT INTO peer_ips (user_id,torrent_id,peer_id,family,ip,port,connectable,last_announced_at,connectivity_checked_at,revision,created_at,updated_at) ");
        q.push_values(endpoints, |mut b,(id,e,at)| {
            b.push_bind(id.user_id).push_bind(id.torrent_id).push_bind(id.peer_id.to_vec()).push_bind(e.family.number()).push_bind(binary(e.ip))
                .push_bind(e.port).push_bind(e.connectable).push_bind(date(e.last_announced_at).unwrap()).push_bind(e.connectivity_checked_at.map(|t| date(t).unwrap()))
                .push_bind(e.revision).push_bind(date(e.created_at).unwrap()).push_bind(date(at).unwrap());
        });
        q.push(" ON DUPLICATE KEY UPDATE ip=VALUES(ip),port=VALUES(port),connectable=VALUES(connectable),last_announced_at=VALUES(last_announced_at),connectivity_checked_at=VALUES(connectivity_checked_at),revision=VALUES(revision),created_at=VALUES(created_at),updated_at=VALUES(updated_at)");
        q.build().execute(&mut *tx).await?;
    }
    let mut q = QueryBuilder::<MySql>::new("INSERT INTO history (user_id,torrent_id,agent,uploaded,downloaded,actual_uploaded,actual_downloaded,client_uploaded,client_downloaded,active,seeder,immune,seedtime,created_at,updated_at,completed_at,state_version,swarm_updated_at) ");
    q.push_values(changed_histories.iter().map(|key| &histories[key]), |mut b,h| {
        b.push_bind(h.user).push_bind(h.torrent).push_bind(h.agent.clone()).push_bind(h.uploaded).push_bind(h.downloaded)
            .push_bind(h.actual_uploaded).push_bind(h.actual_downloaded).push_bind(h.client_uploaded).push_bind(h.client_downloaded)
            .push_bind(h.active).push_bind(h.seeder).push_bind(h.immune).push_bind(h.seedtime).push_bind(h.created_at)
            .push_bind(h.updated_at).push_bind(h.completed_at).push_bind(h.version).push_bind(h.swarm_at);
    });
    q.push(" ON DUPLICATE KEY UPDATE agent=VALUES(agent),uploaded=VALUES(uploaded),downloaded=VALUES(downloaded),actual_uploaded=VALUES(actual_uploaded),actual_downloaded=VALUES(actual_downloaded),client_uploaded=VALUES(client_uploaded),client_downloaded=VALUES(client_downloaded),active=VALUES(active),seeder=VALUES(seeder),immune=VALUES(immune),seedtime=VALUES(seedtime),updated_at=VALUES(updated_at),completed_at=VALUES(completed_at),state_version=VALUES(state_version),swarm_updated_at=VALUES(swarm_updated_at)");
    q.build().execute(&mut *tx).await?;
    for (table, fields, deltas) in [
        ("users",vec!["uploaded","downloaded"], user_deltas.into_iter().map(|(id,values)| (id,values.iter().map(ToString::to_string).collect::<Vec<_>>())).collect::<BTreeMap<_,_>>()),
        ("torrents",vec!["seeders","leechers","seeders_ipv4","seeders_ipv6","leechers_ipv4","leechers_ipv6","times_completed","balance"],torrent_deltas.into_iter().map(|(id,values)| (id,values.iter().map(ToString::to_string).collect::<Vec<_>>())).collect())] {
        let mut q = QueryBuilder::<MySql>::new(format!("UPDATE {table} SET "));
        for (index,field) in fields.iter().enumerate() {
            if index != 0 { q.push(","); }
            q.push(format!("{field}={field}+CASE id"));
            for (id,values) in &deltas { q.push(" WHEN ").push_bind(*id).push(" THEN CAST(").push_bind(values[index].clone()).push(" AS DECIMAL(30,0))"); }
            q.push(" ELSE 0 END");
        }
        q.push(" WHERE id IN ("); { let mut ids=q.separated(","); for id in deltas.keys() { ids.push_bind(*id); } } q.push(")");
        q.build().execute(&mut *tx).await?;
    }
    tx.commit().await?;
    Ok(applied)
}
