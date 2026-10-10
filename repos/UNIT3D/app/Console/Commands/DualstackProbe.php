<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Services\Dualstack\EndpointProbe;
use Illuminate\Console\Command;
use Throwable;

final class DualstackProbe extends Command
{
    protected $signature = 'dualstack:probe {--once}';
    protected $description = 'Verifica portas dos endpoints fora do caminho de announce';

    public function handle(): int
    {
        if (!config('dualstack.enabled') || config('announce.external_tracker.is_enabled')) {
            $this->error('Exige dualstack standalone.');

            return self::FAILURE;
        }
        $stop = false;
        $this->trap([SIGTERM, SIGINT], function () use (&$stop): void { $stop = true; });

        try {
            do {
                $count = (new EndpointProbe())->runBatch();

                if ($count === 0 && !$this->option('once')) {
                    usleep(250000);
                }
            } while (!$stop && !$this->option('once'));

            return self::SUCCESS;
        } catch (Throwable $error) {
            $this->error('Verificador interrompido: '.$error::class.'; nenhum endpoint substituto sera alterado.');

            return self::FAILURE;
        }
    }
}
