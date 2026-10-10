<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;
use RuntimeException;

/** TCP confirma alcance da porta; nao comprova transferencia BitTorrent. */
final class EndpointProbe
{
    public function runBatch(int $limit = 25): int
    {
        if (!config('announce.connectable_check')) {
            return 0;
        }
        $lease = TrackerLease::current();
        $policy = Policy::configured();
        $now = (int) Redis::connection('announce')->time()[0];
        $rows = DB::table('peer_ips as e')->join('peers as p', function ($join): void {
            $join->on('e.user_id', '=', 'p.user_id')->on('e.torrent_id', '=', 'p.torrent_id')->on('e.peer_id', '=', 'p.peer_id');
        })->where('p.active', true)->where('e.last_announced_at', '>', gmdate('Y-m-d H:i:s', $now - $policy['endpoint_ttl']))
            ->where(fn ($query) => $query->whereNull('e.connectivity_checked_at')->orWhere('e.connectivity_checked_at', '<', gmdate('Y-m-d H:i:s', $now - (int) config('announce.connectable_check_interval'))))
            ->orderBy('e.connectivity_checked_at')->orderBy('e.updated_at')->limit($limit)->get(['e.*']);
        $published = 0;

        foreach ($rows as $row) {
            $ip = EndpointAddress::observed(inet_ntop($row->ip), $policy['allow_private_addresses']);
            $connectable = $this->check($lease, $ip, (int) $row->port);

            if ($connectable === null) {
                continue;
            }
            $result = (new TransitionJournal($lease))->publish(
                [
                    'user_id' => (int) $row->user_id, 'torrent_id' => (int) $row->torrent_id, 'peer_id' => bin2hex($row->peer_id),
                ],
                ['kind' => 'probe', 'ip' => $ip->text(), 'port' => (int) $row->port, 'revision' => (int) $row->revision, 'connectable' => $connectable],
                $policy,
                ['upload_percent' => 100, 'download_percent' => 100, 'immune' => false]
            );
            $published += $result['outcome'] === 'accepted' ? 1 : 0;
        }

        return $published;
    }

    private function check(TrackerLease $lease, EndpointAddress $ip, int $port): ?bool
    {
        $redis = Redis::connection('announce');
        $keys = [$lease->prefix().':probe-values', $lease->prefix().':probe-expiry'];
        $key = hash('sha256', $ip->binary.pack('n', $port));
        $token = bin2hex(random_bytes(16));
        $capacity = (int) config('dualstack.connectivity_cache_entries');
        $ttl = (int) config('dualstack.connectivity_cache_ttl');

        if ($capacity < 1 || $ttl < 1) {
            throw new RuntimeException('Limites do cache de conectividade invalidos.');
        }
        $result = $redis->eval(<<<'LUA'
local now = tonumber(redis.call('TIME')[1])
local expired = redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', now, 'LIMIT', 0, 1000)
for _, member in ipairs(expired) do redis.call('HDEL', KEYS[1], member); redis.call('ZREM', KEYS[2], member) end
local old = redis.call('HGET', KEYS[1], ARGV[1])
local deadline = redis.call('ZSCORE', KEYS[2], ARGV[1])
if old and (not deadline or tonumber(deadline) <= now) then
    redis.call('HDEL', KEYS[1], ARGV[1]); redis.call('ZREM', KEYS[2], ARGV[1]); old = false
end
if old == '1' or old == '0' then return {'cached', old} end
if old or redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[3]) or redis.call('HLEN', KEYS[1]) >= tonumber(ARGV[3]) then return {'busy'} end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
redis.call('ZADD', KEYS[2], now + 10, ARGV[1])
return {'probe'}
LUA, 2, ...[...$keys, $key, $token, $capacity]);

        if ($result[0] === 'busy') {
            return null;
        }

        if ($result[0] === 'cached') {
            return $result[1] === '1';
        }
        // Fora do CAS, do lock SQL e do coordenador de persistencia.
        $host = $ip->family === 6 ? '['.$ip->text().']' : $ip->text();
        $connection = @fsockopen($host, $port, $errno, $error, 1.0);
        $connectable = \is_resource($connection);

        if ($connectable) {
            fclose($connection);
        }
        $stored = $redis->eval(<<<'LUA'
if redis.call('HGET', KEYS[1], ARGV[1]) ~= ARGV[2] then return 0 end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[3])
redis.call('ZADD', KEYS[2], tonumber(redis.call('TIME')[1]) + tonumber(ARGV[4]), ARGV[1])
return 1
LUA, 2, ...[...$keys, $key, $token, $connectable ? '1' : '0', $ttl]);

        return $stored === 1 ? $connectable : null;
    }
}
