<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use App\Models\Peer;
use Illuminate\Pagination\LengthAwarePaginator;
use Illuminate\Support\Facades\DB;

final class PeerSearchQuery
{
    public static function paginate(array $filters): LengthAwarePaginator
    {
        $cutoff = now()->subSeconds((int) config('dualstack.endpoint_ttl'))->format('Y-m-d H:i:s');
        $network = DB::table('peer_ips')->select(['user_id','torrent_id','peer_id'])
            ->selectRaw('MAX(last_announced_at > ?) AS live', [$cutoff])
            ->selectRaw('MAX(last_announced_at > ? AND connectable=1) AS positive', [$cutoff])
            ->selectRaw('MAX(last_announced_at > ? AND connectable IS NULL) AS unknown', [$cutoff])
            ->selectRaw('MIN(INET6_NTOA(ip)) AS ip, MIN(port) AS port')
            ->groupBy(['user_id','torrent_id','peer_id']);
        $rows = DB::table('peers as p')->join('torrents as t', 't.id', '=', 'p.torrent_id')
            ->whereNull('t.deleted_at')
            ->whereExists(fn ($q) => $q->selectRaw('1')->from('users as u')->whereColumn('u.id', 'p.user_id')->whereNull('u.deleted_at'))
            ->leftJoinSub($network, 'network', fn ($join) => self::joinIdentity($join, 'network', 'p'))
            ->select(['p.user_id','p.torrent_id','p.peer_id','p.agent','p.uploaded','p.downloaded','p.left','p.seeder','p.visible','p.created_at','p.updated_at','t.size','network.ip','network.port'])
            ->selectRaw('p.active AND COALESCE(network.live,0) AS active')
            ->selectRaw('CASE WHEN network.positive=1 THEN 1 WHEN COALESCE(network.live,0)=0 OR network.unknown=1 THEN NULL ELSE 0 END AS connectable');
        $logical = Peer::query()->fromSub($rows, 'peers');

        if ($filters['ip'] !== '' || $filters['port'] !== '' || $filters['sharedIpsOnly'] || $filters['sharedSocketsOnly']) {
            $matching = DB::table('peer_ips as e')->selectRaw('1')->whereColumn('e.user_id', 'peers.user_id')
                ->whereColumn('e.torrent_id', 'peers.torrent_id')->whereColumn('e.peer_id', 'peers.peer_id');
            self::matchEndpoints($matching, $filters);
            $logical->whereExists($matching);
        }
        $logical->when($filters['agent'] !== '', fn ($q) => $q->where('peers.agent', 'LIKE', $filters['agent'].'%'))
            ->when($filters['torrent'] !== '', fn ($q) => $q->whereRelation('torrent', 'name', 'LIKE', '%'.str_replace(' ', '%', $filters['torrent']).'%'))
            ->when($filters['connectivity'] === 'connectable', fn ($q) => $q->where('peers.connectable', true))
            ->when($filters['connectivity'] === 'unconnectable', fn ($q) => $q->where('peers.connectable', false))
            ->when($filters['connectivity'] === 'unknown', fn ($q) => $q->whereNull('peers.connectable'))
            ->when($filters['active'] === 'include', fn ($q) => $q->where('peers.active', true))
            ->when($filters['active'] === 'exclude', fn ($q) => $q->where('peers.active', false));
        $mode = \in_array($filters['groupBy'], ['user','user_ip','user_session'], true) ? $filters['groupBy'] : 'none';

        if ($mode === 'none') {
            $query = (clone $logical)->select('peers.*')->with(['user.group','torrent:id,name,size']);
        } else {
            $group = (clone $logical)->select('peers.user_id')->groupBy('peers.user_id');

            if ($mode === 'user_ip') {
                // Uma linha por peer e endereco; familias distintas formam grupos distintos.
                $group->join('peer_ips as e', fn ($join) => self::joinIdentity($join, 'e', 'peers'))
                    ->groupBy('e.ip')->selectRaw('INET6_NTOA(e.ip) AS ip, COUNT(DISTINCT e.port) AS port');
                self::matchEndpoints($group, $filters);
            } elseif ($mode === 'user_session') {
                $group->addSelect(['peers.agent','peers.peer_id'])->groupBy(['peers.agent','peers.peer_id']);
            }

            if ($mode !== 'user_session') {
                $group->selectRaw('COUNT(DISTINCT peers.agent) AS agent');
            }
            $group->selectRaw('COUNT(*) AS peer_count, COUNT(DISTINCT peers.torrent_id) AS torrent_id')
                ->selectRaw('SUM(peers.uploaded) AS uploaded, SUM(peers.downloaded) AS downloaded, SUM(peers.`left`) AS `left`')
                ->selectRaw('MIN(peers.created_at) AS created_at, MAX(peers.updated_at) AS updated_at')
                ->selectRaw('COALESCE(SUM(peers.connectable=1),0) AS connectable_count, COALESCE(SUM(peers.connectable=0),0) AS unconnectable_count, SUM(peers.connectable IS NULL) AS unknown_count')
                ->selectRaw('SUM(peers.active=1) AS active_count, SUM(peers.active=0) AS inactive_count')
                ->selectRaw('ROUND(COALESCE(SUM(peers.active=0)/NULLIF(SUM(peers.active=1),0),0),2) AS inactive_ratio')
                ->selectRaw('SUM(peers.size) AS size, SUM(CASE WHEN peers.connectable=1 THEN peers.size ELSE 0 END) AS connectable_size, SUM(CASE WHEN peers.connectable=0 THEN peers.size ELSE 0 END) AS unconnectable_size');
            $query = Peer::query()->fromSub($group->toBase(), 'peers')->select('peers.*')->with('user.group');

            if ($mode !== 'user_ip') {
                $endpoints = DB::table('peer_ips as e')->joinSub((clone $logical)->select('peers.*')->toBase(), 'matched', fn ($join) => self::joinIdentity($join, 'e', 'matched'))
                    ->whereColumn('e.user_id', 'peers.user_id');

                if ($mode === 'user_session') {
                    $endpoints->whereColumn('matched.agent', 'peers.agent')->whereColumn('matched.peer_id', 'peers.peer_id');
                }
                $query->addSelect(['ip' => (clone $endpoints)->selectRaw('COUNT(DISTINCT e.ip)'),
                    'port'              => (clone $endpoints)->selectRaw('COUNT(DISTINCT e.port)')]);
            }
        }
        $allowed = ['peers.user_id','user_id','torrent_id','agent','ip','port','uploaded','downloaded','left','created_at','updated_at','size'];
        $allowed = array_merge($allowed, $mode === 'none' ? ['active','connectable'] : ['peer_count','connectable_count','unconnectable_count','unknown_count','active_count','inactive_count','inactive_ratio','connectable_size','unconnectable_size']);
        $sort = \in_array($filters['sortField'], $allowed, true) ? $filters['sortField'] : 'created_at';
        $query->orderBy($sort, $filters['sortDirection'] === 'asc' ? 'asc' : 'desc')->orderBy('peers.user_id');

        if ($mode === 'none') {
            $query->orderBy('peers.torrent_id')->orderBy('peers.peer_id');
        }

        if ($mode === 'user_ip') {
            $query->orderBy('ip');
        }

        if ($mode === 'user_session') {
            $query->orderBy('peers.agent')->orderBy('peers.peer_id');
        }
        $page = $query->paginate(min(100, max(1, (int) $filters['perPage'])));

        if ($mode === 'none') {
            EndpointView::load($page->getCollection());
        }

        if ($mode === 'user_session') {
            $page->getCollection()->each(fn ($peer) => $peer->makeHidden('peer_id'));
        }

        return $page;
    }

    private static function joinIdentity($join, string $left, string $right): void
    {
        foreach (['user_id','torrent_id','peer_id'] as $column) {
            $join->on($left.'.'.$column, '=', $right.'.'.$column);
        }
    }

    private static function matchEndpoints($query, array $filters): void
    {
        if ($filters['ip'] !== '') {
            $query->where(fn ($q) => $q->whereRaw('INET6_NTOA(e.ip) LIKE ?', [$filters['ip'].'%'])
                ->orWhereRaw('e.ip=INET6_ATON(?)', [$filters['ip']]));
        }
        $query->when($filters['port'] !== '', fn ($q) => $q->where('e.port', 'LIKE', $filters['port']));

        if ($filters['sharedIpsOnly']) {
            $query->whereIn('e.ip', DB::table('peer_ips')->select('ip')->groupBy('ip')->havingRaw('COUNT(DISTINCT user_id)>1'));
        }

        if ($filters['sharedSocketsOnly']) {
            $query->whereIn(DB::raw('(e.ip,e.port)'),DB::table('peer_ips')->select(['ip','port'])->groupBy(['ip','port'])->havingRaw('COUNT(DISTINCT user_id)>1'));
        }
    }
}
