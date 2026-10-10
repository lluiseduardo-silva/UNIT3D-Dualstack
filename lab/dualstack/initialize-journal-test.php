<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
set_exception_handler(function (Throwable $error): never {
    fwrite(STDERR, 'Preparacao falhou: '.$error::class.' codigo '.$error->getCode()."\n");
    exit(1);
});
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

if (DB::getDatabaseName() !== 'unit3d_dualstack_journal_test' || DB::getDriverName() !== 'mysql') {
    throw new RuntimeException('Exige banco de ensaio unit3d_dualstack_journal_test.');
}
$owner = Schema::hasTable('tracker_ownership') ? DB::table('tracker_ownership')->where('id', 1)->selectRaw('*, lease_expires_at > UTC_TIMESTAMP(3) AS live')->first() : null;
if ($owner?->live) {
    throw new RuntimeException('Encerre e drene o coordenador antes de restaurar a fixture.');
}
Schema::dropIfExists('peer_ips');
Schema::dropIfExists('tracker_cleanup_requests');
Schema::dropIfExists('tracker_ownership');
DB::unprepared(file_get_contents('/app/database/schema/mysql-schema.sql'));
foreach (['2026_10_08_000001_expand_dualstack_schema.php', '2026_10_08_000002_add_dualstack_journal_state.php', '2026_10_08_000003_add_dualstack_handoff_state.php', '2026_10_08_000004_add_dualstack_cleanup_requests.php', '2026_10_08_000005_add_dualstack_removal_state.php', '2026_10_08_000006_add_dualstack_legacy_reconciliation.php'] as $file) {
    $migration = require '/app/database/migrations/'.$file;
    $migration->up();
    $migration->up();
}
if ($owner !== null) {
    // A geracao nao pode retroceder em relacao ao Redis durante reexecucoes.
    DB::table('tracker_ownership')->where('id', 1)->update(['generation' => $owner->generation]);
}
foreach (['groups', 'chatrooms', 'chat_statuses', 'categories', 'types', 'resolutions', 'users', 'torrents'] as $table) {
    $columns = array_column(DB::select('SHOW COLUMNS FROM `'.$table.'`'), 'Field');
    $columns = array_values(array_diff($columns, ['tracker_removal_state']));
    $columns = implode(',', array_map(fn ($column) => '`'.$column.'`', $columns));
    DB::statement("INSERT INTO `{$table}` ({$columns}) SELECT {$columns} FROM unit3d_baseline.`{$table}`");
}
DB::table('users')->update(['uploaded' => 0, 'downloaded' => 0]);
DB::table('torrents')->update(array_fill_keys(['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6', 'times_completed'], 0));
echo "Banco exclusivo e fixtures sinteticas preparados; baseline preservado.\n";
