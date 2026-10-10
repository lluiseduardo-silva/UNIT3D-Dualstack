<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
set_exception_handler(function (Throwable $error): never {
    fwrite(STDERR, 'Ciclo de limpeza falhou: '.$error::class.' codigo '.$error->getCode()."\n");
    exit(1);
});

use App\Http\Controllers\User\PeerController;
use App\Models\User;
use App\Services\Dualstack\Policy;
use App\Services\Dualstack\TrackerLease;
use App\Services\Dualstack\TrackerRecovery;
use App\Services\Dualstack\TransitionJournal;
use App\Services\Dualstack\TransitionWriter;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;

function checkCleanup(bool $value, string $label): void
{
    if (!$value) {
        throw new RuntimeException($label);
    }
}
function awaitCleanup(callable $check): void
{
    $deadline = hrtime(true) + 15e9;
    while (!$check()) {
        if (hrtime(true) > $deadline) {
            throw new RuntimeException('Timeout de verificacao.');
        }
        usleep(100000);
    }
}
checkCleanup(DB::getDatabaseName() === 'unit3d_dualstack_journal_test' && DB::getDriverName() === 'mysql', 'Banco incorreto');
$mode = $argv[1] ?? '';
checkCleanup(in_array($mode, ['preflight', 'pending', 'verify-once', 'live', 'verify-stop'], true), 'Modo incorreto');
$redis = Redis::connection('announce');
if ($mode === 'preflight') {
    checkCleanup(!app()->runningUnitTests() && extension_loaded('pcntl'), 'Sinais devem estar habilitados no ensaio do daemon');
    checkCleanup(!DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists(), 'Proprietario ativo');
    checkCleanup(DB::table('tracker_cleanup_requests')->count() === 0, 'Recupere as limpezas pendentes antes de recriar as fixtures');
    checkCleanup((int) $redis->xLen(TrackerLease::base().':transitions') === 0, 'Recupere o journal antes de recriar as fixtures');
    echo "PASS preflight sem proprietario ou transicoes pendentes; sinais habilitados\n";
    exit(0);
}
if (in_array($mode, ['verify-once', 'verify-stop'], true)) {
    checkCleanup(DB::table('tracker_cleanup_requests')->count() === 0, 'Fila nao drenada');
    $owner = DB::table('tracker_ownership')->where('id', 1)->first();
    checkCleanup($owner->lease_expires_at === null && (bool) $owner->php_journal_drained, 'Drenagem nao certificada');
    $userId = $mode === 'verify-once' ? 12001 : 12002;
    checkCleanup(DB::table('peers')->where('user_id', $userId)->count() === 1, 'Referencia perdida');
    checkCleanup((string) DB::table('users')->where('id', $userId)->value('uploaded') === ($mode === 'verify-once' ? '0' : '100'), 'Credito incorreto');
    checkCleanup(DB::table('peer_ips')->where('user_id', $userId)->count() === ($mode === 'verify-once' ? 1 : 2), 'Endpoints incorretos');
    echo 'PASS '.$mode." com limpeza drenada, referencia preservada e credito correto\n";
    exit(0);
}
$policy = array_replace(Policy::configured(), ['min_interval' => 0]);
$credit = ['upload_percent' => 100, 'download_percent' => 100, 'immune' => false];
if ($mode === 'pending') {
    $lease = TrackerLease::acquire();
    $recovery = new TrackerRecovery($lease, $policy);
    $recovery->restore();
} else {
    awaitCleanup(fn () => $redis->hGet(TrackerLease::base().':owner', 'ready') === '1');
    $lease = TrackerLease::current();
}
$journal = new TransitionJournal($lease);
$userId = $mode === 'pending' ? 12001 : 12002;
DB::table('users')->where('id', $userId)->update(['own_flushes' => 2]);
$identity = ['user_id' => $userId, 'torrent_id' => 12001, 'peer_id' => bin2hex('-DS9200-000000000092')];
$request = ['event' => 'started', 'ip' => '172.29.92.30', 'port' => 6881, 'uploaded' => '1000', 'downloaded' => '0', 'left' => '0', 'visible' => true, 'agent' => 'cleanup-lifecycle'];
$now = (int) $redis->time()[0];
$journal->publish($identity, $request, $policy, $credit, $now - 4300);
$journal->publish($identity, array_replace($request, ['ip' => 'fd42:756e:6974:92::30']), $policy, $credit, $now - 5);
if ($mode === 'pending') {
    $recovery->drain(new TransitionWriter($lease), false);
} else {
    awaitCleanup(fn () => DB::table('peer_ips')->where('user_id', $userId)->count() === 2);
}
$http = Request::create('/lab/flush', 'DELETE');
$user = User::findOrFail($userId);
$http->setUserResolver(fn () => $user);
$response = app(PeerController::class)->massDestroy($http, $user);
checkCleanup($response->getSession()->get('success') === __('dualstack.cleanup-queued'), 'Solicitacao recusada');
checkCleanup((int) DB::table('users')->where('id', $userId)->value('own_flushes') === 1, 'Cota incorreta');
if ($mode === 'pending') {
    $lease->release();
    checkCleanup(DB::table('tracker_cleanup_requests')->count() === 1, 'Pedido pendente perdido');
    checkCleanup((int) $redis->xLen(TrackerLease::base().':transitions') === 0, 'Journal deve estar vazio neste ensaio');
    checkCleanup(!(bool) DB::table('tracker_ownership')->value('php_journal_drained'), 'Handoff prematuro');
    echo "PASS limpeza pendente bloqueia handoff mesmo com journal vazio\n";
} else {
    awaitCleanup(fn () => DB::table('tracker_cleanup_requests')->count() === 0);
    checkCleanup(DB::table('peer_ips')->where('user_id', $userId)->pluck('family')->map(fn ($v) => (int) $v)->all() === [6], 'Flush parcial incorreto');
    $request['event'] = '';
    $request['uploaded'] = '1100';
    $journal->publish($identity, $request, $policy, $credit);
    $journal->publish($identity, array_replace($request, ['ip' => 'fd42:756e:6974:92::30']), $policy, $credit);
    awaitCleanup(fn () => (int) $redis->xLen(TrackerLease::base().':transitions') === 0);
    checkCleanup((string) DB::table('users')->where('id', $userId)->value('uploaded') === '100', 'Credito duplicado');
    echo "PASS daemon processa limpeza e novos announces sem perder endpoint IPv6 ou duplicar credito\n";
}
