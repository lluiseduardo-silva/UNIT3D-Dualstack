<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;
use RuntimeException;
use Throwable;

/** deleted_at e a intencao duravel; so o proprietario sela e remove dados do swarm. */
final class DeletedEntities
{
    public static function assertSupported(): void
    {
        if (!config('dualstack.enabled') || !config('announce.external_tracker.is_enabled')) {
            return;
        }

        try {
            $capabilities = \App\Services\Unit3dAnnounce::getCapabilities();
        } catch (Throwable) {
            $capabilities = false;
        }
        abort_unless(\is_array($capabilities) && ($capabilities['dualstack'] ?? false) === true
            && ($capabilities['coordinated_deletion'] ?? false) === true, 503, __('dualstack.deletion-unavailable'));
    }

    public static function restoreFences(TrackerLease $lease): void
    {
        foreach (['users', 'torrents'] as $table) {
            DB::table($table)->whereNotNull('deleted_at')->select('id')->orderBy('id')
                ->chunkById(500, function ($rows) use ($lease, $table): void {
                    $lease->renew();
                    Redis::connection('announce')->sAdd($lease->prefix().':deleted-'.$table, ...$rows->pluck('id')->all());
                });
        }
    }

    public function processNext(TrackerLease $lease, TransitionWriter $writer): bool
    {
        foreach (['users' => 'user_id', 'torrents' => 'torrent_id'] as $table => $column) {
            $entity = DB::table($table)->whereNotNull('deleted_at')->where('tracker_removal_state', '<', 2)->orderBy('id')->first(['id']);

            if ($entity !== null) {
                $this->removeBatch($lease, $writer, $table, $column, (int) $entity->id);

                return true;
            }
        }

        return false;
    }

