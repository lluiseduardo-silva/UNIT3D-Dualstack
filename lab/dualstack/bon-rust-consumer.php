<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use Illuminate\Contracts\Console\Kernel;
use Illuminate\Support\Facades\DB;

function bonCheck(bool $value, string $message): void {
    if (!$value) { throw new RuntimeException($message); }
}
function bonWait(string $signal): void {
    $deadline = microtime(true) + 60;
    while (!is_file('/signals/'.$signal)) {
        bonCheck(microtime(true) < $deadline, 'Sinal Rust ausente: '.$signal);
        usleep(20000);
    }
}
bonCheck(DB::getDriverName() === 'mysql' && DB::getDatabaseName() === 'unit3d_dualstack_journal_test', 'Banco incorreto');
bonCheck(!DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists(), 'Proprietario ativo');
$rules = DB::table('bon_earnings')->get()->map(fn ($r) => (array) $r)->all();
$conditions = DB::table('bon_earning_conditions')->get()->map(fn ($r) => (array) $r)->all();
$balances = DB::table('users')->pluck('seedbonus', 'id')->all();
$metrics = fn () => DB::table('information_schema.INNODB_METRICS')->whereIn('NAME', ['lock_deadlocks', 'lock_timeouts'])->pluck('COUNT', 'NAME')->all();
$before = $metrics();
$child = null;
$report = ['status' => 'running', 'production' => false, 'backend' => 'rust'];
$expectedWaits = 2; // persist_batch serializa as quatro tarefas Rust; mais o BON.
try {
    config(['dualstack.enabled' => true, 'dualstack.endpoint_ttl' => 7200]);
    DB::table('peers')->delete(); DB::table('history')->delete();
    DB::table('users')->update(['uploaded' => 0, 'downloaded' => 0]);
    DB::table('torrents')->update(array_fill_keys(['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6', 'times_completed'], 0));
    DB::table('bon_earnings')->delete();
    $rule = DB::table('bon_earnings')->insertGetId(['position'=>1,'variable'=>'1','multiplier'=>10,'operation'=>'append','name'=>'BON Rust','description'=>'Fixture isolada']);
    DB::table('bon_earning_conditions')->insert(['bon_earning_id'=>$rule,'operand1'=>'connectable','operator'=>'=','operand2'=>1]);
    file_put_contents('/signals/prepared', 'prepared');
    bonWait('ready');
    bonCheck(DB::table('peer_ips')->where('connectable', true)->count() === 6, 'Probe IPv6 ausente');
    DB::disconnect();
    $sockets = stream_socket_pair(STREAM_PF_UNIX, STREAM_SOCK_STREAM, STREAM_IPPROTO_IP);
    bonCheck($sockets !== false, 'Socket indisponivel');
    $child = pcntl_fork();
    bonCheck($child !== -1, 'Fork indisponivel');
    if ($child === 0) {
        fclose($sockets[0]);
        try {
            bonCheck(fread($sockets[1], 1) === 'G', 'Barreira ausente');
            for ($i=0; $i<5; $i++) { app(Kernel::class)->call('auto:bon_allocation'); }
            exit(0);
        } catch (Throwable $e) { fwrite(STDERR, $e::class.' codigo '.$e->getCode()."\n"); exit(1); }
    }
    fclose($sockets[1]);
    DB::beginTransaction();
    DB::table('users')->whereIn('id', [12001,12002,12003])->orderBy('id')->lockForUpdate()->get(['id']);
    file_put_contents('/signals/go', 'go');
    fwrite($sockets[0], 'G'); fclose($sockets[0]);
    $deadline = microtime(true)+5;
    do {
        $waiting = (int) DB::table('information_schema.INNODB_METRICS')->where('NAME','lock_row_lock_current_waits')->value('COUNT');
        if ($waiting >= $expectedWaits) { break; }
        usleep(20000);
    } while (microtime(true)<$deadline);
    DB::commit();
    pcntl_waitpid($child, $status); $child = null;
    bonCheck(pcntl_wifexited($status) && pcntl_wexitstatus($status) === 0, 'Consumidor BON falhou');
    bonWait('rust-done');
    $report['waiting'] = $waiting;
    $report['expected_sql_writers'] = $expectedWaits;
    $report['before'] = $before; $report['after'] = $metrics();
    foreach ([12001,12002,12003] as $id) {
        $row=DB::table('users')->find($id);
        $delta=(float)$row->seedbonus-(float)$balances[$id];
        $report['credits'][$id]=['uploaded'=>(string)$row->uploaded,'bon_delta'=>$delta];
        bonCheck((string)$row->uploaded === '800' && $delta === 100.0, 'Credito divergente');
    }
    bonCheck($waiting >= $expectedWaits && $report['after'] === $before, 'Contencao divergente');
    $report['status']='passed';
} catch (Throwable $e) {
    $report['status']='failed'; $report['error_type']=$e::class;
    $report['error_code']=$e->getCode(); $report['origin']=basename($e->getFile()).':'.$e->getLine();
} finally {
    if (DB::transactionLevel()>0) { DB::rollBack(); }
    if ($child !== null && $child>0) { pcntl_waitpid($child, $status); }
    DB::table('bon_earnings')->delete();
    if ($rules !== []) { DB::table('bon_earnings')->insert($rules); }
    if ($conditions !== []) { DB::table('bon_earning_conditions')->insert($conditions); }
    foreach ($balances as $id=>$balance) { DB::table('users')->where('id',$id)->update(['seedbonus'=>$balance]); }
}
echo json_encode($report, JSON_PRETTY_PRINT|JSON_THROW_ON_ERROR)."\n";
exit($report['status']==='passed' ? 0 : 1);
