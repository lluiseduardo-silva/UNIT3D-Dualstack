<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();
set_exception_handler(function (Throwable $error): never {
    fwrite(STDERR, 'Ensaio legado falhou: '.$error::class.'; '.$error->getMessage()."\n");
    exit(1);
});

use App\Services\Dualstack\LegacyReconciliation;
use App\Services\Dualstack\TrackerLease;
use App\Services\Dualstack\TrackerRecovery;
use App\Services\Dualstack\TransitionJournal;
use App\Services\Dualstack\TransitionWriter;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;

function check(bool $condition, string $label): void
{
    if (!$condition) {
        throw new RuntimeException($label);
    }
}

check(DB::getDatabaseName() === 'unit3d_dualstack_journal_test', 'Exige banco isolado');
config(['cache.prefix' => 'dualstack-legacy-rehearsal', 'dualstack.enabled' => false, 'dualstack.allow_private_addresses' => true]);
$mode = $argv[1] ?? '';
check(in_array($mode, ['preflight', 'seed', 'php-resume', 'rust-preflight', 'rust-reconcile'], true), 'Fase invalida');
check((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions') === 0, 'Journal anterior pendente');
if ($mode === 'preflight') {
    echo "PASS preflight do ensaio legado\n";
    exit(0);
}
if ($mode === 'rust-preflight') {
    check((bool) DB::table('tracker_ownership')->value('legacy_reconciliation_required'), 'Prepare antes de iniciar original');
    check(!DB::table('tracker_ownership')->whereRaw('lease_expires_at>UTC_TIMESTAMP(3)')->exists(), 'Proprietario ativo');
    check((int) DB::table('users')->where('id', 12001)->value('uploaded') === 300, 'Execute primeiro o retorno PHP');
    check((int) DB::table('peers')->value('uploaded') === 1300, 'Referencia inicial divergente');
    echo "PASS estado preparado para Rust original\n";
    exit(0);
}
$maintenance = new LegacyReconciliation();
$policy = ['endpoint_ttl' => 7200, 'max_endpoints' => 2, 'max_peers' => 3, 'min_interval' => 0,
    'allow_private_addresses' => true, 'require_connectivity' => false, 'max_pending_transitions' => 1000];
$credit = ['upload_percent' => 100, 'download_percent' => 100, 'immune' => false];
$identity = ['user_id' => 12001, 'torrent_id' => 12001, 'peer_id' => bin2hex('-DS9200-000000000092')];
$request = ['event' => 'started', 'ip' => '172.29.92.30', 'port' => 6881, 'uploaded' => '1000',
    'downloaded' => '0', 'left' => '0', 'visible' => true, 'agent' => 'libtorrent/2.0.10'];
if ($mode !== 'seed') {
    $expected = $mode === 'php-resume' ? 200 : 400;
    check((int) DB::table('users')->where('id', 12001)->value('uploaded') === $expected, 'Credito depois da tag original divergente');
    check((int) DB::table('history')->where('user_id', 12001)->value('actual_uploaded') === $expected, 'Historico depois da tag original divergente');
    check(DB::table('peer_ips')->count() === 2, 'Endpoints dualstack deveriam estar desatualizados antes da reconciliacao');
    check((bool) DB::table('tracker_ownership')->value('legacy_reconciliation_required'), 'Marca de retorno ausente');
    $before = DB::table('history')->where('user_id', 12001)->first();
    $version = DB::table('peers')->value('state_version');
    check($maintenance->run('reconcile', 1) === 1, 'Reconciliacao deve ler um peer');
    check(DB::table('peer_ips')->count() === 1, 'Endereco antigo sobreviveu a reconciliacao');
    check((int) DB::table('peer_ips')->value('family') === 4, 'Familia legada incorreta');
    check(DB::table('peers')->value('state_version') === $version, 'Versao foi reiniciada');
    foreach (['uploaded', 'actual_uploaded', 'downloaded', 'actual_downloaded', 'refunded_download', 'seedtime', 'completed_at', 'state_version'] as $field) {
        check(DB::table('history')->where('user_id', 12001)->value($field) === $before->$field, 'Reconciliacao alterou '.$field);
    }
    echo "PASS {$mode}: credito {$expected}, referencias e historico preservados; endpoints 2 -> 1\n";
    if ($mode === 'rust-reconcile') {
        exit(0);
    }
}
$lease = TrackerLease::acquire();
(new TrackerRecovery($lease, $policy))->restore();
$journal = new TransitionJournal($lease);
$sequence = $mode === 'seed' ? [[4, 1000], [6, 1100]] : [[4, 1200], [6, 1300], [4, 1300]];
foreach ($sequence as [$family, $uploaded]) {
    $result = $journal->publish($identity, array_replace($request, [
        'ip' => $family === 4 ? '172.29.92.30' : 'fd42:756e:6974:92::30', 'uploaded' => (string) $uploaded,
    ]), $policy, $credit);
    check($result['outcome'] === 'accepted', 'Announce novo recusado');
}
(new TransitionWriter($lease))->flush('rehearsal');
$lease->release();
$expected = $mode === 'seed' ? 100 : 300;
check((int) DB::table('users')->where('id', 12001)->value('uploaded') === $expected, 'Credito PHP retomado divergente');
check(DB::table('peer_ips')->count() === 2, 'PHP deveria preservar dois endpoints');
$maintenance->run('prepare', 1);
echo "PASS {$mode}: PHP novo drenado com credito {$expected}; retorno ao legado preparado\n";
