//! Remocao administrativa duravel, depois de confirmar o journal anterior ao fence.
use super::{
    coordinator::{Coordinator, Error, Identity},
    persistence,
};
use sqlx::{MySql, QueryBuilder, Row};
use std::{
    collections::{BTreeMap, BTreeSet},
    time::Duration,
};

struct Removal<'a> {
    coordinator: &'a Coordinator,
    completed: bool,
}
impl Drop for Removal<'_> {
    fn drop(&mut self) {
        if !self.completed {
            self.coordinator.close_input();
        }
    }
}

impl Coordinator {
    pub fn block_deleted_user(&self, id: u32) {
        self.state.lock().deleted_users.insert(id);
    }
    pub fn block_deleted_torrent(&self, id: u32) {
        self.state.lock().deleted_torrents.insert(id);
    }

    pub async fn remove_deleted(&self) -> Result<bool, Error> {
        let mut guard = Removal {
            coordinator: self,
            completed: false,
        };
        let result = tokio::time::timeout(Duration::from_secs(120), self.remove_deleted_inner())
            .await
            .map_err(|_| Error::Timeout("remocao"))??;
        guard.completed = true;
        Ok(result)
    }

    async fn remove_deleted_inner(&self) -> Result<bool, Error> {
        for (table, column) in [("users", "user_id"), ("torrents", "torrent_id")] {
            let id=sqlx::query_scalar::<_,u32>(&format!("SELECT id FROM {table} WHERE deleted_at IS NOT NULL AND tracker_removal_state<2 ORDER BY id LIMIT 1"))
                .fetch_optional(&self.pool).await?;
            let Some(id) = id else { continue };
            let barrier = {
                let mut state = self.state.lock();
                if table == "users" {
                    state.deleted_users.insert(id);
                } else {
                    state.deleted_torrents.insert(id);
                }
                state.sequence
            };
            // Novos announces de outros recursos podem continuar; fronteira finita.
            while self
                .state
                .lock()
                .pending
                .front()
                .is_some_and(|c| c.sequence <= barrier)
            {
                self.renew().await?;
                self.flush().await?;
            }
            let _writer = self.writer.lock().await;
            let mut tx = self.pool.begin().await?;
            self.lease.fence(&mut tx).await?;
            let deleted = sqlx::query_scalar::<_, i64>(&format!(
                "SELECT deleted_at IS NOT NULL FROM {table} WHERE id=? FOR UPDATE"
            ))
            .bind(id)
            .fetch_optional(&mut *tx)
            .await?;
            if deleted != Some(1) {
                return Err(Error::StoredState);
            }
            sqlx::query(&format!(
                "UPDATE {table} SET tracker_removal_state=1 WHERE id=? AND tracker_removal_state=0"
            ))
            .bind(id)
            .execute(&mut *tx)
            .await?;
            tx.commit().await?;
            let (peers, groups) = self.delete_entity_batch(table, column, id).await?;
            let mut state = self.state.lock();
            for identity in peers {
                state.peers.remove(&identity);
                state.retiring.remove(&identity);
                if let Some(ids) = state.leechers.get_mut(&identity.user_id) {
                    ids.remove(&identity);
                    if ids.is_empty() {
                        state.leechers.remove(&identity.user_id);
                    }
                }
            }
            for group in groups {
                state.groups.remove(&group);
            }
            return Ok(true);
        }
        Ok(false)
    }

