<?php
declare(strict_types=1);
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
use App\Services\Dualstack\TrackerLease;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;
if (DB::getDatabaseName() !== 'unit3d_dualstack_journal_test') {
    exit(1);
}
$redis = Redis::connection('announce');
echo json_encode([
    'generation' => $redis->hGet(TrackerLease::base().':owner', 'generation'),
    'ready' => $redis->hGet(TrackerLease::base().':owner', 'ready'),
    'backlog' => $redis->xLen(TrackerLease::base().':transitions'),
    'peers' => DB::table('peers')->count(), 'endpoints' => DB::table('peer_ips')->count(),
    'peer_states' => DB::table('peers')->orderBy('user_id')->orderBy('torrent_id')->orderBy('peer_id')->get(['user_id', 'torrent_id', DB::raw('HEX(peer_id) AS peer_id_hex'), 'state_version', 'uploaded', 'downloaded', 'active']),
    'endpoint_states' => DB::table('peer_ips')->orderBy('user_id')->orderBy('torrent_id')->orderBy('peer_id')->orderBy('family')->get(['user_id', 'torrent_id', DB::raw('HEX(peer_id) AS peer_id_hex'), 'family', DB::raw('INET6_NTOA(ip) AS ip'), 'port', 'revision']),
    'users' => DB::table('users')->whereIn('id', [12001,12002,12003])->get(['id','uploaded','downloaded']),
], JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR)."\n";
