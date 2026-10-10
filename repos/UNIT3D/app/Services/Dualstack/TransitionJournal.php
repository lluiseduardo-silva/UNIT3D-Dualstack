<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Support\Facades\Redis;
use Illuminate\Support\Facades\DB;
use InvalidArgumentException;
use RuntimeException;

/** CAS entre processos PHP: snapshot, efeitos e referencia entram juntos no Redis. */
final class TransitionJournal
{
    public function __construct(private readonly TrackerLease $lease)
    {
    }

    public static function identityKey(array $identity): string
    {
        if (($identity['user_id'] ?? 0) < 1 || ($identity['torrent_id'] ?? 0) < 1
            || \strlen($identity['peer_id'] ?? '') !== 40 || !ctype_xdigit($identity['peer_id'])) {
            throw new InvalidArgumentException('Identidade de peer invalida.');
        }

        return (int) $identity['user_id'].':'.(int) $identity['torrent_id'].':'.strtolower($identity['peer_id']);
    }

    public function keys(array $identity): array
    {
        $id = self::identityKey($identity);
        $prefix = $this->lease->prefix();

        return [$prefix.':peer:'.$id, $prefix.':history:'.$identity['user_id'].':'.$identity['torrent_id'],
            $prefix.':user-version:'.$identity['user_id'], $prefix.':user-leechers:'.$identity['user_id'],
            $prefix.':expiry', TrackerLease::base().':transitions', TrackerLease::base().':owner', TrackerLease::base().':heartbeat',
            $prefix.':deleted-users', $prefix.':deleted-torrents'];
    }

