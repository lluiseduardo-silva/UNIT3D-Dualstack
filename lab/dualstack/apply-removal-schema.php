<?php
declare(strict_types=1);
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
use Illuminate\Support\Facades\DB;
if (DB::getDatabaseName() !== 'unit3d_dualstack_journal_test' || DB::getDriverName() !== 'mysql'
    || DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists()) {
    throw new RuntimeException('Exige banco isolado sem proprietario ativo.');
}
$migration = require '/app/database/migrations/2026_10_08_000005_add_dualstack_removal_state.php';
$migration->up();
$migration->up();
echo "PASS schema aditivo de remocao aplicado duas vezes\n";
