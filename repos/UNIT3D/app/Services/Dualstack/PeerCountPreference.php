<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Support\Facades\DB;

final class PeerCountPreference
{
    /** Um lote de usuarios; nenhuma consulta ou escrita por peer. */
    public function resolve(array $userIds): int
    {
        if (!config('dualstack.enabled') || $userIds === []) {
            return 0;
        }

        $activity = DB::table('peer_ips as endpoints')
            ->join('peers', fn ($join) => $join
                ->on('peers.user_id', '=', 'endpoints.user_id')
                ->on('peers.torrent_id', '=', 'endpoints.torrent_id')
                ->on('peers.peer_id', '=', 'endpoints.peer_id'))
            ->whereIn('peers.user_id', $userIds)
            ->where('peers.active', true)
            ->where('endpoints.last_announced_at', '>', now()->subSeconds((int) config('dualstack.endpoint_ttl')))
            ->select('peers.user_id')
            ->selectRaw('BIT_OR(IF(peers.seeder, IF(endpoints.family = 4, 1, 2), 0)) AS seeding_families')
            ->selectRaw('BIT_OR(IF(endpoints.family = 4, 1, 2)) AS active_families')
            ->groupBy('peers.user_id');

        return DB::transaction(fn () => DB::table('users')
            ->leftJoinSub($activity, 'activity', fn ($join) => $join->on('activity.user_id', '=', 'users.id'))
            ->whereIn('users.id', $userIds)
            ->where('users.peer_count_mode', 'auto')
            ->update(['users.peer_count_auto_mode' => DB::raw("CASE COALESCE(NULLIF(activity.seeding_families, 0), activity.active_families, 0) WHEN 1 THEN 'ipv4' WHEN 2 THEN 'ipv6' ELSE 'sum' END")]), 5);
    }
}
