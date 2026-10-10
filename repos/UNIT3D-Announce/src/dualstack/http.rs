//! Adaptador HTTP para o coordenador; filas financeiras legadas nao sao usadas.
use super::*;
use unit3d_announce::dualstack::{
    coordinator::{Credit, Error, Identity},
    peer::{self as logical, Operation, Outcome, Rejection},
    response::ListRequest,
};

pub(super) async fn handle(
    state: &Arc<AppState>,
    queries: &Announce,
    user: Result<store::user::User, AnnounceError>,
    torrent_id: u32,
    user_agent: &str,
    ip: IpAddr,
) -> Result<Vec<u8>, AnnounceError> {
    let user = user?;
    let config = state.config.load().clone();
    let torrent = state
        .stores
        .torrents
        .lock()
        .get(&torrent_id)
        .cloned()
        .ok_or(TorrentNotFound)?;
    if torrent.is_deleted {
        return Err(TorrentIsDeleted);
    }
    match torrent.status {
        TorrentStatus::Approved => (),
        TorrentStatus::Pending => return Err(TorrentIsPendingModeration),
        TorrentStatus::Rejected => return Err(TorrentIsRejected),
        TorrentStatus::Postponed => return Err(TorrentIsPostponed),
        _ => return Err(TorrentUnknownModerationStatus),
    }
    if !user.can_download && queries.left != 0 {
        return Err(DownloadPrivilegesRevoked);
    }
    let group = state
        .stores
        .groups
        .read()
        .get(&user.group_id)
        .cloned()
        .ok_or(GroupNotFound)?;
    if ["banned", "validating", "disabled"].contains(&group.slug.as_str()) {
        return Err(GroupNotEnabled(group.slug));
    }
    let mut upload = config
        .upload_factor
        .max(group.upload_factor)
        .max(torrent.upload_factor);
    let mut download = config
        .download_factor
        .min(group.download_factor)
        .min(torrent.download_factor);
    let mut immune = group.is_immune;
    let overrides = if user.is_lifetime {
        (
            config.lifetime_donor_upload_factor_override,
            config.lifetime_donor_download_factor_override,
            config.lifetime_donor_immunity_override,
        )
    } else if user.is_donor {
        (
            config.donor_upload_factor_override,
            config.donor_download_factor_override,
            config.donor_immunity_override,
        )
    } else {
        (None, None, None)
    };
    if let Some(value) = overrides.0 {
        upload = upload.max(value);
    }
    if let Some(value) = overrides.1 {
        download = download.min(value);
    }
    if let Some(value) = overrides.2 {
        immune = value;
    }
    let featured = state
        .stores
        .featured_torrents
        .read()
        .contains(&FeaturedTorrent { torrent_id });
    if featured {
        upload = 200;
    }
    if featured
        || state
            .stores
            .personal_freeleeches
            .read()
            .contains(&PersonalFreeleech { user_id: user.id })
        || state
            .stores
            .freeleech_tokens
            .read()
            .contains(&FreeleechToken {
                user_id: user.id,
                torrent_id,
            })
    {
        download = 0;
    }
    let event = match queries.event {
        Event::Empty => logical::Event::Empty,
        Event::Started => logical::Event::Started,
        Event::Stopped => logical::Event::Stopped,
        Event::Completed => logical::Event::Completed,
    };
    let identity = Identity {
        user_id: user.id,
        torrent_id,
        peer_id: queries.peer_id.0,
    };
    let coordinator = state.dualstack.as_ref().ok_or(InternalTrackerError)?;
    let result = coordinator
        .publish(
            identity,
            Operation::Announce(logical::Announce {
                event,
                ip,
                port: queries.port,
                uploaded: queries.uploaded,
                downloaded: queries.downloaded,
                left: queries.left,
                visible: true,
                agent: user_agent.into(),
            }),
            Credit {
                upload_percent: upload.into(),
                download_percent: download.into(),
                immune,
            },
            group.download_slots.map(|n| n as usize),
        )
        .map_err(|error| match error {
            Error::PeerLimit => PeersPerTorrentPerUserLimit(config.max_peers_per_torrent_per_user),
            Error::Transition(logical::TransitionError::InvalidPort) => InvalidPort,
            _ => AnnounceError::TrackerUnavailable,
        })?;
    if result.reason == Some(Rejection::EndpointLimit) {
        return Err(AnnounceError::EndpointLimit);
    }
    let mut warning = None;
    let limited = result.reason == Some(Rejection::Interval);
    if let Some(peer) = result.peer.as_ref() {
        if !peer.visible {
            warning = Some("Download slot limit reached");
        }
        if result.outcome == Outcome::Accepted
            && event != logical::Event::Stopped
            && config.is_connectivity_check_enabled
        {
            if let Some(endpoint) = peer.endpoints.get(logical::Family::of(ip)) {
                if let Some(connectable) = state
                    .dualstack_probes
                    .check(
                        SocketAddr::new(endpoint.ip, endpoint.port),
                        config.dualstack_connectivity_cache_entries,
                        std::time::Duration::from_secs(config.dualstack_connectivity_cache_ttl),
                    )
                    .await
                {
                    // Revisao, IP e porta protegem contra resultados atrasados.
                    let _ = coordinator.publish(
                        identity,
                        Operation::Probe {
                            ip: endpoint.ip,
                            port: endpoint.port,
                            revision: endpoint.revision,
                            connectable,
                        },
                        Credit::default(),
                        None,
                    );
                }
            }
        }
        if config.require_peer_connectivity
            && !coordinator.peer(identity).is_some_and(|p| p.connectable)
        {
            warning = Some("Connectivity issue detected. Enable port-forwarding to resolve.");
        }
    }
    let can_list =
        queries.event != Event::Stopped && !limited && warning.is_none() && queries.numwant > 0;
    let (seeds, leeches) = {
        let mut users = state.stores.users.write();
        let current = users.get_mut(&user.id).ok_or(UserNotFound)?;
        let seeds =
            can_list && queries.left > 0 && current.receive_seed_list_rates.is_under_limit();
        let leeches = can_list && current.receive_leech_list_rates.is_under_limit();
        if can_list && queries.left > 0 {
            current.receive_seed_list_rates.tick();
        }
        if can_list {
            current.receive_leech_list_rates.tick();
        }
        (seeds, leeches)
    };
    let list = coordinator
        .select(ListRequest {
            torrent_id,
            user_id: user.id,
            numwant: queries.numwant,
            seeds,
            leeches,
        })
        .map_err(|_| AnnounceError::TrackerUnavailable)?;
    let interval = rng().random_range(config.announce_min..=config.announce_max);
    if config.is_announce_logging_enabled {
        state.queues.announces.lock().upsert(AnnounceUpdate {
            user_id: user.id,
            torrent_id,
            uploaded: queries.uploaded,
            downloaded: queries.downloaded,
            left: queries.left,
            corrupt: queries.corrupt,
            peer_id: queries.peer_id,
            port: queries.port,
            numwant: queries.numwant.try_into().unwrap_or(u16::MAX),
            created_at: Utc::now(),
            event: queries.event,
            key: queries.key.clone(),
        });
    }
    state.stats.increment_announce_response();
    Ok(list.encode(list.completed, interval, config.announce_min, warning))
}
