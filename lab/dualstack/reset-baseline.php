<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
if (config('database.connections.mysql.database') !== 'unit3d_baseline'
    || App\Models\User::query()->whereNotBetween('id', [12001, 12006])->exists()) {
    throw new RuntimeException('Reset recusado: banco nao corresponde ao fixture isolado.');
}
foreach (['peers', 'histories', 'announces'] as $queue) {
    if (Illuminate\Support\Facades\Redis::connection('announce')->llen(config('cache.prefix').':'.$queue.':batch') !== 0) {
        throw new RuntimeException('Reset recusado: fila pendente '.$queue);
    }
}
if (app('queue')->size() !== 0 || Illuminate\Support\Facades\DB::table('failed_jobs')->exists()) {
    throw new RuntimeException('Reset recusado: jobs pendentes ou falhos.');
}
Illuminate\Support\Facades\DB::transaction(function (): void {
    Illuminate\Support\Facades\DB::table('peers')->delete();
    Illuminate\Support\Facades\DB::table('history')->delete();
    Illuminate\Support\Facades\DB::table('users')->update(['uploaded' => 0, 'downloaded' => 0]);
    Illuminate\Support\Facades\DB::table('torrents')->update(['seeders' => 0, 'leechers' => 0, 'times_completed' => 0]);
});
// Redis exclusivo das VMs deste laboratorio; nunca executar contra Redis compartilhado.
foreach (['default', 'cache', 'job', 'announce'] as $connection) {
    Illuminate\Support\Facades\Redis::connection($connection)->flushdb();
}
echo "Estado do fixture original restaurado.\n";
