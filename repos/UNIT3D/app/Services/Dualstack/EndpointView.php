<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Query\Builder as Query;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;

/** Leitura paginada com identidade composta e uma consulta de endpoints. */
final class EndpointView
{
    private static function related(): Query
    {
        return DB::table('peer_ips as endpoint')->whereColumn('endpoint.user_id', 'peers.user_id')
            ->whereColumn('endpoint.torrent_id', 'peers.torrent_id')->whereColumn('endpoint.peer_id', 'peers.peer_id');
    }

    public static function selectNetwork(Builder $query): void
    {
        if (config('dualstack.enabled')) {
            // Valores de ordenacao; a view exibe a colecao completa da pagina.
            $query->addSelect(['ip' => self::related()->selectRaw('MIN(INET6_NTOA(endpoint.ip))'),
                'port'              => self::related()->selectRaw('MIN(endpoint.port)')]);
        } else {
            $query->addSelect('peers.port')->selectRaw('INET6_NTOA(peers.ip) AS ip');
        }
    }

    public static function filterNetwork(Builder $query, string $ip, string $port): void
    {
        if (config('dualstack.enabled')) {
            if ($ip !== '' || $port !== '') {
                $query->whereExists(self::related()->selectRaw('1')
                    ->when($ip !== '', fn ($q) => $q->whereRaw('endpoint.ip = INET6_ATON(?)', [$ip]))
                    ->when($port !== '', fn ($q) => $q->where('endpoint.port', $port)));
            }
        } else {
            $query->when($ip !== '', fn ($q) => $q->whereRaw('peers.ip = INET6_ATON(?)', [$ip]))
                ->when($port !== '', fn ($q) => $q->where('peers.port', $port));
        }
    }

    /** @param Collection<int, \App\Models\Peer> $peers */
    public static function load(Collection $peers): void
    {
        if (!config('dualstack.enabled') || $peers->isEmpty()) {
            return;
        }
        $key = fn ($row) => $row->user_id.':'.$row->torrent_id.':'.bin2hex($row->peer_id);
        $endpoints = TransitionWriter::tuples(
            'peer_ips',
            ['user_id', 'torrent_id', 'peer_id'],
            $peers->map(fn ($peer) => [$peer->user_id, $peer->torrent_id, $peer->peer_id])->all()
        )
            ->select(['user_id', 'torrent_id', 'peer_id', 'family', 'port', 'connectable', 'last_announced_at'])
            ->selectRaw('INET6_NTOA(ip) AS ip_address')->orderBy('family')->get();
        $cutoff = now()->subSeconds((int) config('dualstack.endpoint_ttl'))->format('Y-m-d H:i:s');

        foreach ($endpoints as $endpoint) {
            $endpoint->current = $endpoint->last_announced_at > $cutoff;
            $endpoint->connectable = $endpoint->connectable === null ? null : (bool) $endpoint->connectable;
        }
        $grouped = $endpoints->groupBy($key);

        foreach ($endpoints as $endpoint) {
            unset($endpoint->user_id, $endpoint->torrent_id, $endpoint->peer_id);
        }

        foreach ($peers as $peer) {
            $peer->setRelation('endpoints', $grouped->get($key($peer), collect()));
            $peer->makeHidden('peer_id');
        }
    }
}
