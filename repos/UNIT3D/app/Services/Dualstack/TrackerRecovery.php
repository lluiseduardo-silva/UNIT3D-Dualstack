<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;
use RuntimeException;

/** Executar com a entrada fechada. SQL confirmado e journal precedem o cache. */
final class TrackerRecovery
{
    public function __construct(private readonly TrackerLease $lease, private readonly array $policy)
    {
    }

    public function restore(): array
    {
        $this->lease->ready(false);
        $redis = Redis::connection('announce');
        $memoryPolicy = $redis->command('rawCommand', ['CONFIG', 'GET', 'maxmemory-policy']);

        if (($memoryPolicy[1] ?? null) !== 'noeviction') {
            throw new RuntimeException('O Redis do journal exige maxmemory-policy=noeviction.');
        }
        $writer = new TransitionWriter($this->lease);
        $writer->prepare();
        $replayed = $this->drain($writer, true);
        $this->clearCache($this->lease->prefix().':*');
        DeletedEntities::restoreFences($this->lease);
        $cursor = null;
        $count = 0;
        $groupKey = null;
        $group = null;

        do {
            $this->lease->renew();
            $query = DB::table('peers')->orderBy('user_id')->orderBy('torrent_id')->orderBy('peer_id')->limit(500);

            if ($cursor !== null) {
                $query->whereRaw('(user_id,torrent_id,peer_id) > (?,?,?)', $cursor);
            }
            $rows = $query->get();

            if ($rows->isEmpty()) {
                break;
            }
            $identities = $rows->map(fn ($peer) => [$peer->user_id, $peer->torrent_id, $peer->peer_id])->all();
            $endpoints = TransitionWriter::tuples('peer_ips', ['user_id', 'torrent_id', 'peer_id'], $identities)->get()
                ->groupBy(fn ($row) => $row->user_id.':'.$row->torrent_id.':'.bin2hex($row->peer_id));
            $histories = TransitionWriter::tuples('history', ['user_id', 'torrent_id'], array_map(fn ($id) => \array_slice($id, 0, 2), $identities))->get()
                ->keyBy(fn ($row) => $row->user_id.':'.$row->torrent_id);
            $commands = [];

            foreach ($rows as $row) {
                $cursor = [$row->user_id, $row->torrent_id, $row->peer_id];
                $key = $row->user_id.':'.$row->torrent_id.':'.bin2hex($row->peer_id);
                $nextGroup = $row->user_id.':'.$row->torrent_id;

                if ($nextGroup !== $groupKey) {
                    if ($group !== null) {
                        $commands[] = ['set', $this->lease->prefix().':history:'.$groupKey, json_encode($group, JSON_THROW_ON_ERROR)];
                    }
                    $groupKey = $nextGroup;
                    $history = $histories[$groupKey] ?? null;
                    $group = ['state_version' => (int) ($history->state_version ?? 0), 'peers' => [],
                        'completed'           => ($history->completed_at ?? null) !== null,
                        'last_at'             => self::time($history->swarm_updated_at ?? $history->updated_at ?? $row->updated_at)];
                }
                $state = self::peer($row, $endpoints[$key] ?? []);
                $commands[] = ['set', $this->lease->prefix().':peer:'.$key, json_encode($state, JSON_THROW_ON_ERROR)];

                if ($state['active']) {
                    $lasts = array_column($state['endpoints'], 'last_announced_at');
                    $expiry = max($lasts) + $this->policy['endpoint_ttl'];
                    $group['peers'][bin2hex($row->peer_id)] = ['seeder' => $state['seeder'], 'expires_at' => $expiry];
                    $commands[] = ['zadd', $this->lease->prefix().':expiry', min($lasts) + $this->policy['endpoint_ttl'], $key];

                    if ($state['visible'] && !$state['seeder']) {
                        $commands[] = ['zadd', $this->lease->prefix().':user-leechers:'.$row->user_id, $expiry, $key];
                    }
                }
                $count++;
            }
            $redis->pipeline(function ($pipe) use ($commands): void {
                foreach ($commands as $command) {
                    $method = array_shift($command);
                    $pipe->{$method}(...$command);
                }
            });
        } while ($rows->count() === 500);

        if ($group !== null) {
            $redis->set($this->lease->prefix().':history:'.$groupKey, json_encode($group, JSON_THROW_ON_ERROR));
        }
        $this->lease->renew();
        $this->reconcileCounts();
        $expired = 0;

        do {
            $this->lease->renew();
            $processed = $this->expire(200, true);
            $expired += $processed;
            $this->drain($writer, true);
        } while ($processed === 200);
        $this->lease->renew();
        $this->clearCache(TrackerLease::base().':g:*', $this->lease->prefix().':');
        $this->lease->renew();
        $this->lease->ready(true);

        return ['loaded_peers' => $count, 'replayed_transitions' => $replayed, 'expired_peers' => $expired];
    }

