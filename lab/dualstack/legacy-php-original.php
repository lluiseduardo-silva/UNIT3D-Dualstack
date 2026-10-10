<?php

declare(strict_types=1);

// Executado com /app apontando para o git archive exato da tag 9.2.0.
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();
use App\DTO\AnnounceGroupDTO;
use App\DTO\AnnounceQueryDTO;
use App\DTO\AnnounceTorrentDTO;
use App\DTO\AnnounceUserDTO;
use App\Jobs\ProcessAnnounce;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;

if (DB::getDatabaseName() !== 'unit3d_dualstack_journal_test'
    || !DB::table('tracker_ownership')->value('legacy_reconciliation_required')
    || DB::table('tracker_ownership')->whereRaw('lease_expires_at>UTC_TIMESTAMP(3)')->exists()) {
    throw new RuntimeException('Exige banco isolado preparado para rollback.');
}
config(['cache.prefix' => 'dualstack-legacy-rehearsal', 'announce.connectable_check' => false,
    'announce.log_announces' => false, 'other.doubleup' => false, 'other.freeleech' => false]);
$version = DB::table('peers')->value('state_version');
$query = new AnnounceQueryDTO(6881, 1200, 0, 0, 0, 0, '', '', 'libtorrent/2.0.10',
    DB::table('torrents')->where('id', 12001)->value('info_hash'), '-DS9200-000000000092', inet_pton('172.29.92.30'));
(new ProcessAnnounce($query, new AnnounceUserDTO(12001, false, new AnnounceGroupDTO(false, false, false)), new AnnounceTorrentDTO(12001, 0, false), true))->handle();
foreach (['auto:upsert_peers', 'auto:upsert_histories', 'auto:upsert_announces'] as $command) {
    if ($kernel->call($command) !== 0) {
        throw new RuntimeException('Consumidor original falhou: '.$command);
    }
}
foreach (['peers', 'histories', 'announces'] as $queue) {
    if (Redis::connection('announce')->lLen(config('cache.prefix').':'.$queue.':batch') !== 0) {
        throw new RuntimeException('Fila legada nao drenada');
    }
}
if ((int) DB::table('users')->where('id', 12001)->value('uploaded') !== 200
    || (int) DB::table('history')->where('user_id', 12001)->value('actual_uploaded') !== 200
    || DB::table('peers')->value('state_version') !== $version) {
    throw new RuntimeException('Contabilidade/versao apos PHP 9.2.0 divergente');
}
echo "PASS PHP 9.2.0 original: ProcessAnnounce e consumidores drenados; credito 100 -> 200\n";
