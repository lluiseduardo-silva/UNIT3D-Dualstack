<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Http\Controllers\ExternalTorrentController;
use App\Models\Torrent;
use App\Services\Dualstack\Counter;
use App\Services\Unit3dAnnounce;
use Illuminate\Support\Facades\DB;

set_exception_handler(function (Throwable $error): never {
    fwrite(STDERR, 'Validacao administrativa falhou: '.$error::class.' codigo '.$error->getCode()."\n");
    exit(1);
});

function check(bool $condition, string $message): void
{
    if (!$condition) {
        throw new RuntimeException($message);
    }
}

check(DB::getDatabaseName() === 'unit3d_dualstack_journal_test', 'Exige banco isolado.');
$env = [];

foreach (file('/run/rust-candidate.env', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
    if (str_contains($line, '=')) {
        [$key, $value] = explode('=', $line, 2);
        $env[$key] = $value;
    }
}
config(['announce.external_tracker' => ['is_enabled' => true, 'host' => '172.29.92.10', 'port' => 8080, 'unix_socket' => null, 'key' => $env['APIKEY']]]);
unset($env);

if (isset($argv[1])) {
    check(in_array($argv[1], ['free-double', 'normal'], true), 'Perfil de fatores invalido.');
    $model = Torrent::findOrFail(12002);
    $model->doubleup = $argv[1] === 'free-double';
    $model->free = $argv[1] === 'free-double' ? 100 : 0;
    check(Unit3dAnnounce::addTorrent($model), 'Atualizacao de fatores recusada.');
    $torrent = Unit3dAnnounce::getTorrent(12002);
    check($torrent['upload_factor'] === ($model->doubleup ? 200 : 100) && $torrent['download_factor'] === 100 - $model->free, 'Fatores nao atualizados.');
    echo json_encode(['status' => 'passed', 'profile' => $argv[1], 'upload_factor' => $torrent['upload_factor'], 'download_factor' => $torrent['download_factor']], JSON_THROW_ON_ERROR)."\n";
    exit(0);
}

$capabilities = Unit3dAnnounce::getCapabilities();
check(is_array($capabilities) && $capabilities['dualstack'] === true && $capabilities['peer_schema'] === 1, 'Capacidade dualstack nao reconhecida.');
$torrent = Unit3dAnnounce::getTorrent(12001);
check(is_array($torrent) && count($torrent['peers'] ?? []) === 6, 'Exige os seis peers do contrato HTTP.');
$key = '12004-'.bin2hex('-DS9200-000000000005');
check($torrent['peers'][$key]['uploaded'] === Counter::MAX, 'uint64 perdeu precisao.');
check(count($torrent['peers'][$key]['endpoints']) === 2, 'Peer dualstack perdeu endpoint.');
$user = Unit3dAnnounce::getUser(12001);
check(is_array($user) && $user['num_seeding'] === 1 && $user['num_leeching'] === 3, 'Contadores por usuario divergentes.');
unset($user); // A resposta de usuario contem passkey e nunca e exportada.

$model = Torrent::findOrFail(12001);
$model->seeders = 0;
$model->leechers = 0;
$model->times_completed = 0;
check(Unit3dAnnounce::addTorrent($model), 'Refresh administrativo recusado.');
$after = Unit3dAnnounce::getTorrent(12001);
foreach (['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6', 'times_completed', 'peers'] as $field) {
    check($after[$field] === $torrent[$field], 'Refresh sobrescreveu estado corrente: '.$field);
}

DB::enableQueryLog();
DB::flushQueryLog();
$data = app(ExternalTorrentController::class)->show(12001)->getData();
$queries = count(DB::getQueryLog());
DB::disableQueryLog();
check($queries <= 6 && $data['peerUsers']->count() === 4, 'Usuarios devem ser carregados em lote.');
$compiler = app('blade.compiler');
$compiler->compile(resource_path('views/torrent/external-tracker.blade.php'));
echo json_encode([
    'status' => 'passed', 'capabilities' => $capabilities, 'logical_peers' => count($torrent['peers']),
    'endpoints' => array_sum(array_map(fn ($peer) => count($peer['endpoints']), $torrent['peers'])),
    'uint64' => $torrent['peers'][$key]['uploaded'], 'user_counts' => ['seeding' => 1, 'leeching' => 3],
    'controller_queries' => $queries, 'peer_users_loaded' => $data['peerUsers']->count(),
    'metadata_refresh_preserved_swarm' => true, 'view_compiled' => true,
], JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR)."\n";
