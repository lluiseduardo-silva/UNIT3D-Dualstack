<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Queue;
use Illuminate\Support\Facades\Redis;
use InvalidArgumentException;
use RuntimeException;

/** Manutencao offline: binarios originais nao participam da exclusao por geracao. */
final class LegacyReconciliation
{
    public function run(string $action, int $batch): int
    {
        if (config('dualstack.enabled') || !\in_array($action, ['prepare', 'reconcile'], true) || $batch < 1 || $batch > 2000) {
            throw new RuntimeException('Manutencao exige dualstack desativado e parametros validos.');
        }
        $lock = $this->lockName();

        if ((int) DB::selectOne('SELECT GET_LOCK(?, 0) AS acquired', [$lock])->acquired !== 1) {
            throw new RuntimeException('Outra reconciliacao esta em andamento.');
        }

        try {
            $this->transaction(function () use ($action): void {
                $owner = DB::table('tracker_ownership')->where('id', 1)
                    ->selectRaw('*, lease_expires_at > UTC_TIMESTAMP(3) AS live')->lockForUpdate()->first();

                if ($owner === null || $owner->live) {
                    throw new RuntimeException('Interrompa o proprietario ativo antes da manutencao.');
                }
                $this->assertDrained();

                if ($owner->backend === 'php' && !$owner->php_journal_drained) {
                    throw new RuntimeException('Recupere e drene o journal PHP antes da manutencao.');
                }

                if ($action === 'reconcile' && !$owner->legacy_reconciliation_required) {
                    throw new RuntimeException('Execute prepare antes da reconciliacao.');
                }
                DB::table('tracker_ownership')->where('id', 1)->update(['legacy_reconciliation_required' => true]);
            });
            // A marca SQL ja impede nova aquisicao. A lease anterior expirou e nao pode renovar.
            Redis::connection('announce')->hSet(TrackerLease::base().':owner', 'ready', '0');
            Redis::connection('announce')->del(TrackerLease::base().':heartbeat');

            if ($action === 'prepare') {
                return 0;
            }
            $count = $this->reconcilePeers($batch);
            $this->reconcileHistory($batch);
            $this->reconcileCounts($batch);
            $this->assertDrained();
            $this->transaction(fn () => DB::table('tracker_ownership')->where('id', 1)->update(['legacy_reconciliation_required' => false]));

            return $count;
        } finally {
            DB::selectOne('SELECT RELEASE_LOCK(?) AS released', [$lock]);
        }
    }

    private function lockName(): string
    {
        return 'dualstack:legacy:'.substr(hash('sha256', DB::getDatabaseName()), 0, 40);
    }

    private function transaction(callable $callback): void
    {
        DB::transaction(function () use ($callback): void {
            // Uma reconexao do PDO perde GET_LOCK. Nunca continuar usando so a marca
            // de manutencao, pois outra instancia pode ter adquirido a exclusao.
            if ((int) DB::selectOne('SELECT IS_USED_LOCK(?) = CONNECTION_ID() AS held', [$this->lockName()])->held !== 1) {
                throw new RuntimeException('Conexao perdeu a exclusao da reconciliacao; mantenha offline e retome o comando.');
            }
            $callback();
        }, 3);
    }

    private function assertDrained(): void
    {
        $redis = Redis::connection('announce');

        if ($redis->xLen(TrackerLease::base().':transitions') !== 0 || Queue::connection()->size() !== 0) {
            throw new RuntimeException('Drene o journal e a fila de jobs antes da manutencao.');
        }

        foreach (['peers', 'histories', 'announces'] as $name) {
            if ($redis->lLen(config('cache.prefix').':'.$name.':batch') !== 0) {
                throw new RuntimeException('Drene os lotes legados antes da manutencao.');
            }
        }

        if (DB::table('tracker_cleanup_requests')->exists()
            || DB::table('users')->where('tracker_removal_state', 1)->exists()
            || DB::table('torrents')->where('tracker_removal_state', 1)->exists()) {
            throw new RuntimeException('Conclua limpezas e remocoes pendentes antes da manutencao.');
        }
    }

