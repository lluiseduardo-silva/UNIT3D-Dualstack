<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Http\Controllers\TorrentController;
use App\Models\Group;
use App\Models\User;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Notification;
use Illuminate\Support\Facades\Queue;

set_exception_handler(function (Throwable $error): never {
    // Nao exportar mensagens SQL, URLs autenticadas ou modelos de usuario.
    fwrite(STDERR, 'DELETION_HTTP_FAILED '.$error::class.' code='.$error->getCode()."\n");
    exit(1);
});

function check(bool $condition, string $message): void
{
    if (!$condition) {
        throw new RuntimeException($message);
    }
}

$backend = $argv[1] ?? '';
check(in_array($backend, ['php-standalone', 'rust'], true), 'Backend invalido.');
check(DB::getDatabaseName() === 'unit3d_dualstack_journal_test', 'Exige banco isolado.');
config(['dualstack.enabled' => true]);
if ($backend === 'rust') {
    $env = [];
    foreach (file('/run/rust-candidate.env', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_contains($line, '=')) {
            [$key, $value] = explode('=', $line, 2);
            $env[$key] = $value;
        }
    }
    config(['announce.external_tracker' => ['is_enabled' => true, 'host' => '172.29.92.10', 'port' => 8080, 'unix_socket' => null, 'key' => $env['APIKEY']]]);
    unset($env);
} else {
    config(['announce.external_tracker.is_enabled' => false]);
}
Notification::fake();
Queue::fake();
$admin = User::findOrFail(12002);
$admin->setRelation('group', new Group(['is_modo' => true]));
auth()->setUser($admin);
$request = Request::create('/lab/remove', 'DELETE', ['message' => 'ensaio dualstack isolado']);
$request->setUserResolver(fn () => $admin);
$credits = fn () => DB::table('users')->whereBetween('id', [12001, 12020])->orderBy('id')->get(['id', 'uploaded', 'downloaded'])->toJson();
$other = fn () => DB::table('peers')->where('torrent_id', 12002)->orderBy('user_id')->orderBy('peer_id')->get()->toJson(JSON_INVALID_UTF8_SUBSTITUTE);
$beforeCredits = $credits();
$beforeOther = $other();
$peerCount = DB::table('peers')->where('torrent_id', 12001)->count();
check($peerCount === 6, 'Exige os seis peers do contrato HTTP.');
app(TorrentController::class)->destroy($request, 12001);
$deadline = microtime(true) + 30;
while ((int) DB::table('torrents')->where('id', 12001)->value('tracker_removal_state') !== 2) {
    check(microtime(true) < $deadline, 'Coordenador nao concluiu a exclusao.');
    usleep(100000);
}
foreach (['peers', 'peer_ips', 'history'] as $table) {
    check(DB::table($table)->where('torrent_id', 12001)->count() === 0, 'Linhas residuais: '.$table);
}
check($credits() === $beforeCredits, 'Exclusao alterou credito confirmado.');
check($other() === $beforeOther, 'Exclusao alterou outro torrent.');
echo json_encode(['status' => 'passed', 'backend' => $backend, 'removed_logical_peers' => $peerCount,
    'removal_state' => 2, 'remaining_endpoints' => 0, 'remaining_history' => 0,
    'credits_preserved' => true, 'other_torrent_preserved' => true], JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR)."\n";
