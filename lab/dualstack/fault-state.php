<?php
declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Services\Dualstack\TrackerLease;
use App\Services\Dualstack\TransitionJournal;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;

if (DB::getDatabaseName() !== 'unit3d_dualstack_journal_test') {
    exit(1);
}
$identity = ['user_id' => 12001, 'torrent_id' => 12001, 'peer_id' => bin2hex('-DS9200-000000000091')];
$result = [];
try {
    $redis = Redis::connection('announce');
    $lease = TrackerLease::current();
    $state = json_decode($redis->get((new TransitionJournal($lease))->keys($identity)[0]) ?: 'null', true);
    $result['redis'] = [
        'available' => true, 'generation' => $lease->generation,
        'ready' => $redis->hGet(TrackerLease::base().':owner', 'ready'),
        'heartbeat_ms' => $redis->pttl(TrackerLease::base().':heartbeat'),
        'backlog' => $redis->xLen(TrackerLease::base().':transitions'),
        'peer_version' => $state['state_version'] ?? null,
        'uploaded' => $state['uploaded'] ?? null,
        'endpoints' => array_values($state['endpoints'] ?? []),
    ];
} catch (Throwable $error) {
    $result['redis'] = ['available' => false, 'error_type' => $error::class];
}
try {
    $result['mysql'] = [
        'available' => true,
        'ownership' => DB::table('tracker_ownership')->where('id', 1)
            ->selectRaw('generation, GREATEST(0, TIMESTAMPDIFF(MICROSECOND, UTC_TIMESTAMP(3), lease_expires_at) / 1000000) AS lease_remaining_seconds')->first(),
        'peers' => DB::table('peers')->orderBy('user_id')->orderBy('torrent_id')->orderBy('peer_id')
            ->get(['user_id', 'torrent_id', DB::raw('HEX(peer_id) AS peer_id_hex'), 'state_version', 'uploaded', 'downloaded', 'active']),
        'endpoints' => DB::table('peer_ips')->orderBy('family')
            ->get(['family', DB::raw('INET6_NTOA(ip) AS ip'), 'port', 'revision']),
        'user' => DB::table('users')->where('id', 12001)->first(['uploaded', 'downloaded']),
        'history' => DB::table('history')->where('user_id', 12001)->where('torrent_id', 12001)
            ->first(['state_version', 'actual_uploaded', 'actual_downloaded', 'active', 'seedtime']),
        'torrent' => DB::table('torrents')->where('id', 12001)
            ->first(['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6']),
    ];
} catch (Throwable $error) {
    $result['mysql'] = ['available' => false, 'error_type' => $error::class];
}
echo json_encode($result, JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR)."\n";
