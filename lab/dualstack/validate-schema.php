<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

// O handler da aplicacao pode apenas renderizar uma excecao e terminar com zero.
// O gate do laboratorio precisa de um resultado inequívoco para automacao.
$phase = 'guard';
$report = [];
set_exception_handler(function (Throwable $error) use (&$phase, &$report): never {
    $message = $error instanceof Illuminate\Database\QueryException
        ? 'Falha SQL no ensaio; SQLSTATE '.$error->getCode()
        : $error->getMessage();
    fwrite(STDERR, json_encode(['status' => 'failed', 'phase' => $phase, 'ddl_boundaries_passed' => count($report['ddl_recovery'] ?? []), 'error' => $message], JSON_THROW_ON_ERROR)."\n");
    exit(1);
});

use Illuminate\Database\Events\QueryExecuted;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

if (DB::getDatabaseName() !== 'unit3d_dualstack_schema_test' || DB::getDriverName() !== 'mysql') {
    throw new RuntimeException('Exige banco MySQL exclusivo unit3d_dualstack_schema_test.');
}
function check(bool $condition, string $message): void
{
    if (!$condition) {
        throw new RuntimeException($message);
    }
}
$schema = file_get_contents('/app/database/schema/mysql-schema.sql');
$migrationFile = '/app/database/migrations/2026_10_08_000001_expand_dualstack_schema.php';
$report = ['status' => 'passed', 'database' => DB::selectOne('SELECT VERSION() AS version, @@transaction_isolation AS isolation_level'), 'ddl_recovery' => []];
$counter = 0;
$stopAfter = 0;
DB::listen(function (QueryExecuted $query) use (&$counter, &$stopAfter): void {
    if ($stopAfter > 0 && preg_match('/^(alter|create) table/i', $query->sql) === 1 && ++$counter === $stopAfter) {
        throw new RuntimeException('INTERRUPCAO_DDL_CONTROLADA');
    }
});

// Fronteiras depois de colunas, tabela de endpoints, checks e preferencias.
foreach ([1, 4, 5, 6, 7, 9, 14] as $boundary) {
    $phase = 'ddl-boundary-'.$boundary;
    Schema::dropIfExists('peer_ips');
    DB::unprepared($schema);
    $migration = require $migrationFile;
    $counter = 0;
    $stopAfter = $boundary;
    try {
        $migration->up();
        throw new RuntimeException('Interrupcao esperada nao ocorreu.');
    } catch (RuntimeException $error) {
        check($error->getMessage() === 'INTERRUPCAO_DDL_CONTROLADA', $error->getMessage());
    } finally {
        $stopAfter = 0;
    }
    $migration->up();
    $migration->up();
    check(Schema::hasColumn('users', 'peer_count_auto_mode'), 'Retomada nao concluiu preferencias.');
    check(Schema::hasColumn('torrents', 'leechers_ipv6'), 'Retomada nao concluiu contadores.');
    $constraints = DB::table('information_schema.TABLE_CONSTRAINTS')->where('CONSTRAINT_SCHEMA', DB::getDatabaseName())->where('TABLE_NAME', 'peer_ips')->count();
    check($constraints === 4, 'PK, FK e dois CHECKs devem existir uma unica vez.');
    $indexes = DB::select('SHOW INDEX FROM peer_ips');
    $names = array_unique(array_map(fn ($index) => $index->Key_name, $indexes));
    check(in_array('peer_ips_torrent_family_live', $names, true) && in_array('peer_ips_expiration', $names, true), 'Indices ausentes.');
    $report['ddl_recovery'][] = ['after_statement' => $boundary, 'repeated_up' => 'passed', 'constraints' => $constraints];
}

// Fixture copiada apenas de tabelas sinteticas do baseline, dentro do mesmo MySQL.
$phase = 'copy-fixture';
foreach (['groups', 'chatrooms', 'chat_statuses', 'categories', 'types', 'resolutions', 'users', 'torrents'] as $table) {
    $columns = array_column(DB::select('SHOW COLUMNS FROM `'.$table.'`'), 'Field');
    $columns = implode(',', array_map(fn ($column) => '`'.$column.'`', $columns));
    DB::statement("INSERT INTO `{$table}` ({$columns}) SELECT {$columns} FROM unit3d_baseline.`{$table}`");
}
$total = 54000;
$now = now()->toDateTimeString();
for ($start = 0; $start < $total; $start += 1000) {
    $rows = [];
    for ($i = $start; $i < $start + 1000; $i++) {
        $rows[] = [
            'user_id' => 12001 + ($i % 3), 'torrent_id' => 12001,
            'peer_id' => sprintf('schema-%013d', $i),
            'ip' => inet_pton($i % 2 === 0 ? '172.29.92.30' : 'fd42:756e:6974:92::30'),
            'port' => 6881, 'agent' => 'schema-bulk-fixture', 'uploaded' => $i,
            'downloaded' => 0, 'left' => 0, 'seeder' => true, 'active' => true,
            'visible' => true, 'created_at' => $now, 'updated_at' => $now,
        ];
    }
    DB::table('peers')->insert($rows);
}
DB::table('torrents')->where('id', 12001)->update(['seeders' => $total, 'leechers' => 0]);
config(['dualstack.enabled' => false, 'dualstack.allow_private_addresses' => true]);
$report['backfill'] = [];
foreach ([1000, 137] as $batch) {
    $phase = 'backfill-'.$batch;
    $start = hrtime(true);
    $exit = $kernel->call('dualstack:backfill', ['--offline' => true, '--batch' => $batch]);
    check($exit === 0, 'Backfill falhou: '.$kernel->output());
    $count = DB::table('peer_ips')->count();
    $torrent = DB::table('torrents')->find(12001);
    check($count === $total, 'Quantidade incorreta de endpoints.');
    check((int) $torrent->seeders === $total && (int) $torrent->seeders_ipv4 === 27000 && (int) $torrent->seeders_ipv6 === 27000, 'Contagem incorreta depois do backfill.');
    $report['backfill'][] = ['batch_size' => $batch, 'peers' => $total, 'endpoints' => $count, 'seconds' => (hrtime(true) - $start) / 1e9];
}
$report['peak_memory_bytes'] = memory_get_peak_usage(true);
$report['scope'] = 'Schema/backfill; nao representa benchmark de announce ou validacao de limites por usuario.';
echo json_encode($report, JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR)."\n";
