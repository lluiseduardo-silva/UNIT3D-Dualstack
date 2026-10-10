<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Services\Dualstack\Policy;
use App\Services\Dualstack\CleanupRequests;
use App\Services\Dualstack\DeletedEntities;
use App\Services\Dualstack\TrackerLease;
use App\Services\Dualstack\TrackerRecovery;
use App\Services\Dualstack\TransitionWriter;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\Redis;
use RuntimeException;
use Throwable;

final class DualstackWork extends Command
{
    protected $signature = 'dualstack:work {--once : Recupera, drena e encerra sem manter a entrada aberta}';

    protected $description = 'Coordena o journal standalone, a propriedade e a expiracao dos endpoints';

    public function handle(): int
    {
        if (!config('dualstack.enabled') || config('announce.external_tracker.is_enabled')) {
            $this->error('Exige dualstack ativo e processamento PHP standalone.');

            return self::FAILURE;
        }
        $lease = null;
        $stopping = false;

        if (\function_exists('pcntl_async_signals')) {
            pcntl_async_signals(true);
            $this->trap([SIGTERM, SIGINT], function () use (&$stopping): void { $stopping = true; });
        }

        try {
            foreach (['peers', 'histories'] as $queue) {
                if ((int) Redis::connection('announce')->lLen(config('cache.prefix').':'.$queue.':batch') > 0) {
                    throw new RuntimeException('Drene as filas legadas antes de iniciar dualstack.');
                }
            }
            $policy = Policy::configured();
            $lease = TrackerLease::acquire();
            $recovery = new TrackerRecovery($lease, $policy);
            $report = $recovery->restore();
            $writer = new TransitionWriter($lease);
            $cleanups = new CleanupRequests();
            $deletions = new DeletedEntities();
            $this->info(json_encode(['generation' => $lease->generation] + $report, JSON_THROW_ON_ERROR));
            $renewAt = $expireAt = $retireAt = $cleanupAt = $deletionAt = hrtime(true);

            while (!$stopping && !$this->option('once')) {
                $now = hrtime(true);

                if ($now >= $renewAt) {
                    $lease->renew();
                    $renewAt = $now + 5e9;
                }

                if (Redis::connection('announce')->hGet(TrackerLease::base().':owner', 'ready') !== '1') {
                    throw new RuntimeException('Journal exige recuperacao; entrada foi fechada.');
                }

                if ($now >= $expireAt) {
                    $processed = $recovery->expire();
                    $expireAt = $processed === 200 ? $now : $now + 60e9;
                }

                if ($now >= $deletionAt) {
                    $deletionAt = $deletions->processNext($lease, $writer) ? $now : $now + 5e9;
                }

                if ($now >= $retireAt) {
                    $retired = $recovery->retire();
                    $retireAt = $retired === 200 ? $now + 60e9 : $now + 3600e9;
                }

                if ($now >= $cleanupAt) {
                    $cleanupAt = $cleanups->processNext($lease, $policy) ? $now : $now + 5e9;
                }

                if ($writer->flush('coordinator-'.$lease->ownerId) === 0) {
                    usleep(100000);
                }
            }
            $lease->ready(false);
            $deletionDeadline = hrtime(true) + 120e9;

            while ($deletions->processNext($lease, $writer)) {
                if (hrtime(true) >= $deletionDeadline) {
                    throw new RuntimeException('Prazo de remocao excedido; estado preservado.');
                }
                $lease->renew();
            }
            $cleanups->drain($lease, $policy, $writer);
            $recovery->drain($writer, true);
            $lease->release();

            return self::SUCCESS;
        } catch (Throwable $error) {
            // Nao imprimir SQL/payload/passkeys. O supervisor pode reiniciar;
            // a proxima geracao recupera mensagens nao reconhecidas.
            $this->error('Coordenador interrompido: '.$error::class.'; transicoes pendentes preservadas.');

            if ($lease !== null) {
                try {
                    $lease->release();
                } catch (Throwable) { /* Lease expira sem renovacao. */
                }
            }

            return self::FAILURE;
        }
    }
}
