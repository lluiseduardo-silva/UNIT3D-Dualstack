use anyhow::{Context, Result, bail};
use axum::Router;
use dotenvy::dotenv;
use std::net::SocketAddr;
use tokio::{
    net::{TcpListener, UnixListener},
    signal,
};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[cfg(not(target_env = "msvc"))]
use tikv_jemallocator::Jemalloc;

#[cfg(not(target_env = "msvc"))]
#[global_allocator]
static GLOBAL: Jemalloc = Jemalloc;

mod announce;
mod api;
mod config;
mod error;
mod model;
mod queue;
mod rate;
mod routes;
mod scheduler;
mod state;
mod stats;
mod store;
mod utils;
mod warning;
mod dualstack_network;

#[tokio::main]
async fn main() -> Result<()> {
    let _ = dotenv().context(".env file not found.")?;

    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| format!("{}=trace", env!("CARGO_CRATE_NAME")).into()),
        )
        .with(
            tracing_subscriber::fmt::layer()
                .with_ansi(false)
                .with_level(false)
                .with_target(false),
        )
        .init();

    // The state struct keeps track of all state within the application.
    let state = state::AppState::default().await?;
    let (stop, receiver) = tokio::sync::watch::channel(false);

    // Starts scheduler to automate flushing updates
    // to database and inactive peer removal.
    let mut scheduler = tokio::spawn({
        let state = state.clone();
        let receiver = receiver.clone();

        async move {
            scheduler::handle(&state, receiver).await;
        }
    });

    // Create router.
    let app = Router::new()
        .merge(routes::routes(state.clone()))
        .with_state(state.clone());

    // Ensure lock is dropped before axum::serve() is called otherwise
    // reloading config triggers a deadlock
    let config = state.config.load().clone();

    let signal = tokio::spawn({
        let stop = stop.clone();
        let coordinator = state.dualstack.clone();
        async move {
            shutdown_signal().await;
            if let Some(coordinator) = coordinator { coordinator.close_input(); }
            let _ = stop.send(true);
        }
    });
    let server = serve(app, config, receiver.clone());
    tokio::pin!(server);
    let result = if let Some(coordinator) = &state.dualstack {
        let worker = coordinator.run(receiver);
        tokio::pin!(worker);
        tokio::select! {
            result = &mut server => {
                coordinator.close_input();
                let _ = stop.send(true);
                let drained = worker.await.map_err(|error| anyhow::anyhow!("Coordenador dualstack: {error}"));
                result.and(drained)
            },
            result = &mut worker => {
                coordinator.close_input();
                let _ = stop.send(true);
                let stopped = tokio::time::timeout(std::time::Duration::from_secs(10), &mut server)
                    .await.context("Tempo limite encerrando HTTP")?;
                result.map_err(|error| anyhow::anyhow!("Coordenador dualstack: {error}")).and(stopped)
            },
        }
    } else { server.await };
    signal.abort();
    let _ = stop.send(true);
    if tokio::time::timeout(std::time::Duration::from_secs(30), &mut scheduler).await.is_err() {
        scheduler.abort();
        bail!("Tempo limite encerrando scheduler");
    }
    result?;

    // Flush only remaining legacy/diagnostic queues after their producer stops.
    let max_flushes = 1000;
    let mut flushes = 0;
    while flushes < max_flushes && state.queues.are_not_empty() {
        state.queues.flush(&state).await;
        flushes += 1;
    }
    if flushes == max_flushes { bail!("Graceful shutdown failed"); }
    println!("Graceful shutdown succeeded");
    Ok(())
}

async fn serve(app: Router, config: std::sync::Arc<config::Config>, mut stop: tokio::sync::watch::Receiver<bool>) -> Result<()> {
    let stopping = async move {
        while !*stop.borrow_and_update() {
            if stop.changed().await.is_err() { break; }
        }
    };
    if let Some(path) = config.listening_unix_socket.to_owned() {
        // Create unix domain socket.
        let _ = tokio::fs::remove_file(&path).await;
        tokio::fs::create_dir_all(path.parent().unwrap()).await?;

        let listener = UnixListener::bind(path.clone())?;

        // Start handling announces.
        println!("UNIT3D Announce has started.");

        axum::serve(listener, app)
            .with_graceful_shutdown(stopping)
            .await?;
    } else if let Some(ip) = config.listening_ip_address
        && let Some(port) = config.listening_port
    {
        // Create TCP socket.
        let addr = SocketAddr::from((ip, port));

        let listener = TcpListener::bind(addr).await?;

        // Start handling announces.
        println!("UNIT3D Announce has started.");

        let app = app.into_make_service_with_connect_info::<SocketAddr>();

        axum::serve(listener, app)
            .with_graceful_shutdown(stopping)
            .await?;
    } else {
        bail!("Listener not configured.");
    }

    Ok(())
}

/// This future completes when shutdown signal is received.
async fn shutdown_signal() {
    let ctrl_c = async {
        signal::ctrl_c()
            .await
            .expect("Failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        signal::unix::signal(signal::unix::SignalKind::terminate())
            .expect("Failed to install signal handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }

    println!("\nSignal received, starting graceful shutdown");
}