    private function reconcilePeers(int $batch): int
    {
        $cursor = null;
        $count = 0;
        $cutoff = now()->subSeconds((int) config('dualstack.endpoint_ttl'))->toDateTimeString();

        do {
            $query = DB::table('peers')->orderBy('user_id')->orderBy('torrent_id')->orderBy('peer_id')->limit($batch);

            if ($cursor !== null) {
                $query->whereRaw('(user_id, torrent_id, peer_id) > (?, ?, ?)', $cursor);
            }
            $peers = $query->get();

            if ($peers->isEmpty()) {
                break;
            }
            $last = $peers->last();
            $next = [$last->user_id, $last->torrent_id, $last->peer_id];
            $rows = [];

            foreach ($peers as $peer) {
                if (!$peer->active || ($peer->updated_at ?? '') <= $cutoff) {
                    continue;
                }

                try {
                    $address = EndpointAddress::observed(@inet_ntop($peer->ip) ?: '', (bool) config('dualstack.allow_private_addresses'));
                } catch (InvalidArgumentException) {
                    throw new RuntimeException('Peer ativo possui IP legado invalido/nao permitido; corrija a origem antes de retomar.');
                }

                if ($peer->port < 1 || $peer->port > 65535 || $peer->state_version >= PHP_INT_MAX) {
                    throw new RuntimeException('Peer ativo possui porta ou versao legada invalida.');
                }
                $rows[] = [
                    'user_id'           => $peer->user_id, 'torrent_id' => $peer->torrent_id, 'peer_id' => $peer->peer_id,
                    'family'            => $address->family, 'ip' => $address->binary, 'port' => $peer->port,
                    'connectable'       => $peer->connectable ? true : null, 'connectivity_checked_at' => null,
                    'last_announced_at' => $peer->updated_at, 'revision' => (int) $peer->state_version + 1,
                    'created_at'        => $peer->created_at, 'updated_at' => $peer->updated_at,
                ];
            }
            // Faixa da PK, nao uma consulta por peer. Um lote e seu snapshot sao atomicos.
            $this->transaction(function () use ($cursor, $next, $rows, $cutoff): void {
                $range = '(user_id, torrent_id, peer_id) <= (?, ?, ?)';
                $bindings = $next;

                if ($cursor !== null) {
                    $range .= ' AND (user_id, torrent_id, peer_id) > (?, ?, ?)';
                    $bindings = [...$bindings, ...$cursor];
                }
                DB::table('peer_ips')->whereRaw($range, $bindings)->delete();

                if ($rows !== []) {
                    DB::table('peer_ips')->insert($rows);
                }
                DB::table('peers')->whereRaw($range, $bindings)->update([
                    'protocol_state'      => null,
                    'completion_reported' => DB::raw('seeder OR EXISTS (SELECT 1 FROM history h WHERE h.user_id=peers.user_id AND h.torrent_id=peers.torrent_id AND h.completed_at IS NOT NULL)'),
                ]);
                DB::table('peers')->whereRaw($range, $bindings)->where(function ($query) use ($cutoff): void {
                    $query->where('active', false)->orWhere('updated_at', '<=', $cutoff)->orWhereNull('updated_at');
                })->update(['active' => false, 'connectable' => false]);
            });
            $count += $peers->count();
            $cursor = $next;
        } while ($peers->count() === $batch);

        return $count;
    }

    private function reconcileHistory(int $batch): void
    {
        $cursor = null;

        do {
            $query = DB::table('history')->select(['user_id', 'torrent_id'])->orderBy('user_id')->orderBy('torrent_id')->limit($batch);

            if ($cursor !== null) {
                $query->whereRaw('(user_id, torrent_id) > (?, ?)', $cursor);
            }
            $rows = $query->get();

            if ($rows->isEmpty()) {
                break;
            }
            $last = $rows->last();
            $next = [$last->user_id, $last->torrent_id];
            $update = DB::table('history')->whereRaw('(user_id, torrent_id) <= (?, ?)', $next);

            if ($cursor !== null) {
                $update->whereRaw('(user_id, torrent_id) > (?, ?)', $cursor);
            }
            // Nao creditar novamente o tempo ja contabilizado pelo escritor legado.
            $this->transaction(fn () => $update->update([
                'swarm_updated_at' => DB::raw('updated_at'),
                'active'           => DB::raw('EXISTS (SELECT 1 FROM peers p WHERE p.user_id=history.user_id AND p.torrent_id=history.torrent_id AND p.active=1)'),
                'seeder'           => DB::raw('EXISTS (SELECT 1 FROM peers p WHERE p.user_id=history.user_id AND p.torrent_id=history.torrent_id AND p.active=1 AND p.seeder=1)'),
            ]));
            $cursor = $next;
        } while ($rows->count() === $batch);
    }

    private function reconcileCounts(int $batch): void
    {
        $connectivity = config('dualstack.require_connectivity') ? ' AND e.connectable=1' : '';
        DB::table('torrents')->select('id')->orderBy('id')->chunkById($batch, function ($rows) use ($connectivity): void {
            $updates = [];

            foreach (['seeders' => 1, 'leechers' => 0] as $name => $seeder) {
                foreach (['' => '', '_ipv4' => ' AND e.family=4', '_ipv6' => ' AND e.family=6'] as $suffix => $family) {
                    $updates[$name.$suffix] = DB::raw("(SELECT COUNT(*) FROM peers p WHERE p.torrent_id=torrents.id AND p.active=1 AND p.visible=1 AND p.seeder={$seeder} AND EXISTS (SELECT 1 FROM peer_ips e WHERE e.user_id=p.user_id AND e.torrent_id=p.torrent_id AND e.peer_id=p.peer_id {$family} {$connectivity}))");
                }
            }
            $this->transaction(fn () => DB::table('torrents')->whereIn('id', $rows->pluck('id'))->update($updates));
        });
    }
}
