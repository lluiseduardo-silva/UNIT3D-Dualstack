<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Services\DownloadRefund;
use Illuminate\Support\Facades\DB;

function refundCheck(bool $ok, string $message): void {
    if (!$ok) { throw new RuntimeException($message); }
}
function refundWait(string $signal): void {
    $deadline = microtime(true) + 90;
    while (!is_file('/signals/'.$signal)) {
        refundCheck(microtime(true) < $deadline, 'Sinal ausente: '.$signal);
        usleep(20000);
    }
}
refundCheck(DB::getDriverName() === 'mysql' && DB::getDatabaseName() === 'unit3d_dualstack_journal_test', 'Banco incorreto');
refundCheck(!DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists(), 'Proprietario ativo');
refundCheck(DB::selectOne('SELECT @@transaction_isolation AS level')->level === 'REPEATABLE-READ', 'Isolamento divergente');
refundCheck((int)DB::selectOne('SELECT @@innodb_lock_wait_timeout AS seconds')->seconds === 10, 'Timeout divergente');
$metrics = fn () => DB::table('information_schema.INNODB_METRICS')->whereIn('NAME', ['lock_deadlocks', 'lock_timeouts', 'lock_row_lock_waits', 'lock_row_lock_time'])->pluck('COUNT', 'NAME')->all();
$before = $metrics();
$users = DB::table('users')->whereIn('id', [12001,12002,12003])->get(['id','uploaded','downloaded','group_id'])->all();
$torrents = DB::table('torrents')->whereIn('id', [12001,12002])->get(['id','size','user_id'])->all();
$uploader = DB::table('users')->whereNotIn('id', [12001,12002,12003])->orderBy('id')->value('id');
refundCheck($uploader !== null, 'Fixture exige uploader distinto dos usuarios reembolsados');
$children = $gates = [];
$report = ['status'=>'running','backend'=>'rust','production'=>false,'sql_writers'=>9,'unique_transitions'=>480,'persistence_attempts'=>1920,'refund_commands'=>160];
try {
    config(['other.refundable'=>true,'hitrun.seedtime'=>3600]);
    DB::table('peers')->delete(); DB::table('history')->delete();
    DB::table('users')->whereIn('id',[12001,12002,12003])->update(['uploaded'=>0,'downloaded'=>1000000,'group_id'=>DB::table('groups')->orderBy('id')->value('id')]);
    DB::table('torrents')->whereIn('id',[12001,12002])->update(['size'=>1000,'user_id'=>$uploader]);
    DB::table('torrents')->update(array_fill_keys(['seeders','leechers','seeders_ipv4','seeders_ipv6','leechers_ipv4','leechers_ipv6','times_completed'],0));
    file_put_contents('/signals/prepared','prepared');
    refundWait('ready');
    DB::table('history')->update(['seedtime'=>12*30*24*60*60+3600,'created_at'=>now()->subDays(2)]);
    refundCheck(DB::table('history')->count() === 6, 'Historicos ausentes');
    DB::disconnect();
    for ($worker=0; $worker<8; $worker++) {
        $sockets=stream_socket_pair(STREAM_PF_UNIX,STREAM_SOCK_STREAM,STREAM_IPPROTO_IP);
        refundCheck($sockets !== false,'Socket indisponivel');
        $pid=pcntl_fork();
        refundCheck($pid !== -1,'Fork indisponivel');
        if ($pid===0) {
            fclose($sockets[0]);
            try {
                refundCheck(fread($sockets[1],1)==='G','Barreira ausente');
                for ($i=0;$i<20;$i++) { app(DownloadRefund::class)->run(); }
                exit(0);
            } catch (Throwable $e) { fwrite(STDERR,$e::class.' codigo '.$e->getCode()."\n"); exit(1); }
        }
        fclose($sockets[1]); $children[]=$pid; $gates[]=$sockets[0];
    }
    DB::beginTransaction();
    DB::table('users')->whereIn('id',[12001,12002,12003])->orderBy('id')->lockForUpdate()->get(['id']);
    file_put_contents('/signals/go','go');
    foreach ($gates as $gate) { fwrite($gate,'G'); fclose($gate); }
    $gates=[]; $deadline=microtime(true)+5;
    do {
        $waiting=(int)DB::table('information_schema.INNODB_METRICS')->where('NAME','lock_row_lock_current_waits')->value('COUNT');
        if ($waiting>=9) { break; }
        usleep(20000);
    } while (microtime(true)<$deadline);
    DB::commit();
    foreach ($children as $key=>$pid) {
        pcntl_waitpid($pid,$status); unset($children[$key]);
        refundCheck(pcntl_wifexited($status) && pcntl_wexitstatus($status)===0,'Reembolso falhou');
    }
    refundWait('rust-done');
    $report['waiting']=$waiting; $report['before']=$before; $report['after']=$metrics();
    $report['credits']=DB::table('users')->whereIn('id',[12001,12002,12003])->orderBy('id')->get(['id','uploaded','downloaded'])->all();
    foreach ($report['credits'] as $row) {
        refundCheck((int)$row->uploaded===16000 && (int)$row->downloaded===1014000,'Credito divergente');
    }
    refundCheck((int)DB::table('history')->sum('refunded_download')===6000,'Reembolso divergente');
    refundCheck($waiting>=9,'Concorrencia nao comprovada');
    foreach (['lock_deadlocks','lock_timeouts'] as $name) { refundCheck($report['after'][$name]===$before[$name],$name.' aumentou'); }
    $report['status']='passed';
} catch (Throwable $e) {
    $report['status']='failed'; $report['error_type']=$e::class; $report['error']=$e->getMessage();
    // Only our own assertion text is safe to report; SQL exception messages may contain data.
    if ($e instanceof PDOException) {
        unset($report['error']);
        $report['sqlstate']=$e->errorInfo[0] ?? $e->getCode();
        $report['driver_code']=$e->errorInfo[1] ?? null;
        // Localizar a operacao sem exportar SQL, bindings ou credenciais.
        $report['callsite']=array_values(array_map(fn ($frame) => basename($frame['file']).':'.$frame['line'],
            array_filter($e->getTrace(), fn ($frame) => ($frame['file'] ?? null) === __FILE__)));
    }
    $report['origin']=basename($e->getFile()).':'.$e->getLine();
} finally {
    if (DB::transactionLevel()>0) { DB::rollBack(); }
    foreach ($gates as $gate) { fclose($gate); }
    foreach ($children as $pid) { posix_kill($pid,SIGTERM); pcntl_waitpid($pid,$status); }
    foreach ($users as $user) { DB::table('users')->where('id',$user->id)->update((array)$user); }
    foreach ($torrents as $torrent) { DB::table('torrents')->where('id',$torrent->id)->update((array)$torrent); }
}
echo json_encode($report,JSON_PRETTY_PRINT|JSON_THROW_ON_ERROR)."\n";
exit($report['status']==='passed' ? 0 : 1);
