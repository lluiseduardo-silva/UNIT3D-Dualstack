<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use App\Models\User;
use Illuminate\Pagination\LengthAwarePaginator;
use Illuminate\Support\Collection;

final class ProfileClients
{
    public static function get(User $user, User $viewer): Collection|LengthAwarePaginator
    {
        if (!$viewer->is($user) && !$viewer->group->is_modo) {
            return collect();
        }

        $query = $user->peers()->join('torrents', 'torrents.id', '=', 'peers.torrent_id')
            ->where('peers.active', true);

        if (!config('dualstack.enabled')) {
            return $query->select('agent', 'port')->selectRaw('INET6_NTOA(peers.ip) AS ip')
                ->selectRaw('MIN(peers.created_at) AS created_at, MAX(peers.updated_at) AS updated_at')
                ->selectRaw('SUM(torrents.size) AS size, COUNT(*) AS num_peers, MAX(peers.connectable) AS connectable')
                ->groupBy(['ip', 'port', 'agent'])->get();
        }

        $page = $query->select(['peers.user_id', 'peers.torrent_id', 'peers.peer_id', 'peers.agent',
            'peers.created_at', 'peers.updated_at', 'torrents.name as torrent_name', 'torrents.size'])
            ->whereExists(fn ($endpoint) => $endpoint->selectRaw('1')->from('peer_ips')
                ->whereColumn('peer_ips.user_id', 'peers.user_id')
                ->whereColumn('peer_ips.torrent_id', 'peers.torrent_id')
                ->whereColumn('peer_ips.peer_id', 'peers.peer_id')
                ->where('last_announced_at', '>', now()->subSeconds((int) config('dualstack.endpoint_ttl'))))
            ->orderByDesc('peers.updated_at')->orderBy('peers.torrent_id')->orderBy('peers.peer_id')
            ->paginate(25, ['*'], 'clientsPage')->withQueryString();
        EndpointView::load($page->getCollection());

        return $page;
    }
}