    private function removeBatch(TrackerLease $lease, TransitionWriter $writer, string $table, string $column, int $id): void
    {
        $redis = Redis::connection('announce');
        // O fence e a fronteira do journal sao atomicos com os announces em voo.
        $barrier = $redis->eval(
            <<<'LUA'
if redis.call('HGET', KEYS[1], 'owner_id') ~= ARGV[1] or redis.call('GET', KEYS[2]) ~= ARGV[1] then return {'unavailable'} end
redis.call('SADD', KEYS[3], ARGV[2])
local last = redis.call('XREVRANGE', KEYS[4], '+', '-', 'COUNT', 1)
return {'ok', #last > 0 and last[1][1] or ''}
LUA,
            4,
            TrackerLease::base().':owner',
            TrackerLease::base().':heartbeat',
            $lease->prefix().':deleted-'.$table,
            TrackerLease::base().':transitions',
            $lease->ownerId,
            $id
        );

        if ($barrier[0] !== 'ok') {
            throw new RuntimeException('Propriedade perdida durante remocao.');
        }
        $deadline = hrtime(true) + 120e9;

        while ($barrier[1] !== '' && $redis->xRange(TrackerLease::base().':transitions', '-', $barrier[1], 1) !== []) {
            if (hrtime(true) >= $deadline) {
                throw new RuntimeException('Remocao aguarda transicoes confirmadas; prazo excedido.');
            }
            $lease->renew();

            if ($writer->flush('coordinator-'.$lease->ownerId, true) === 0) {
                usleep(100000);
            }
        }
        // Selado so apos commit E ack. Reentregas antigas nao podem recriar o historico.
        DB::transaction(function () use ($lease, $table, $id): void {
            $lease->assertPersistable();
            $entity = DB::table($table)->where('id', $id)->lockForUpdate()->first(['deleted_at']);

            if ($entity === null || $entity->deleted_at === null) {
                throw new RuntimeException('Entidade restaurada durante remocao; recupere o tracker.');
            }
            DB::table($table)->where('id', $id)->where('tracker_removal_state', 0)->update(['tracker_removal_state' => 1]);
        }, 3);
        $removed = DB::transaction(function () use ($lease, $table, $column, $id): array {
            $lease->assertPersistable();
            $rows = DB::table('peers')->where($column, $id)->orderBy('user_id')->orderBy('torrent_id')->orderBy('peer_id')->limit(200)->get();

            if ($rows->isNotEmpty()) {
                DB::table('users')->whereIn('id', $rows->pluck('user_id')->unique())->orderBy('id')->lockForUpdate()->get(['id']);
                DB::table('torrents')->whereIn('id', $rows->pluck('torrent_id')->unique())->orderBy('id')->lockForUpdate()->get(['id']);
                $ids = $rows->map(fn ($row) => [$row->user_id, $row->torrent_id, $row->peer_id])->all();
                $rows = TransitionWriter::tuples('peers', ['user_id', 'torrent_id', 'peer_id'], $ids)->orderBy('user_id')->orderBy('torrent_id')->orderBy('peer_id')->lockForUpdate()->get();
                $endpoints = TransitionWriter::tuples('peer_ips', ['user_id', 'torrent_id', 'peer_id'], $ids)->get()
                    ->groupBy(fn ($e) => $e->user_id.':'.$e->torrent_id.':'.bin2hex($e->peer_id));
                $deltas = [];

                foreach ($rows as $peer) {
                    $key = $peer->user_id.':'.$peer->torrent_id.':'.bin2hex($peer->peer_id);
                    $eligible = ($endpoints[$key] ?? collect())->filter(fn ($e) => !config('dualstack.require_connectivity') || $e->connectable === 1);

                    if (!$peer->active || !$peer->visible || $eligible->isEmpty()) {
                        continue;
                    }
                    $count = $peer->seeder ? 'seeders' : 'leechers';

                    foreach ([$count, ...$eligible->map(fn ($e) => $count.'_ipv'.$e->family)->all()] as $field) {
                        $deltas[$peer->torrent_id][$field] = ($deltas[$peer->torrent_id][$field] ?? 0) + 1;
                    }
                }

                if ($deltas !== []) {
                    $sets = $bindings = [];

                    foreach (['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6'] as $field) {
                        $case = $field.'='.$field.'-CASE id';

                        foreach ($deltas as $torrentId => $counts) {
                            $case .= ' WHEN ? THEN ?';
                            array_push($bindings, $torrentId, $counts[$field] ?? 0);
                        }
                        $sets[] = $case.' ELSE 0 END';
                    }
                    array_push($bindings, ...array_keys($deltas));
                    DB::update('UPDATE torrents SET '.implode(',', $sets).' WHERE id IN ('.implode(',', array_fill(0, \count($deltas), '?')).')', $bindings);
                }
                TransitionWriter::tuples('peers', ['user_id', 'torrent_id', 'peer_id'], $ids)->delete();

                return ['peers' => $ids, 'history' => []];
            }
            $rows = DB::table('history')->where($column, $id)->orderBy('user_id')->orderBy('torrent_id')->limit(200)->get(['user_id', 'torrent_id']);
            $ids = $rows->map(fn ($row) => [$row->user_id, $row->torrent_id])->all();

            if ($ids !== []) {
                TransitionWriter::tuples('history', ['user_id', 'torrent_id'], $ids)->delete();
            } else {
                DB::table($table)->where('id', $id)->update(['tracker_removal_state' => 2]);
            }

            return ['peers' => [], 'history' => $ids];
        }, 3);
        $redis->pipeline(function ($pipe) use ($lease, $removed): void {
            foreach ($removed['peers'] as [$user, $torrent, $peer]) {
                $key = $user.':'.$torrent.':'.bin2hex($peer);
                $pipe->del($lease->prefix().':peer:'.$key);
                $pipe->zRem($lease->prefix().':expiry', $key);
                $pipe->zRem($lease->prefix().':user-leechers:'.$user, $key);
            }

            foreach ($removed['history'] as [$user, $torrent]) {
                $pipe->del($lease->prefix().':history:'.$user.':'.$torrent);
            }
        });
    }
}
