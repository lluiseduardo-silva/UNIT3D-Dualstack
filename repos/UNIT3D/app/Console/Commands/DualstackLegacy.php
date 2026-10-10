<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Services\Dualstack\LegacyReconciliation;
use Illuminate\Console\Command;
use RuntimeException;

final class DualstackLegacy extends Command
{
    protected $signature = 'dualstack:legacy {action : prepare ou reconcile} {--offline : Confirma entrada fechada, filas drenadas e todos os escritores interrompidos} {--batch=500}';

    protected $description = 'Prepara retorno ao legado ou reconcilia sua projecao antes de reativar dualstack';

    public function handle(LegacyReconciliation $maintenance): int
    {
        $batch = filter_var($this->option('batch'), FILTER_VALIDATE_INT, ['options' => ['min_range' => 1, 'max_range' => 2000]]);
        $action = $this->argument('action');

        if (!$this->option('offline') || config('dualstack.enabled') || $batch === false || !\in_array($action, ['prepare', 'reconcile'], true)) {
            $this->error('Use prepare ou reconcile, --offline, dualstack desativado e lote entre 1 e 2000.');

            return self::FAILURE;
        }

        try {
            $count = $maintenance->run($action, $batch);
        } catch (RuntimeException $error) {
            $this->error($error->getMessage());

            return self::FAILURE;
        }
        $this->info($action === 'prepare'
            ? 'Retorno preparado. Coordenadores novos bloqueados ate concluir reconcile.'
            : "Reconciliacao concluida: {$count} peers. Saldos e versoes preservados.");

        return self::SUCCESS;
    }
}
