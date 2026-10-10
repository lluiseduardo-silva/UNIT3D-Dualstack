<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Database\Query\Builder;
use Illuminate\Support\Facades\DB;

final class AnnounceResponse
{
    private static function endpoints(Builder $query, int $now): void
    {
        $query->where('e.last_announced_at', '>', gmdate('Y-m-d H:i:s', $now - (int) config('dualstack.endpoint_ttl')));

        if (config('dualstack.require_connectivity')) {
            $query->where('e.connectable', true);
        }
    }

    public function build(int $torrentId, int $userId, bool $seeder, int $numwant, bool $stopped, ?string $warning = null): string
    {
        $now = (int) now()->timestamp;
        $eligible = DB::table('peers as p')->where('p.torrent_id', $torrentId)->where('p.active', true)->where('p.visible', true)
            ->whereExists(fn ($q) => $q->selectRaw('1')->from('users as u')->whereColumn('u.id', 'p.user_id')->whereNull('u.deleted_at'))
            ->whereExists(fn ($q) => $q->selectRaw('1')->from('torrents as t')->whereColumn('t.id', 'p.torrent_id')->whereNull('t.deleted_at'))
            ->whereExists(function (Builder $query) use ($now): void {
                $query->selectRaw('1')->from('peer_ips as e')->whereColumn('e.user_id', 'p.user_id')
                    ->whereColumn('e.torrent_id', 'p.torrent_id')->whereColumn('e.peer_id', 'p.peer_id');
                self::endpoints($query, $now);
            });
        $counts = (clone $eligible)->selectRaw('COALESCE(SUM(p.seeder=1),0) AS seeders, COALESCE(SUM(p.seeder=0),0) AS leechers')->first();
        $completed = (int) DB::table('torrents')->where('id', $torrentId)->value('times_completed');
        $ipv4 = $ipv6 = '';
        $limit = $stopped || $warning !== null ? 0 : min(25, max(0, $numwant));

        if ($limit > 0) {
            $selected = $eligible->where('p.user_id', '<>', $userId)->when($seeder, fn ($q) => $q->where('p.seeder', false))
                ->orderBy('p.user_id')->orderBy('p.peer_id')->limit($limit)->get(['p.user_id', 'p.torrent_id', 'p.peer_id']);

            if ($selected->isNotEmpty()) {
                $query = TransitionWriter::tuples(
                    'peer_ips as e',
                    ['e.user_id', 'e.torrent_id', 'e.peer_id'],
                    $selected->map(fn ($row) => [$row->user_id, $row->torrent_id, $row->peer_id])->all()
                );
                self::endpoints($query, $now);

                foreach ($query->get(['e.family', 'e.ip', 'e.port']) as $endpoint) {
                    if ((int) $endpoint->family === 4) {
                        $ipv4 .= $endpoint->ip.pack('n', (int) $endpoint->port);
                    } else {
                        $ipv6 .= $endpoint->ip.pack('n', (int) $endpoint->port);
                    }
                }
            }
        }
        $response = 'd8:completei'.$counts->seeders.'e10:downloadedi'.$completed.'e10:incompletei'.$counts->leechers
            .'e8:intervali'.random_int(1800, 3600).'e12:min intervali'.random_int(1710, 1800).'e'
            .'5:peers'.\strlen($ipv4).':'.$ipv4.'6:peers6'.\strlen($ipv6).':'.$ipv6;

        if ($warning !== null) {
            $response .= '15:warning message'.\strlen($warning).':'.$warning;
        }

        return $response.'e';
    }
}