    async fn delete_entity_batch(
        &self,
        table: &str,
        column: &str,
        id: u32,
    ) -> Result<(Vec<Identity>, Vec<(u32, u32)>), Error> {
        let mut tx = self.pool.begin().await?;
        self.lease.fence(&mut tx).await?;
        let rows=sqlx::query(&format!("SELECT user_id,torrent_id,peer_id FROM peers WHERE {column}=? ORDER BY user_id,torrent_id,peer_id LIMIT 200"))
            .bind(id).fetch_all(&mut *tx).await?;
        let identities: Vec<_> = rows
            .iter()
            .map(|r| {
                Ok(Identity {
                    user_id: r.try_get("user_id")?,
                    torrent_id: r.try_get("torrent_id")?,
                    peer_id: r
                        .try_get::<Vec<u8>, _>("peer_id")?
                        .try_into()
                        .map_err(|_| Error::StoredState)?,
                })
            })
            .collect::<Result<_, Error>>()?;
        if identities.is_empty() {
            let groups:Vec<(u32,u32)>=sqlx::query_as(&format!("SELECT user_id,torrent_id FROM history WHERE {column}=? ORDER BY user_id,torrent_id LIMIT 200 FOR UPDATE"))
                .bind(id).fetch_all(&mut *tx).await?;
            if groups.is_empty() {
                sqlx::query(&format!(
                    "UPDATE {table} SET tracker_removal_state=2 WHERE id=?"
                ))
                .bind(id)
                .execute(&mut *tx)
                .await?;
            } else {
                let mut q = QueryBuilder::<MySql>::new(
                    "DELETE FROM history WHERE (user_id,torrent_id) IN (",
                );
                {
                    let mut s = q.separated(",");
                    for (user, torrent) in &groups {
                        s.push("(")
                            .push_bind_unseparated(*user)
                            .push_unseparated(",")
                            .push_bind_unseparated(*torrent)
                            .push_unseparated(")");
                    }
                }
                q.push(")").build().execute(&mut *tx).await?;
            }
            tx.commit().await?;
            return Ok((identities, groups));
        }
        for (parent, ids) in [
            (
                "users",
                identities
                    .iter()
                    .map(|i| i.user_id)
                    .collect::<BTreeSet<_>>(),
            ),
            (
                "torrents",
                identities.iter().map(|i| i.torrent_id).collect(),
            ),
        ] {
            let mut q =
                QueryBuilder::<MySql>::new(format!("SELECT id FROM {parent} WHERE id IN ("));
            {
                let mut s = q.separated(",");
                for id in ids {
                    s.push_bind(id);
                }
            }
            q.push(") ORDER BY id FOR UPDATE")
                .build()
                .fetch_all(&mut *tx)
                .await?;
        }
        let connectivity = if self.settings.require_connectivity {
            " AND e.connectable=1"
        } else {
            ""
        };
        let exists = |family| {
            format!(
                "EXISTS(SELECT 1 FROM peer_ips e WHERE e.user_id=p.user_id AND e.torrent_id=p.torrent_id AND e.peer_id=p.peer_id AND e.family={family}{connectivity})"
            )
        };
        let mut q = QueryBuilder::<MySql>::new(format!(
            "SELECT p.torrent_id,p.active,p.visible,p.seeder,{} AS v4,{} AS v6 FROM peers p WHERE (p.user_id,p.torrent_id,p.peer_id) IN (",
            exists(4),
            exists(6)
        ));
        persistence::peer_tuples(&mut q, identities.iter().copied());
        q.push(") ORDER BY p.user_id,p.torrent_id,p.peer_id FOR UPDATE");
        let mut deltas = BTreeMap::<u32, [i64; 6]>::new();
        for row in q.build().fetch_all(&mut *tx).await? {
            let v4 = row.try_get::<i64, _>("v4")? != 0;
            let v6 = row.try_get::<i64, _>("v6")? != 0;
            if row.try_get::<bool, _>("active")? && row.try_get::<bool, _>("visible")? && (v4 || v6)
            {
                let seed = row.try_get::<bool, _>("seeder")?;
                let delta = deltas.entry(row.try_get("torrent_id")?).or_default();
                for (index, value) in [
                    seed,
                    !seed,
                    seed && v4,
                    seed && v6,
                    !seed && v4,
                    !seed && v6,
                ]
                .iter()
                .enumerate()
                {
                    delta[index] += i64::from(*value);
                }
            }
        }
        if !deltas.is_empty() {
            let mut q = QueryBuilder::<MySql>::new("UPDATE torrents SET ");
            for (index, field) in [
                "seeders",
                "leechers",
                "seeders_ipv4",
                "seeders_ipv6",
                "leechers_ipv4",
                "leechers_ipv6",
            ]
            .iter()
            .enumerate()
            {
                if index != 0 {
                    q.push(",");
                }
                q.push(format!("{field}={field}-CASE id"));
                for (id, values) in &deltas {
                    q.push(" WHEN ")
                        .push_bind(*id)
                        .push(" THEN ")
                        .push_bind(values[index]);
                }
                q.push(" ELSE 0 END");
            }
            q.push(" WHERE id IN (");
            {
                let mut s = q.separated(",");
                for id in deltas.keys() {
                    s.push_bind(*id);
                }
            }
            q.push(")").build().execute(&mut *tx).await?;
        }
        let mut q =
            QueryBuilder::<MySql>::new("DELETE FROM peers WHERE (user_id,torrent_id,peer_id) IN (");
        persistence::peer_tuples(&mut q, identities.iter().copied());
        q.push(")").build().execute(&mut *tx).await?;
        tx.commit().await?;
        Ok((identities, vec![]))
    }
}
