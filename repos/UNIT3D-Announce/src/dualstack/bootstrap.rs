//! Conexoes reservadas ate o fim da carga ou confirmacao do cancelamento no MySQL.
use std::time::Duration;

use sqlx::{Executor, MySqlConnection, MySqlPool};
use tokio::{sync::oneshot, time::{Instant, timeout, timeout_at}};

use super::{coordinator::{Error, Settings, Swarm}, persistence::{self, Lease}};

pub(crate) async fn load(pool: &MySqlPool, lease: &Lease, settings: Settings, limit: Duration) -> Result<Swarm, Error> {
    let deadline=Instant::now()+limit;
    let mut work=timeout_at(deadline,pool.acquire()).await.map_err(|_|Error::Timeout("bootstrap"))??;
    work.close_on_drop();
    let mut control=timeout_at(deadline,pool.acquire()).await.map_err(|_|Error::Timeout("bootstrap"))??;
    control.close_on_drop();
    let id:u64=timeout_at(deadline,sqlx::query_scalar("SELECT CONNECTION_ID()").fetch_one(&mut *work))
        .await.map_err(|_|Error::Timeout("bootstrap"))??;
    let (finished,signal)=oneshot::channel::<()>();
    let owner=lease.clone();
    // O drop da future chamadora fecha o canal. A limpeza continua no runtime,
    // conservando a conexao de controle, sem disputar capacidade livre no pool.
    let cleanup=tokio::spawn(async move {
        if signal.await.is_ok() {return Ok(());}
        let result=timeout(Duration::from_secs(5),terminate(&mut control,id)).await;
        if !matches!(result,Ok(Ok(()))) {
            tracing::error!(connection_id=id,"Cancelamento do bootstrap nao confirmado no MySQL; propriedade nao liberada");
            return Err(Error::BootstrapCancellation);
        }
        // KILL CONNECTION so sinaliza a interrupcao. terminate aguarda a saida
        // do servidor; liberar a lease antes disso permitiria sobrepor geracoes.
        owner.release_on(&mut control).await?;
        Ok(())
    });
    let result=timeout_at(deadline,persistence::load(&mut work,pool,lease,settings))
        .await.unwrap_or(Err(Error::Timeout("bootstrap")));
    if result.is_ok() {let _=finished.send(());} else {drop(finished);}
    cleanup.await.map_err(|_|Error::BootstrapCancellation)??;
    result
}

async fn terminate(control: &mut MySqlConnection, id: u64) -> Result<(), Error> {
    // ID numerico obtido na propria conexao, nunca fornecido pelo cliente.
    let statement=format!("KILL CONNECTION {id}");
    if let Err(error)=control.execute(statement.as_str()).await {
        let absent=matches!(&error,sqlx::Error::Database(e) if e.try_downcast_ref::<sqlx::mysql::MySqlDatabaseError>()
            .is_some_and(|e|e.number()==1094));
        if !absent {return Err(error.into());}
    }
    loop {
        let remaining:i64=sqlx::query_scalar("SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID=?")
            .bind(id).fetch_one(&mut *control).await?;
        if remaining==0 {return Ok(());}
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}
