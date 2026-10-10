//! Retira somente referencias confirmadas. I/O ocorre fora do mutex do swarm.
use std::{
    collections::BTreeSet,
    time::{Duration, Instant},
};

use super::{
    coordinator::{Coordinator, Error, Identity},
    persistence,
};

// Cancelamento tambem deixa resultado SQL incerto. So um novo bootstrap pode
// reabrir a entrada; nao reutiliza uma referencia que talvez tenha sido apagada.
struct Retirement<'a> {
    coordinator: &'a Coordinator,
    committed: bool,
}
impl Drop for Retirement<'_> {
    fn drop(&mut self) {
        if !self.committed {
            self.coordinator.close_input();
        }
    }
}

impl Coordinator {
    #[doc(hidden)]
    pub fn is_retiring(&self, identity: Identity) -> bool {
        self.state.lock().retiring.contains(&identity)
    }

    pub async fn retire(&self) -> Result<usize, Error> {
        self.retire_at(self.now()).await
    }

    #[doc(hidden)]
    pub async fn retire_at(&self, now: u64) -> Result<usize, Error> {
        // Mesmo escritor dos lotes: fila sem a identidade significa SQL confirmado.
        let _writer = self.writer.lock().await;
        let cutoff = now.saturating_sub(self.settings.inactive_retention);
        let candidates = {
            let mut state = self.state.lock();
            if !state.ready || Instant::now() >= state.deadline {
                return Err(Error::Unavailable);
            }
            let pending: BTreeSet<_> = state.pending.iter().map(|c| c.identity).collect();
            let candidates: Vec<_> = state
                .peers
                .iter()
                .filter(|(id, peer)| {
                    !peer.active
                        && peer.endpoints.is_empty()
                        && peer.updated_at < cutoff
                        && !pending.contains(id)
                        && !state.retiring.contains(id)
                })
                .take(self.settings.batch_size)
                .map(|(id, peer)| (*id, peer.state_version))
                .collect();
            // Somente essas identidades ficam temporariamente indisponiveis.
            state.retiring.extend(candidates.iter().map(|(id, _)| *id));
            candidates
        };
        if candidates.is_empty() {
            return Ok(0);
        }
        let mut guard = Retirement {
            coordinator: self,
            committed: false,
        };
        tokio::time::timeout(
            Duration::from_secs(15),
            persistence::retire(&self.pool, &self.lease, &candidates, cutoff),
        )
        .await
        .map_err(|_| Error::Timeout("retencao"))??;
        {
            let mut state = self.state.lock();
            for (identity, _) in &candidates {
                state.peers.remove(identity);
                state.retiring.remove(identity);
            }
            // A versao/conclusao do historico permanece para uma reconexao futura.
        }
        guard.committed = true;
        Ok(candidates.len())
    }
}
