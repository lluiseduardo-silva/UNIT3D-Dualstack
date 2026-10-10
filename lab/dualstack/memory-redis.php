<?php
declare(strict_types=1);
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
if (Illuminate\Support\Facades\DB::getDatabaseName() !== 'unit3d_dualstack_journal_test') {
    throw new RuntimeException('Exige banco exclusivo do laboratorio.');
}
$redis = Illuminate\Support\Facades\Redis::connection('announce');
$lease = App\Services\Dualstack\TrackerLease::current();
$prefix = $lease->prefix();
$journal = new App\Services\Dualstack\TransitionJournal($lease);
$peerKey = $journal->keys(['user_id' => 12001, 'torrent_id' => 12001, 'peer_id' => bin2hex('-DS9200-000000000001')])[0];
$values = [$prefix.':probe-values', $prefix.':probe-expiry', $peerKey, App\Services\Dualstack\TrackerLease::base().':transitions'];
$metrics = $redis->eval(<<<'LUA'
local now = tonumber(redis.call('TIME')[1])
local entries = redis.call('HLEN', KEYS[1])
local deadlines = redis.call('ZCARD', KEYS[2])
local live = redis.call('ZCOUNT', KEYS[2], '(' .. now, '+inf')
return {entries, deadlines, live, redis.call('MEMORY', 'USAGE', KEYS[1]) or 0,
redis.call('MEMORY', 'USAGE', KEYS[2]) or 0, redis.call('STRLEN', KEYS[3]),
redis.call('XLEN', KEYS[4])}
LUA, 4, ...$values);
$result = array_combine(['entries','deadlines','live','values_bytes','expiry_bytes','peer_json_bytes','pending'], $metrics);
foreach (['default', 'cache', 'announce'] as $connection) {
    $result[$connection.'_keys'] = Illuminate\Support\Facades\Redis::connection($connection)->dbSize();
}
$result['redis_used_memory'] = $redis->info('memory')['used_memory'];
echo json_encode($result, JSON_THROW_ON_ERROR)."\n";
