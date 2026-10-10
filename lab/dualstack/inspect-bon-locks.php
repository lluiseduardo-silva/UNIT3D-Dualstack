<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use Illuminate\Support\Facades\DB;

if (DB::getDatabaseName() !== 'unit3d_dualstack_journal_test' || DB::getDriverName() !== 'mysql') {
    throw new RuntimeException('Exige MySQL do laboratorio isolado.');
}
$status = DB::selectOne('SHOW ENGINE INNODB STATUS')->Status;
preg_match('/LATEST DETECTED DEADLOCK\n(.*?)(?:\n------------\nTRANSACTIONS)/s', $status, $match);
$lines = [];
foreach (explode("\n", $match[1] ?? '') as $line) {
    // Somente tipos de operacao e locks; nunca valores das linhas ou SQL completo.
    if (str_starts_with($line, '***') || str_starts_with($line, 'RECORD LOCKS')) {
        $lines[] = $line;
    } elseif (preg_match('/^(update|insert into|delete from)\s+`?([a-z_]+)`?/i', $line, $sql)) {
        $lines[] = strtoupper($sql[1]).' '.$sql[2];
    }
}
echo json_encode(['production' => false, 'source' => 'latest_deadlock_after_legacy_control', 'lock_excerpt' => $lines], JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR)."\n";
exit($lines === [] ? 1 : 0);