    public function drain(TransitionWriter $writer, bool $recovering): int
    {
        $started = hrtime(true);
        $total = 0;

        while ((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions') > 0) {
            if ((hrtime(true) - $started) / 1e9 > 120) {
                throw new RuntimeException('Drenagem excedeu 120 segundos; entrada permanece fechada.');
            }
            $this->lease->renew();
            $messages = $writer->read('coordinator-'.$this->lease->ownerId, 200, $recovering ? 0 : 5000);

            if ($messages === []) {
                usleep(100000);

                continue;
            }
            $writer->persist($messages, $recovering);
            $writer->acknowledge(array_keys($messages));
            $total += \count($messages);
        }

        return $total;
    }

    public function expire(int $limit = 200, bool $initializing = false): int
    {
        $redis = Redis::connection('announce');
        $now = (int) $redis->time()[0];
        $members = $redis->zRangeByScore($this->lease->prefix().':expiry', '-inf', (string) $now, ['limit' => [0, $limit]]);
        $journal = new TransitionJournal($this->lease);

        foreach ($members as $member) {
            [$user, $torrent, $peer] = explode(':', $member);
            $result = $journal->publish(
                ['user_id' => (int) $user, 'torrent_id' => (int) $torrent, 'peer_id' => $peer],
                ['kind' => 'expire'],
                $this->policy,
                ['upload_percent' => 100, 'download_percent' => 100, 'immune' => false],
                initializing: $initializing
            );

            if ($result['outcome'] === 'ignored' || ($result['reason'] ?? null) === 'removed') {
                // Um announce pode ter renovado a origem apos a leitura do ZSET.
                $redis->eval(<<<'LUA'
local deadline = redis.call('ZSCORE', KEYS[1], ARGV[1])
if deadline and tonumber(deadline) <= tonumber(ARGV[2]) then redis.call('ZREM', KEYS[1], ARGV[1]) end
return 1
LUA, 1, $this->lease->prefix().':expiry', $member, $now);
            }
        }

        return \count($members);
    }

    private function clearCache(string $pattern, ?string $exceptPrefix = null): void
    {
        $redis = Redis::connection('announce');
        $cursor = '0';

        do {
            $this->lease->renew();
            [$cursor, $keys] = $redis->command('rawCommand', ['SCAN', $cursor, 'MATCH', $pattern, 'COUNT', 1000]);

            if ($exceptPrefix !== null) {
                $keys = array_values(array_filter($keys, fn ($key) => !str_starts_with($key, $exceptPrefix)));
            }

            if ($keys !== []) {
                $redis->command('rawCommand', ['UNLINK', ...$keys]);
            }
        } while ((string) $cursor !== '0');
    }

    /** Pausa curta somente quando ha peers a retirar; nenhuma referencia pendente e descartada. */
    public function retire(int $limit = 200): int
    {
        $retention = (int) config('dualstack.inactive_peer_retention');

        if ($retention < 7200) {
            throw new RuntimeException('Retencao contabil deve ser de pelo menos 7200 segundos.');
        }
        $cutoff = gmdate('Y-m-d H:i:s', (int) Redis::connection('announce')->time()[0] - $retention);
        $candidate = fn () => DB::table('peers')->where('active', false)->where('updated_at', '<', $cutoff);

        if (!$candidate()->exists()) {
            return 0;
        }
        $this->lease->ready(false);
        $writer = new TransitionWriter($this->lease);
        $this->drain($writer, true);
        $this->lease->renew();
        $identities = DB::transaction(function () use ($candidate, $limit): array {
            $this->lease->assertPersistable();
            $rows = $candidate()->orderBy('user_id')->orderBy('torrent_id')->orderBy('peer_id')->limit($limit)->lockForUpdate()
                ->get(['user_id', 'torrent_id', 'peer_id']);

            if ($rows->isNotEmpty()) {
                TransitionWriter::tuples('peers', ['user_id', 'torrent_id', 'peer_id'], $rows->map(fn ($row) => [$row->user_id, $row->torrent_id, $row->peer_id])->all())->delete();
            }

            return $rows->all();
        }, 3);
        $redis = Redis::connection('announce');

        foreach ($identities as $identity) {
            $key = $identity->user_id.':'.$identity->torrent_id.':'.bin2hex($identity->peer_id);
            $redis->eval(
                <<<'LUA'
redis.call('DEL', KEYS[1])
redis.call('ZREM', KEYS[2], ARGV[1])
redis.call('ZREM', KEYS[3], ARGV[1])
local group = redis.call('GET', KEYS[4])
if group and next(cjson.decode(group).peers) == nil then redis.call('DEL', KEYS[4]) end
return 1
LUA,
                4,
                $this->lease->prefix().':peer:'.$key,
                $this->lease->prefix().':expiry',
                $this->lease->prefix().':user-leechers:'.$identity->user_id,
                $this->lease->prefix().':history:'.$identity->user_id.':'.$identity->torrent_id,
                $key
            );
        }
        // Qualquer falha anterior deixa a entrada fechada; restore() reconstrui
        // o cache a partir do SQL antes de uma nova geracao voltar a aceitar.
        $this->lease->renew();
        $this->lease->ready(true);

        return \count($identities);
    }

    private function reconcileCounts(): void
    {
        // Estado confirmado antes da limpeza temporal. As expiracoes a seguir
        // registram a diferenca por versao e historico, sem subtrair duas vezes.
        $connectivity = $this->policy['require_connectivity'] ? ' AND e.connectable=1' : '';
        DB::transaction(function () use ($connectivity): void {
            $this->lease->assertPersistable();
            $columns = $sets = [];

            foreach (['seeders' => 'p.seeder=1', 'leechers' => 'p.seeder=0'] as $name => $kind) {
                foreach (['' => '', '_ipv4' => ' AND e.family=4', '_ipv6' => ' AND e.family=6'] as $suffix => $family) {
                    $field = $name.$suffix;
                    $columns[] = "SUM(({$kind}) AND EXISTS (SELECT 1 FROM peer_ips e WHERE e.user_id=p.user_id AND e.torrent_id=p.torrent_id AND e.peer_id=p.peer_id {$family} {$connectivity})) AS {$field}";
                    $sets[] = "t.{$field}=COALESCE(c.{$field},0)";
                }
            }
            DB::update('UPDATE torrents t LEFT JOIN (SELECT p.torrent_id,'.implode(',', $columns).' FROM peers p WHERE p.active=1 AND p.visible=1 GROUP BY p.torrent_id) c ON c.torrent_id=t.id SET '.implode(',', $sets));
        }, 3);
    }

    private static function time(?string $value): int
    {
        return $value === null ? 0 : (int) strtotime($value.' UTC');
    }

    private static function peer(object $row, iterable $rows): array
    {
        $protocol = $row->protocol_state === null ? [] : json_decode($row->protocol_state, true, flags: JSON_THROW_ON_ERROR);
        $endpoints = [];

        if ($row->active) {
            foreach ($rows as $endpoint) {
                $ip = EndpointAddress::observed(inet_ntop($endpoint->ip), (bool) config('dualstack.allow_private_addresses'));
                $endpoints[$ip->family] = ['family' => $ip->family, 'ip' => $ip->text(), 'port' => (int) $endpoint->port,
                    'connectable'                   => $endpoint->connectable === null ? null : (bool) $endpoint->connectable,
                    'last_announced_at'             => self::time($endpoint->last_announced_at), 'revision' => (int) $endpoint->revision,
                    'connectivity_checked_at'       => $endpoint->connectivity_checked_at === null ? null : self::time($endpoint->connectivity_checked_at),
                    'created_at'                    => self::time($endpoint->created_at)];
            }

            if ($endpoints === []) {
                throw new RuntimeException('Peer ativo sem endpoint; execute e verifique o backfill antes de iniciar.');
            }
        }
        ksort($endpoints);

        return ['uploaded'        => (string) $row->uploaded, 'downloaded' => (string) $row->downloaded, 'left' => (string) $row->left,
            'agent'               => $row->agent, 'visible' => (bool) $row->visible, 'active' => $endpoints !== [], 'seeder' => (bool) $row->seeder,
            'connectable'         => \in_array(true, array_column($endpoints, 'connectable'), true),
            'state_version'       => (int) $row->state_version, 'session_generation' => (int) $row->session_generation,
            'completion_reported' => (bool) $row->completion_reported || ((int) $row->state_version === 0 && (bool) $row->seeder),
            'created_at'          => self::time($row->created_at), 'updated_at' => self::time($row->updated_at),
            'session_started_at'  => $protocol['session_started_at'] ?? self::time($row->created_at),
            'last_announces'      => $protocol['last_announces'] ?? array_map(fn ($endpoint) => $endpoint['last_announced_at'], $endpoints),
            'endpoints'           => $endpoints, 'legacy_endpoint' => ['ip' => inet_ntop($row->ip), 'port' => (int) $row->port]];
    }
}
