//! Um escritor supervisionado: renovacao nunca disputa o fence do proprio lote.
use std::{future::Future, sync::atomic::Ordering, time::{Duration, Instant}};
use tokio::sync::watch;

use super::coordinator::{Coordinator, Error};

const RECOVERY_LIMIT: Duration = Duration::from_secs(120);
const RENEW_INTERVAL: Duration = Duration::from_secs(5);
const FLUSH_INTERVAL: Duration = Duration::from_millis(100);

// Estes erros permitem tentar a MESMA geracao. Unavailable/Version nunca permitem.
fn transient(error: &Error) -> bool {
    error.retryable() || matches!(error, Error::Timeout("renovacao da lease"))
}

/// Fechar entrada nao cancela SQL/commit. A future conserva seu proprio timeout.
async fn observe<T>(c: &Coordinator, stop: &mut watch::Receiver<bool>, work: impl Future<Output=Result<T,Error>>) -> Result<T,Error> {
    let deadline=c.state.lock().deadline;
    tokio::pin!(work);
    tokio::select! {
        result=&mut work => result,
        _=tokio::time::sleep_until(deadline.into()) => {
            c.pause_input();
            work.await
        },
        _=stop.changed() => {
            c.close_input();
            work.await
        },
    }
}

pub(super) async fn run(c: &Coordinator, mut stop: watch::Receiver<bool>) -> Result<(),Error> {
    let mut renew_at=Instant::now();
    let mut flush_at=Instant::now();
    let mut expire_at=Instant::now();
    let mut delete_at=Instant::now();
    let mut retire_at=Instant::now();
    let mut burst=Instant::now();
    let mut phase=0;
    let mut recovering: Option<Instant>=None;
    let mut stopping: Option<Instant>=None;
    loop {
        if *stop.borrow_and_update() || stop.has_changed().is_err() { c.close_input(); }
        let closed=c.input_closed.load(Ordering::Relaxed);
        if closed { stopping.get_or_insert_with(Instant::now); }
        if stopping.is_some_and(|at| at.elapsed()>=RECOVERY_LIMIT) { return Err(Error::Timeout("encerramento")); }
        if recovering.is_some_and(|at| at.elapsed()>=RECOVERY_LIMIT) { return Err(Error::Timeout("recuperacao")); }
        // Inclui o watchdog local vencido enquanto SQL estava em andamento.
        let paused={let state=c.state.lock(); !state.ready || Instant::now()>=state.deadline};
        if paused && !closed && recovering.is_none() {
            c.pause_input();
            recovering=Some(Instant::now());
            renew_at=Instant::now();
            tracing::warn!(generation=c.generation(), pending=c.backlog(), "Persistencia pausada; aguardando confirmacao da mesma lease");
        }
        if Instant::now()>=renew_at {
            match observe(c,&mut stop,c.renew()).await {
                Ok(()) => renew_at=Instant::now()+RENEW_INTERVAL,
                Err(error) if transient(&error) => {
                    c.pause_input();
                    recovering.get_or_insert_with(Instant::now);
                    c.record_retry(&error);
                    tracing::warn!(generation=c.generation(), pending=c.backlog(), error=%error, "Renovacao transitoria; entrada permanece fechada");
                    tokio::time::sleep(Duration::from_millis(200)).await;
                    continue;
                },
                Err(error) => return Err(error),
            }
        }
        if c.input_closed.load(Ordering::Relaxed) { stopping.get_or_insert_with(Instant::now); }
        if recovering.is_some() && c.backlog()==0 && stopping.is_none() {
            let mut state=c.state.lock();
            // close_input e reabertura usam o mesmo mutex: parada nunca e revertida.
            if !c.input_closed.load(Ordering::Relaxed) && Instant::now()<state.deadline {
                state.ready=true;
                recovering=None;
                tracing::info!(generation=c.generation(), "Persistencia recuperada; journal drenado e entrada reaberta");
            }
        }
        if stopping.is_some() && c.backlog()==0 {
            if observe(c,&mut stop,c.remove_deleted()).await? { continue; }
            return observe(c,&mut stop,c.lease.release(&c.pool)).await;
        }
        if recovering.is_some() || stopping.is_some() { phase=0; }
        match phase {
            0..=7 => {
                if recovering.is_none() && stopping.is_none() && c.backlog()<c.settings.batch_size && Instant::now()<flush_at {
                    tokio::select! {
                        _=tokio::time::sleep_until(flush_at.min(renew_at).into()) => {},
                        _=stop.changed() => c.close_input(),
                    }
                    continue;
                }
                if phase==0 { burst=Instant::now(); }
                match observe(c,&mut stop,c.flush_once()).await {
                    Ok(_) => {},
                    Err(error) if transient(&error) => {
                        c.pause_input();
                        recovering.get_or_insert_with(Instant::now);
                        // UPDATE da lease e uma barreira para qualquer commit incerto
                        // que ainda mantenha o fence S. Depois dele, replay e idempotente.
                        renew_at=Instant::now();
                        c.record_retry(&error);
                        tracing::warn!(generation=c.generation(), pending=c.backlog(), error=%error, "Lote pendente; confirmando propriedade antes do retry");
                        tokio::time::sleep(Duration::from_millis(200)).await;
                        continue;
                    },
                    Err(error) => return Err(error),
                }
                flush_at=Instant::now()+FLUSH_INTERVAL;
                phase=if c.backlog()<c.settings.batch_size || burst.elapsed()>=FLUSH_INTERVAL {8} else {phase+1};
                tokio::task::yield_now().await;
            },
            8 => {
                if Instant::now()>=expire_at {
                    let count=c.expire()?;
                    if count<c.settings.batch_size.min(c.settings.max_pending) { expire_at=Instant::now()+Duration::from_secs(60); }
                }
                phase=9;
            },
            9 => {
                if Instant::now()>=delete_at && !observe(c,&mut stop,c.remove_deleted()).await? { delete_at=Instant::now()+RENEW_INTERVAL; }
                phase=10;
            },
            _ => {
                if Instant::now()>=retire_at {
                    let count=observe(c,&mut stop,c.retire()).await?;
                    if count<c.settings.batch_size { retire_at=Instant::now()+Duration::from_secs(60); }
                }
                phase=0;
            },
        }
    }
}
