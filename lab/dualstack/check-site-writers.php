<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
set_exception_handler(function (Throwable $error): never {
    fwrite(STDERR, 'Diagnostico falhou: '.$error::class.' codigo '.$error->getCode()."\n");
    exit(2);
});

use App\Http\Controllers\Staff\FlushController;
use App\Http\Controllers\User\PeerController;
use App\Models\User;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\DB;

if (DB::getDatabaseName() !== 'unit3d_dualstack_journal_test' || DB::getDriverName() !== 'mysql') {
    throw new RuntimeException('Exige banco isolado de ensaio.');
}
if (DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists()) {
    throw new RuntimeException('Encerre e drene o coordenador antes do diagnostico.');
}
config(['dualstack.enabled' => true, 'announce.external_tracker.is_enabled' => false, 'cache.default' => 'array']);
$results = [];
foreach (['user_flush', 'staff_flush'] as $action) {
    DB::beginTransaction();
    try {
        $identity = ['user_id' => 12001, 'torrent_id' => 12001, 'peer_id' => str_repeat('W', 20)];
        DB::table('peers')->where('user_id', 12001)->delete();
        DB::table('peers')->insert($identity + [
            'ip' => inet_pton('172.29.92.30'), 'port' => 6881, 'agent' => 'writer-diagnostic',
            'uploaded' => 1000, 'downloaded' => 0, 'left' => 0, 'seeder' => true,
            'active' => true, 'visible' => true, 'created_at' => now()->subHours(3), 'updated_at' => now()->subHours(3),
        ]);
        foreach ([4 => '172.29.92.30', 6 => 'fd42:756e:6974:92::30'] as $family => $ip) {
            DB::table('peer_ips')->insert($identity + ['family' => $family, 'ip' => inet_pton($ip), 'port' => 6881,
                'last_announced_at' => now()->subHours(3), 'revision' => 1]);
        }
        DB::table('history')->updateOrInsert(['user_id' => 12001, 'torrent_id' => 12001], [
            'agent' => 'writer-diagnostic', 'client_uploaded' => 1000, 'client_downloaded' => 0,
            'active' => true, 'seeder' => true, 'immune' => false,
            'created_at' => now()->subHours(3), 'updated_at' => now()->subHours(3),
        ]);
        DB::table('users')->where('id', 12001)->update(['own_flushes' => 2]);
        $user = User::findOrFail(12001);
        Auth::guard()->setUser($user);
        $request = Request::create('/lab/flush', 'DELETE');
        $request->setUserResolver(fn () => $user);
        $snapshot = fn () => [
            'peers' => DB::table('peers')->where($identity)->count(),
            'endpoints' => DB::table('peer_ips')->where($identity)->count(),
            'history_active' => (bool) DB::table('history')->where('user_id', 12001)->where('torrent_id', 12001)->value('active'),
            'own_flushes' => (int) DB::table('users')->where('id', 12001)->value('own_flushes'),
        ];
        $before = $snapshot();
        if ($action === 'user_flush') {
            app(PeerController::class)->massDestroy($request, $user);
        } else {
            app(FlushController::class)->peers();
        }
        $after = $snapshot();
        $results[] = ['action' => $action, 'before' => $before, 'after' => $after,
            'criterion' => 'site must not persist peer state outside the coordinator',
            'passed' => $before === $after];
    } finally {
        DB::rollBack();
    }
}
echo json_encode(['dualstack' => true, 'external_tracker' => false, 'transaction_rolled_back' => true, 'checks' => $results], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES)."\n";
exit(array_filter($results, fn ($result) => !$result['passed']) === [] ? 0 : 1);
