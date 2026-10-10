<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
set_exception_handler(function (Throwable $error): never {
    fwrite(STDERR, 'Migracao de ensaio falhou: '.$error::class."\n");
    exit(1);
});

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

if (DB::getDatabaseName() !== 'unit3d_dualstack_journal_test' || DB::getDriverName() !== 'mysql') {
    throw new RuntimeException('Exige banco MySQL isolado.');
}
$before = DB::table('tracker_ownership')->where('id', 1)->selectRaw('*, lease_expires_at > UTC_TIMESTAMP(3) AS live')->first();
if ($before->live) {
    throw new RuntimeException('Encerre o proprietario antes de aplicar a migracao.');
}
$migration = require '/app/database/migrations/2026_10_08_000003_add_dualstack_handoff_state.php';
$migration->up();
$migration->up();
$after = DB::table('tracker_ownership')->where('id', 1)->first();
if (!Schema::hasColumn('tracker_ownership', 'php_journal_drained') || $before->generation !== $after->generation || $before->owner_id !== $after->owner_id) {
    throw new RuntimeException('Migracao alterou identidade/geracao.');
}
echo "PASS migracao aditiva reexecutada sem alterar proprietario ou geracao\n";
