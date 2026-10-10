<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;
use RuntimeException;
use RedisException;

/** Um lote confirma referencias e todos os efeitos antes de reconhecer o stream. */
final class TransitionWriter
{
    public const GROUP = 'mysql-persistence';

    public function __construct(private readonly TrackerLease $lease)
    {
    }

    private function command(string $name, mixed ...$arguments): mixed
    {
        return Redis::connection('announce')->command('rawCommand', [$name, ...$arguments]);
    }

    public function prepare(): void
    {
        try {
            $this->command('XGROUP', 'CREATE', TrackerLease::base().':transitions', self::GROUP, '0', 'MKSTREAM');
        } catch (RedisException $error) {
            if (!str_contains($error->getMessage(), 'BUSYGROUP')) {
                throw $error;
            }
        }
    }

    /** Reentregas antigas precedem novas mensagens. Nao bloqueia a renovacao da lease. */
    public function read(string $consumer, int $limit = 200, int $claimAfterMs = 5000): array
    {
        $stream = TrackerLease::base().':transitions';
        $claimed = $this->command('XAUTOCLAIM', $stream, self::GROUP, $consumer, $claimAfterMs, '0-0', 'COUNT', $limit);
        $messages = $claimed[1] ?? [];

        if ($messages === []) {
            $read = $this->command('XREADGROUP', 'GROUP', self::GROUP, $consumer, 'COUNT', $limit, 'STREAMS', $stream, '>');
            $messages = $read[0][1] ?? [];
        }
        $result = [];

        foreach ($messages as [$id, $fields]) {
            $payload = null;

            for ($i = 0; $i < \count($fields); $i += 2) {
                if ($fields[$i] === 'payload') {
                    $payload = $fields[$i + 1];
                }
            }

            if ($payload === null) {
                throw new RuntimeException('Transicao sem payload; processamento interrompido.');
            }
            $result[$id] = json_decode($payload, true, flags: JSON_THROW_ON_ERROR);
        }

        return $result;
    }

    public function acknowledge(array $ids): void
    {
        if ($ids === []) {
            return;
        }
        Redis::connection('announce')->eval(<<<'LUA'
for i = 2, #ARGV do
    redis.call('XACK', KEYS[1], ARGV[1], ARGV[i])
    redis.call('XDEL', KEYS[1], ARGV[i])
end
return #ARGV - 1
LUA, 1, TrackerLease::base().':transitions', self::GROUP, ...$ids);
    }

    public function flush(string $consumer, bool $recovering = false): int
    {
        $messages = $this->read($consumer);

        if ($messages === []) {
            return 0;
        }
        $this->persist($messages, $recovering);
        $this->acknowledge(array_keys($messages));

        return \count($messages);
    }

