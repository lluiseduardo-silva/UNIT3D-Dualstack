<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Database\Query\Builder;
use Illuminate\Support\Facades\DB;

/** Uma linha por peer; conectividade positiva exige um endpoint ainda vigente. */
final class BonPeers
{
    public static function query(): Builder
    {
        if (!config('dualstack.enabled')) {
            return DB::table('peers');
        }

        $peers = DB::table('peers as p')
            ->select(['p.user_id', 'p.torrent_id', 'p.peer_id', 'p.active', 'p.seeder', 'p.created_at'])
            ->selectRaw('EXISTS (
                SELECT 1 FROM peer_ips AS endpoint
                WHERE endpoint.user_id = p.user_id AND endpoint.torrent_id = p.torrent_id
                    AND endpoint.peer_id = p.peer_id AND endpoint.connectable = 1
                    AND endpoint.last_announced_at > ?
            ) AS connectable', [now()->subSeconds((int) config('dualstack.endpoint_ttl'))->format('Y-m-d H:i:s')]);

        return DB::query()->fromSub($peers, 'peers');
    }
}
