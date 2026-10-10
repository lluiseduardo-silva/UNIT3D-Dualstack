use std::str::FromStr;
use std::sync::Arc;

use axum::extract::{Json, Path, State};
use axum::http::StatusCode;
use serde::Deserialize;
use tracing::info;

use anyhow::Result;

use crate::model::{info_hash::InfoHash, torrent_status::TorrentStatus};
use crate::state::AppState;
use crate::store::torrent::Torrent;

#[derive(Clone, Deserialize)]
pub struct APIInsertTorrent {
    pub id: u32,
    pub status: TorrentStatus,
    pub info_hash: String,
    pub is_deleted: bool,
    pub seeders: u32,
    pub leechers: u32,
    pub times_completed: u32,
    pub download_factor: u8,
    pub upload_factor: u8,
}

pub async fn upsert(
    State(state): State<Arc<AppState>>,
    Json(torrent): Json<APIInsertTorrent>,
) -> StatusCode {
    if let Ok(info_hash) = InfoHash::from_str(&torrent.info_hash) {
        info!("Inserting torrent with id {}.", torrent.id);
        if let Some(coordinator)=&state.dualstack {coordinator.register_torrent(torrent.id,torrent.times_completed.into());}
        let mut torrents=state.stores.torrents.lock();
        let old_torrent = torrents.swap_remove(&torrent.id);
        let peers = old_torrent.unwrap_or_default().peers;

        torrents.insert(
            torrent.id,
            Torrent {
                id: torrent.id,
                status: torrent.status,
                is_deleted: torrent.is_deleted,
                seeders: torrent.seeders,
                leechers: torrent.leechers,
                times_completed: torrent.times_completed,
                download_factor: torrent.download_factor,
                upload_factor: torrent.upload_factor,
                peers,
            },
        );
        drop(torrents);

        state
            .stores
            .infohash2id
            .write()
            .insert(info_hash, torrent.id);

        return StatusCode::OK;
    }

    StatusCode::BAD_REQUEST
}

#[derive(Clone, Deserialize)]
pub struct APIRemoveTorrent {
    pub id: u32,
}

pub async fn destroy(
    State(state): State<Arc<AppState>>,
    Json(torrent): Json<APIRemoveTorrent>,
) -> StatusCode {
    let mut torrent_guard = state.stores.torrents.lock();

    if let Some(torrent) = torrent_guard.get_mut(&torrent.id) {
        info!("Removing torrent with id {}.", torrent.id);
        if let Some(coordinator)=&state.dualstack {coordinator.block_deleted_torrent(torrent.id);}
        torrent.is_deleted = true;

        return StatusCode::OK;
    }

    StatusCode::BAD_REQUEST
}

pub async fn show(
    State(state): State<Arc<AppState>>,
    Path(id): Path<u32>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let torrent=state
        .stores
        .torrents
        .lock()
        .get(&id)
        .cloned().ok_or(StatusCode::NOT_FOUND)?;
    let mut result=serde_json::to_value(torrent).map_err(|_|StatusCode::INTERNAL_SERVER_ERROR)?;
    if let Some(coordinator)=&state.dualstack {
        let snapshot=serde_json::to_value(coordinator.torrent_snapshot(id)).map_err(|_|StatusCode::INTERNAL_SERVER_ERROR)?;
        result.as_object_mut().unwrap().extend(snapshot.as_object().unwrap().clone());
    }
    Ok(Json(result))
}