    /** Publico para ensaiar crash depois do commit e antes do reconhecimento. */
    public function persist(array $messages, bool $recovering = false): int
    {
        if ($messages === []) {
            return 0;
        }
        $messages = array_values($messages);

        foreach ($messages as $message) {
            TransitionJournal::identityKey($message['identity']);

            if ($message['schema_version'] !== 1 || $message['generation'] > $this->lease->generation
                || (!$recovering && $message['generation'] !== $this->lease->generation)) {
                throw new RuntimeException('Contrato ou geracao incompativel no journal.');
            }
        }
        usort($messages, fn ($a, $b) => [$a['identity']['user_id'], $a['identity']['torrent_id'], $a['history']['state_version']]
            <=> [$b['identity']['user_id'], $b['identity']['torrent_id'], $b['history']['state_version']]);

        return DB::transaction(function () use ($messages): int {
            // Ordem global: proprietario compartilhado, usuarios, torrents, historicos, peers.
            $this->lease->assertPersistable();
            $userIds = array_values(array_unique(array_column(array_column($messages, 'identity'), 'user_id')));
            $torrentIds = array_values(array_unique(array_column(array_column($messages, 'identity'), 'torrent_id')));
            sort($userIds);
            sort($torrentIds);
            $users = DB::table('users')->whereIn('id', $userIds)->orderBy('id')->lockForUpdate()->pluck('id');
            $torrents = DB::table('torrents')->whereIn('id', $torrentIds)->orderBy('id')->lockForUpdate()->pluck('id');
            $removedUsers = DB::table('users')->whereIn('id', $userIds)->whereNotNull('deleted_at')->where('tracker_removal_state', '>', 0)->pluck('id')->all();
            $removedTorrents = DB::table('torrents')->whereIn('id', $torrentIds)->whereNotNull('deleted_at')->where('tracker_removal_state', '>', 0)->pluck('id')->all();

            if ($users->count() !== \count($userIds) || $torrents->count() !== \count($torrentIds)) {
                throw new RuntimeException('Usuario ou torrent removido com transicoes pendentes.');
            }
            $groupIdentities = $peerIdentities = [];

            foreach ($messages as $message) {
                $id = $message['identity'];
                $groupIdentities[$id['user_id'].':'.$id['torrent_id']] = [$id['user_id'], $id['torrent_id']];
                $peerIdentities[TransitionJournal::identityKey($id)] = $id;
            }
            $histories = array_fill_keys(array_keys($groupIdentities), []);

            foreach (self::tuples('history', ['user_id', 'torrent_id'], array_values($groupIdentities))
                ->orderBy('user_id')->orderBy('torrent_id')->lockForUpdate()->get() as $row) {
                $histories[$row->user_id.':'.$row->torrent_id] = (array) $row;
            }
            $peerTuples = array_map(fn ($id) => array_values(self::binaryIdentity($id)), array_values($peerIdentities));
            $peers = array_fill_keys(array_keys($peerIdentities), []);

            foreach (self::tuples('peers', ['user_id', 'torrent_id', 'peer_id'], $peerTuples)
                ->orderBy('user_id')->orderBy('torrent_id')->orderBy('peer_id')->lockForUpdate()->get() as $row) {
                $peers[$row->user_id.':'.$row->torrent_id.':'.bin2hex($row->peer_id)] = (array) $row;
            }
            $peerRows = $historyRows = $userDeltas = $torrentDeltas = $lastStates = [];
            $applied = 0;
            $trace = [];

            foreach ($messages as $message) {
                $id = $message['identity'];

                if (\in_array($id['user_id'], $removedUsers, true) || \in_array($id['torrent_id'], $removedTorrents, true)) {
                    continue;
                }
                $key = TransitionJournal::identityKey($id);
                $groupKey = $id['user_id'].':'.$id['torrent_id'];
                $group = $message['history'];
                $state = $message['peer'];
                $previousHistory = $histories[$groupKey];
                $previousVersion = (int) ($previousHistory['state_version'] ?? 0);

                if ($group['state_version'] <= $previousVersion) {
                    continue;
                }

                if ($group['state_version'] !== $previousVersion + 1
                    || $state['state_version'] !== (int) ($peers[$key]['state_version'] ?? 0) + 1) {
                    throw new RuntimeException('Lacuna de versao: aguarde a transicao anterior antes de persistir.');
                }
                $applied++;

                if (config('dualstack.trace_transitions')) {
                    $trace[] = $id + ['generation' => $message['generation'], 'state_version' => $state['state_version'],
                        'history_version'          => $group['state_version'], 'family' => $message['family'], 'event' => $message['event'],
                        'operation'                => $message['operation'], 'upload_delta' => $message['upload_delta'], 'download_delta' => $message['download_delta'],
                        'credited_upload'          => $message['credited_upload'], 'credited_download' => $message['credited_download']];
                }
                $legacy = $state['legacy_endpoint'];
                $peerRows[$key] = self::binaryIdentity($id) + [
                    'agent'          => $state['agent'], 'uploaded' => Counter::of($state['uploaded']), 'downloaded' => Counter::of($state['downloaded']),
                    'left'           => Counter::of($state['left']), 'seeder' => $state['seeder'], 'active' => $state['active'], 'visible' => $state['visible'],
                    'ip'             => inet_pton($legacy['ip']), 'port' => $legacy['port'], 'connectable' => $state['connectable'],
                    'created_at'     => gmdate('Y-m-d H:i:s', $state['created_at']), 'updated_at' => gmdate('Y-m-d H:i:s', $state['updated_at']),
                    'state_version'  => $state['state_version'], 'session_generation' => $state['session_generation'], 'completion_reported' => $state['completion_reported'],
                    'protocol_state' => json_encode(['last_announces' => $state['last_announces'], 'session_started_at' => $state['session_started_at']], JSON_THROW_ON_ERROR),
                ];
                $peers[$key] = $peerRows[$key];
                $lastStates[$key] = $state;
                $timestamp = gmdate('Y-m-d H:i:s', $state['updated_at']);
                $history = $previousHistory ?: [
                    'user_id'  => $id['user_id'], 'torrent_id' => $id['torrent_id'],
                    'uploaded' => '0', 'downloaded' => '0', 'actual_uploaded' => '0', 'actual_downloaded' => '0',
                    'seedtime' => 0, 'created_at' => $timestamp, 'completed_at' => null, 'immune' => $message['immune'] ?? false,
                ];

                foreach (['uploaded' => 'credited_upload', 'downloaded' => 'credited_download', 'actual_uploaded' => 'upload_delta', 'actual_downloaded' => 'download_delta'] as $field => $delta) {
                    $history[$field] = Counter::add((string) $history[$field], Counter::of($message[$delta]));
                }
                $history['agent'] = $state['agent'];
                $history['client_uploaded'] = $state['uploaded'];
                $history['client_downloaded'] = $state['downloaded'];
                $history['active'] = $group['peers'] !== [];
                $history['seeder'] = \in_array(true, array_column($group['peers'], 'seeder'), true);
                $history['seedtime'] += $message['seedtime_delta'];
                $history['updated_at'] = $timestamp;
                $history['swarm_updated_at'] = gmdate('Y-m-d H:i:s', $group['last_at']);
                $history['state_version'] = $group['state_version'];
                $history['immune'] = (bool) $history['immune'] && ($message['immune'] ?? true);

                if ($message['completed_delta'] && $history['completed_at'] === null) {
                    $history['completed_at'] = $timestamp;
                }
                $histories[$groupKey] = $history;
                $historyRows[$groupKey] = array_intersect_key($history, array_flip([
                    'user_id', 'torrent_id', 'agent', 'uploaded', 'downloaded', 'actual_uploaded', 'actual_downloaded',
                    'client_uploaded', 'client_downloaded', 'active', 'seeder', 'immune', 'seedtime', 'created_at', 'updated_at', 'completed_at', 'state_version', 'swarm_updated_at',
                ]));
                $userDeltas[$id['user_id']] ??= ['uploaded' => '0', 'downloaded' => '0'];
                $userDeltas[$id['user_id']]['uploaded'] = Counter::add($userDeltas[$id['user_id']]['uploaded'], Counter::of($message['credited_upload']));
                $userDeltas[$id['user_id']]['downloaded'] = Counter::add($userDeltas[$id['user_id']]['downloaded'], Counter::of($message['credited_download']));
                $torrentDeltas[$id['torrent_id']] ??= array_fill_keys([...array_keys($message['counts']), 'times_completed'], 0);

                foreach ($message['counts'] as $field => $delta) {
                    $torrentDeltas[$id['torrent_id']][$field] += $delta;
                }
                $torrentDeltas[$id['torrent_id']]['times_completed'] += $message['completed_delta'];
            }

            if ($applied === 0) {
                return 0;
            }
            DB::table('peers')->upsert(array_values($peerRows), ['user_id', 'torrent_id', 'peer_id'], array_values(array_diff(array_keys(reset($peerRows)), ['user_id', 'torrent_id', 'peer_id', 'created_at'])));
            $endpoints = [];
            self::tuples('peer_ips', ['user_id', 'torrent_id', 'peer_id'], array_map(fn ($key) => array_values(self::binaryIdentity($peerIdentities[$key])), array_keys($lastStates)))->delete();

            foreach ($lastStates as $key => $state) {
                $identity = self::binaryIdentity($peerIdentities[$key]);

                foreach ($state['endpoints'] as $endpoint) {
                    $endpoints[] = $identity + [
                        'family'                  => $endpoint['family'], 'ip' => inet_pton($endpoint['ip']), 'port' => $endpoint['port'], 'connectable' => $endpoint['connectable'],
                        'last_announced_at'       => gmdate('Y-m-d H:i:s', $endpoint['last_announced_at']), 'revision' => $endpoint['revision'],
                        'connectivity_checked_at' => $endpoint['connectivity_checked_at'] === null ? null : gmdate('Y-m-d H:i:s', $endpoint['connectivity_checked_at']),
                        'created_at'              => gmdate('Y-m-d H:i:s', $endpoint['created_at']), 'updated_at' => gmdate('Y-m-d H:i:s', $state['updated_at']),
                    ];
                }
            }

            if ($endpoints !== []) {
                DB::table('peer_ips')->insert($endpoints);
            }
            DB::table('history')->upsert(array_values($historyRows), ['user_id', 'torrent_id'], array_values(array_diff(array_keys(reset($historyRows)), ['user_id', 'torrent_id', 'created_at'])));
            self::incrementRows('users', $userDeltas);
            self::incrementRows('torrents', $torrentDeltas);

            if ($trace !== []) {
                DB::afterCommit(function () use ($trace): void {
                    foreach ($trace as $event) {
                        logger()->info('dualstack.transition', $event);
                    }
                });
            }

            return $applied;
        }, 5);
    }

