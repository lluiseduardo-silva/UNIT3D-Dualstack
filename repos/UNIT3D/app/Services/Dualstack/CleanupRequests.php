<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;
use RuntimeException;

/** O site grava somente a intencao; apenas o proprietario publica transicoes. */
final class CleanupRequests
{
    public function submit(?int $userId): int
    {
        if (!config('dualstack.enabled') || config('announce.external_tracker.is_enabled')) {
            throw new CleanupRejected('dualstack.cleanup-unavailable');
        }

        return DB::transaction(function () use ($userId): int {
            // Serializa admissao, limite da fila e troca de proprietario. Sem Redis sob lock SQL.
            $owner = DB::table('tracker_ownership')->where('id', 1)
                ->lockForUpdate()->first();
            // NOW() e fixado no inicio de cada statement MySQL. Avaliar depois
            // de adquirir o lock evita aceitar uma lease que expirou na espera.
            $clock = DB::selectOne('SELECT UTC_TIMESTAMP(3) AS clock')->clock;
            $now = Carbon::parse($clock, 'UTC');

            if ($owner === null || $owner->lease_expires_at === null || $owner->backend !== 'php'
                || Carbon::parse($owner->lease_expires_at, 'UTC')->lessThanOrEqualTo($now)) {
                throw new CleanupRejected('dualstack.cleanup-unavailable');
            }
            $scope = $userId === null ? 'staff' : 'user:'.$userId;
            $existing = DB::table('tracker_cleanup_requests')->where('scope', $scope)->first(['id']);

            if ($existing !== null) {
                return (int) $existing->id;
            }

            if (DB::table('tracker_cleanup_requests')->count() >= (int) config('dualstack.max_cleanup_requests')) {
                throw new CleanupRejected('dualstack.cleanup-unavailable');
            }

            if ($userId !== null) {
                $user = DB::table('users')->where('id', $userId)->lockForUpdate()->first(['id', 'own_flushes']);

                if ($user === null || (int) $user->own_flushes <= 0) {
                    throw new CleanupRejected('dualstack.cleanup-quota');
                }
                DB::table('users')->where('id', $userId)->decrement('own_flushes');
            }

            if (!DB::table('tracker_ownership')->where('id', 1)->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists()) {
                throw new CleanupRejected('dualstack.cleanup-unavailable');
            }

            return DB::table('tracker_cleanup_requests')->insertGetId([
                'scope'      => $scope, 'user_id' => $userId,
                'cutoff'     => $now->copy()->subMinutes($userId === null ? 120 : 70),
                'created_at' => $now,
            ]);
        }, 3);
    }

    /** Um lote curto por iteracao do coordenador; nenhum cursor avanca antes do commit. */
    public function processNext(TrackerLease $lease, array $policy, bool $initializing = false): bool
    {
        $request = DB::table('tracker_cleanup_requests')->orderBy('id')->first();

        if ($request === null) {
            return false;
        }
        $candidates = DB::table('peer_ips as e')
            ->join('peers as p', fn ($join) => $join->on('p.user_id', '=', 'e.user_id')
                ->on('p.torrent_id', '=', 'e.torrent_id')->on('p.peer_id', '=', 'e.peer_id'))
            ->where('p.active', true)->where('e.last_announced_at', '<', $request->cutoff)
            ->whereExists(fn ($q) => $q->selectRaw('1')->from('users as u')->whereColumn('u.id', 'p.user_id')->whereNull('u.deleted_at'))
            ->whereExists(fn ($q) => $q->selectRaw('1')->from('torrents as t')->whereColumn('t.id', 'p.torrent_id')->whereNull('t.deleted_at'))
            ->when($request->user_id !== null, fn ($query) => $query->where('e.user_id', $request->user_id))
            ->selectRaw('/*+ MAX_EXECUTION_TIME(2000) */ e.user_id, e.torrent_id, e.peer_id')
            ->groupBy('e.user_id', 'e.torrent_id', 'e.peer_id')
            ->orderBy('e.user_id')->orderBy('e.torrent_id')->orderBy('e.peer_id')->limit(25)->get();

        if ($candidates->isEmpty()) {
            // A consulta SQL pode estar atrasada em relacao ao journal. Esperar a drenagem
            // impede confirmar uma limpeza enquanto ainda houver efeitos por persistir.
            if ((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions') === 0) {
                DB::transaction(function () use ($lease, $request): void {
                    $lease->assertPersistable();
                    DB::table('tracker_cleanup_requests')->where('id', $request->id)->delete();
                }, 3);
            }

            return true;
        }
        $journal = new TransitionJournal($lease);
        $cutoff = Carbon::parse($request->cutoff, 'UTC')->timestamp;
        $started = hrtime(true);

        foreach ($candidates as $candidate) {
            if (hrtime(true) - $started > 2e9) {
                break;
            }
            $result = $journal->publish(
                ['user_id' => (int) $candidate->user_id, 'torrent_id' => (int) $candidate->torrent_id, 'peer_id' => bin2hex($candidate->peer_id)],
                ['kind' => 'flush', 'cutoff' => $cutoff],
                $policy,
                ['upload_percent' => 100, 'download_percent' => 100, 'immune' => false],
                initializing: $initializing
            );

            if ($result['peer'] === null && ($result['reason'] ?? null) !== 'removed') {
                throw new RuntimeException('Referencia de limpeza ausente; recupere o coordenador.');
            }
        }

        return true;
    }

    public function drain(TrackerLease $lease, array $policy, TransitionWriter $writer): void
    {
        $deadline = hrtime(true) + 120e9;

        while ($this->processNext($lease, $policy, initializing: true)) {
            if (hrtime(true) >= $deadline) {
                throw new RuntimeException('Prazo de drenagem das limpezas excedido; solicitacoes preservadas.');
            }
            $lease->renew();

            if ($writer->flush('coordinator-'.$lease->ownerId) === 0) {
                usleep(100000);
            }
        }
    }
}