    /** $clock e reservado a testes/operacoes internas; o HTTP usa TIME do Redis. */
    public function publish(array $identity, array $request, array $policy, array $credit, ?int $clock = null, bool $initializing = false): array
    {
        self::identityKey($identity);
        $identity['peer_id'] = strtolower($identity['peer_id']);
        $redis = Redis::connection('announce');
        $keys = $this->keys($identity);
        $member = self::identityKey($identity);
        $ready = $initializing ? '0' : '1';

        for ($attempt = 0; $attempt < 16; $attempt++) {
            $read = $redis->eval(<<<'LUA'
if redis.call('HGET', KEYS[7], 'owner_id') ~= ARGV[1] or redis.call('HGET', KEYS[7], 'ready') ~= ARGV[2] or redis.call('GET', KEYS[8]) ~= ARGV[1] then return {'unavailable'} end
if redis.call('SISMEMBER', KEYS[9], ARGV[4]) == 1 or redis.call('SISMEMBER', KEYS[10], ARGV[5]) == 1 then return {'removed'} end
local now = tonumber(ARGV[3]) or tonumber(redis.call('TIME')[1])
return {'ok', redis.call('GET', KEYS[1]) or '', redis.call('GET', KEYS[2]) or '', redis.call('GET', KEYS[3]) or '0', redis.call('ZCOUNT', KEYS[4], '(' .. now, '+inf'), now}
LUA, \count($keys), ...[...$keys, $this->lease->ownerId, $ready, $clock === null ? '' : (string) $clock, $identity['user_id'], $identity['torrent_id']]);

            if ($read[0] === 'removed') {
                return ['outcome' => 'rejected', 'reason' => 'removed', 'peer' => null];
            }

            if ($read[0] !== 'ok') {
                throw new RuntimeException('Tracker em inicializacao, recuperacao ou sem proprietario ativo.');
            }
            [, $oldPeer, $oldHistory, $userVersion, $leechers, $now] = $read;
            $before = $oldPeer === '' ? null : json_decode($oldPeer, true, flags: JSON_THROW_ON_ERROR);

            if ($oldHistory === '') {
                // Grupos sem peers nao ocupam o bootstrap inteiro. O primeiro acesso
                // recupera somente sua referencia; SET NX nao vence outro announce.
                $persisted = DB::table('history')->where('user_id', $identity['user_id'])->where('torrent_id', $identity['torrent_id'])
                    ->first(['state_version', 'completed_at', 'swarm_updated_at']);
                $initial = ['state_version' => (int) ($persisted->state_version ?? 0), 'peers' => [],
                    'completed'             => ($persisted->completed_at ?? null) !== null, 'last_at' => (int) $now];
                $redis->eval(<<<'LUA'
if redis.call('HGET', KEYS[2], 'owner_id') ~= ARGV[1] or redis.call('HGET', KEYS[2], 'ready') ~= ARGV[2] or redis.call('GET', KEYS[3]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[3], 'NX')
return 1
LUA, 3, $keys[1], $keys[6], $keys[7], $this->lease->ownerId, $ready, json_encode($initial, JSON_THROW_ON_ERROR));

                continue;
            }
            $history = json_decode($oldHistory, true, flags: JSON_THROW_ON_ERROR);
            $now = max((int) $now, (int) $history['last_at']);
            $request['at'] = $now;
            $result = PeerTransition::apply($before, $request, $policy);

            if ($result['outcome'] !== 'accepted') {
                return $result;
            }
            $state = $result['peer'];
            $deadline = 0;

            foreach ($history['peers'] as $peerId => $peer) {
                if ($peer['seeder']) {
                    $deadline = max($deadline, $peer['expires_at']);
                }

                if ($peer['expires_at'] <= $now) {
                    unset($history['peers'][$peerId]);
                }
            }
            $wasMember = isset($history['peers'][$identity['peer_id']]);

            if ($state['active'] && !$wasMember && \count($history['peers']) >= (int) $policy['max_peers']) {
                return ['outcome' => 'rejected', 'reason' => 'peer_limit', 'peer' => $before, 'upload_delta' => '0', 'download_delta' => '0', 'completed_delta' => 0];
            }
            $expires = $state['active'] ? max(array_column($state['endpoints'], 'last_announced_at')) + $policy['endpoint_ttl'] : 0;
            $previousOwnSlot = $before !== null && $before['visible'] && !$before['seeder']
                && $before['active'] && max(array_column($before['endpoints'], 'last_announced_at')) + $policy['endpoint_ttl'] > $now;

            if ($state['active'] && !$state['seeder'] && ($policy['download_slots'] ?? null) !== null) {
                $state['visible'] = (bool) ($request['visible'] ?? $before['visible'] ?? true) && (int) $leechers - (int) $previousOwnSlot < $policy['download_slots'];
            }

            if ($state['active']) {
                $history['peers'][$identity['peer_id']] = ['seeder' => $state['seeder'], 'expires_at' => $expires];
            } else {
                unset($history['peers'][$identity['peer_id']]);
            }
            $history['state_version']++;
            $completed = $result['completed_delta'] && !$history['completed'] ? 1 : 0;
            $history['completed'] = $history['completed'] || $completed;
            $seedtime = 0;

            if (($request['kind'] ?? 'announce') !== 'probe') {
                if ($now - $history['last_at'] <= (int) ($policy['seedtime_max_interval'] ?? 5400)) {
                    $seedtime = max(0, min($now, $deadline) - $history['last_at']);
                }
                $history['last_at'] = $now;
            }
            $countsBefore = PeerTransition::counts($before, (bool) $policy['require_connectivity']);
            $countsAfter = PeerTransition::counts($state, (bool) $policy['require_connectivity']);
            $counts = [];

            foreach ($countsBefore as $name => $value) {
                $counts[$name] = $countsAfter[$name] - $value;
            }
            $transition = [
                'schema_version'    => 1, 'generation' => $this->lease->generation, 'identity' => $identity,
                'operation'         => $request['kind'] ?? 'announce', 'event' => $request['event'] ?? null, 'observed_at' => $now,
                'family'            => isset($request['ip']) ? EndpointAddress::observed($request['ip'], (bool) ($policy['allow_private_addresses'] ?? false))->family : null,
                'peer'              => $state, 'history' => $history, 'upload_delta' => $result['upload_delta'], 'download_delta' => $result['download_delta'],
                'credited_upload'   => Counter::percent($result['upload_delta'], (int) $credit['upload_percent']),
                'credited_download' => Counter::percent($result['download_delta'], (int) $credit['download_percent']),
                'immune'            => ($request['kind'] ?? 'announce') === 'announce' ? (bool) $credit['immune'] : null,
                'counts'            => $counts, 'completed_delta' => $completed, 'seedtime_delta' => $seedtime,
            ];
            $accepted = $redis->eval(file_get_contents(__DIR__.'/journal.lua'), \count($keys), ...[...$keys,
                $this->lease->ownerId, $ready, $oldPeer, $oldHistory, (string) $userVersion,
                json_encode($state, JSON_THROW_ON_ERROR), json_encode($history, JSON_THROW_ON_ERROR),
                json_encode($transition, JSON_THROW_ON_ERROR), (int) $policy['max_pending_transitions'], $member,
                $state['active'] && $state['visible'] && !$state['seeder'] ? $expires : 0,
                $state['active'] ? min(array_column($state['endpoints'], 'last_announced_at')) + $policy['endpoint_ttl'] : 0,
                $identity['user_id'], $identity['torrent_id'],
            ]);

            if ($accepted[0] === 'accepted') {
                return array_replace($result, ['peer' => $state, 'completed_delta' => $completed, 'transition_id' => $accepted[1]]);
            }

            if ($accepted[0] !== 'conflict') {
                if ($accepted[0] === 'removed') {
                    return ['outcome' => 'rejected', 'reason' => 'removed', 'peer' => null];
                }

                throw new RuntimeException('Transicao nao registrada: '.$accepted[0]);
            }
            usleep(random_int(500, 2000));
        }

        throw new RuntimeException('Concorrencia excessiva ao registrar a transicao; tente novamente.');
    }
}