    private static function binaryIdentity(array $identity): array
    {
        return ['user_id' => (int) $identity['user_id'], 'torrent_id' => (int) $identity['torrent_id'], 'peer_id' => hex2bin($identity['peer_id'])];
    }

    public static function tuples(string $table, array $columns, array $rows): \Illuminate\Database\Query\Builder
    {
        $tuple = '('.implode(',', array_fill(0, \count($columns), '?')).')';

        return DB::table($table)->whereRaw('('.implode(',', $columns).') IN ('.implode(',', array_fill(0, \count($rows), $tuple)).')', array_merge(...$rows));
    }

    private static function incrementRows(string $table, array $rows): void
    {
        $sets = $bindings = [];

        foreach (array_keys(reset($rows)) as $field) {
            $sql = '`'.$field.'` = `'.$field.'` + CASE id';

            foreach ($rows as $id => $deltas) {
                $sql .= ' WHEN ? THEN CAST(? AS DECIMAL(30,0))';
                $bindings[] = $id;
                $bindings[] = $deltas[$field];
            }
            $sets[] = $sql.' ELSE 0 END';
        }
        DB::update('UPDATE `'.$table.'` SET '.implode(', ', $sets).' WHERE id IN ('.implode(',', array_fill(0, \count($rows), '?')).')', [...$bindings, ...array_keys($rows)]);
    }
}
