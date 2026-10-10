<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
set_exception_handler(function (Throwable $error): never {
    fwrite(STDERR, 'Handoff falhou: '.$error::class."\n");
    exit(1);
});

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

check(DB::getDatabaseName() === 'unit3d_dualstack_journal_test', 'Banco incorreto');
config(['cache.prefix' => 'dualstack-handoff-test', 'dualstack.allow_private_addresses' => true]);
$redis = Redis::connection('announce');
$mode = $argv[1] ?? '';
if ($mode === 'preflight') {
    check((int) $redis->xLen(TrackerLease::base().':transitions') === 0, 'Recupere o ensaio anterior antes de recriar o banco');
    echo "PASS preflight sem journal de handoff pendente\n";
    exit(0);
}
check(in_array($mode, ['pending', 'drain', 'resume'], true), 'Modo incorreto');
$policy = ['endpoint_ttl' => 7200, 'max_endpoints' => 2, 'max_peers' => 3, 'min_interval' => 0,
    'allow_private_addresses' => true, 'require_connectivity' => false, 'max_pending_transitions' => 1000];
$credit = ['upload_percent' => 100, 'download_percent' => 100, 'immune' => false];
$identity = ['user_id' => 12001, 'torrent_id' => 12001, 'peer_id' => bin2hex('-DS9200-000000000092')];
$request = ['event' => 'started', 'ip' => '172.29.92.30', 'port' => 6881, 'uploaded' => '1000',
    'downloaded' => '0', 'left' => '0', 'visible' => true, 'agent' => 'dualstack-handoff-test'];
$lease = TrackerLease::acquire();
$recovery = new TrackerRecovery($lease, $policy);
$report = $recovery->restore();
$journal = new TransitionJournal($lease);
$writer = new TransitionWriter($lease);

if ($mode === 'pending') {
    check(DB::table('peers')->count() === 0, 'Fixture deve estar vazia');
    $journal->publish($identity, $request, $policy, $credit);
    $journal->publish($identity, array_replace($request, ['ip' => 'fd42:756e:6974:92::30', 'uploaded' => '1100']), $policy, $credit);
    $lease->release();
    check(!(bool) DB::table('tracker_ownership')->where('id', 1)->value('php_journal_drained'), 'Fila pendente nao pode ser certificada');
    check((int) $redis->xLen(TrackerLease::base().':transitions') === 2, 'Duas transicoes devem permanecer');
    check((string) DB::table('users')->where('id', 12001)->value('uploaded') === '0', 'Credito prematuro');
    echo "PASS PHP fecha entrada com duas transicoes pendentes e credito SQL zero\n";
} elseif ($mode === 'drain') {
    check($report['replayed_transitions'] === 2, 'Duas transicoes devem ser recuperadas');
    check(DB::table('peer_ips')->count() === 2, 'Dois endpoints devem ser preservados');
    check((string) DB::table('users')->where('id', 12001)->value('uploaded') === '100', 'Credito da recuperacao');
    $lease->release();
    check((bool) DB::table('tracker_ownership')->where('id', 1)->value('php_journal_drained'), 'Drenagem nao certificada');
    echo "PASS PHP recupera duas transicoes, confirma credito 100 e certifica drenagem\n";
} else {
    $state = json_decode($redis->get($journal->keys($identity)[0]), true, flags: JSON_THROW_ON_ERROR);
    check($state['uploaded'] === '1200' && count($state['endpoints']) === 2, 'Restauracao depois do Rust');
    check((string) DB::table('users')->where('id', 12001)->value('uploaded') === '200', 'Credito anterior Rust');
    $result = $journal->publish($identity, array_replace($request, ['uploaded' => '1300']), $policy, $credit);
    check($result['upload_delta'] === '100', 'Delta PHP depois do Rust');
    $journal->publish($identity, array_replace($request, ['uploaded' => '1300', 'event' => 'stopped', 'port' => 0, 'ip' => 'fd42:756e:6974:92::30']), $policy, $credit);
    $recovery->drain($writer, false);
    check((string) DB::table('users')->where('id', 12001)->value('uploaded') === '300', 'Credito final PHP');
    check(DB::table('peer_ips')->count() === 1, 'Stop parcial depois da troca');
    $lease->release();
    echo "PASS Rust para PHP restaura referencias, credita somente 100 e preserva IPv4 no stop IPv6\n";
}
