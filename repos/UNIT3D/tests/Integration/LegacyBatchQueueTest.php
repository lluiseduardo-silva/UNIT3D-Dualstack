<?php

declare(strict_types=1);

use Illuminate\Contracts\Console\Kernel;
use Illuminate\Database\Events\QueryExecuted;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

beforeEach(function (): void {
    if (getenv('LEGACY_BATCH_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL e Redis reais do laboratorio isolado.');
    }

    expect(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test')
        ->and(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    config(['dualstack.enabled' => false, 'cache.prefix' => 'legacy-batch-test-'.bin2hex(random_bytes(8))]);
    DB::beginTransaction();
    DB::table('peers')->whereIn('user_id', [12001, 12002])->delete();
    DB::table('history')->whereIn('user_id', [12001, 12002])->delete();
    $this->queueKey = null;
});

afterEach(function (): void {
    if (isset($this->queueKey)) {
        Redis::connection('announce')->del($this->queueKey);
    }

    if (DB::transactionLevel() > 0) {
        DB::rollBack();
    }
});

it('preserva o registro produzido enquanto um lote parcial e persistido', function (string $table, string $batch, string $command): void {
    $redis = Redis::connection('announce');
    $this->queueKey = $key = config('cache.prefix').':'.$batch.':batch';
    $row = ['user_id' => 12001, 'torrent_id' => 12001, 'agent' => 'legacy-batch-test',
        'uploaded'    => 100, 'downloaded' => 0, 'seeder' => true, 'active' => true];

    if ($table === 'peers') {
        $row += ['peer_id' => '-qB4500-000000000001', 'ip' => inet_pton('172.29.92.30'),
            'port'         => 6881, 'left' => 0, 'visible' => true, 'connectable' => false];
    } else {
        $row += ['actual_uploaded' => 100, 'actual_downloaded' => 0, 'client_uploaded' => 100,
            'client_downloaded'    => 0, 'seedtime' => 0, 'immune' => false, 'completed_at' => null];
    }
    $second = array_replace($row, ['user_id' => 12002, 'uploaded' => 200]);

    if ($table === 'history') {
        $second['actual_uploaded'] = $second['client_uploaded'] = 200;
    }
    $redis->rpush($key, serialize($row));
    $injected = false;
    DB::listen(function (QueryExecuted $query) use (&$injected, $table, $redis, $key, $second): void {
        if (!$injected && str_starts_with(strtolower($query->sql), 'insert into `'.$table.'`')) {
            $injected = true;
            // Forca a janela apos LRANGE e antes de LTRIM, usando Redis real.
            $redis->rpush($key, serialize($second));
        }
    });
    Artisan::call($command);
    $pending = (int) $redis->llen($key);
    echo json_encode(['table'       => $table, 'appended_after_read' => $injected,
        'pending_after_first_batch' => $pending, 'expected_pending' => 1])."\n";
    expect($injected)->toBeTrue()->and($pending)->toBe(1)
        ->and((int) DB::table($table)->where('user_id', 12001)->value('uploaded'))->toBe(100)
        ->and(DB::table($table)->where('user_id', 12002)->exists())->toBeFalse();
    Artisan::call($command);
    expect((int) $redis->llen($key))->toBe(0)
        ->and((int) DB::table($table)->where('user_id', 12002)->value('uploaded'))->toBe(200)
        ->and((int) DB::table($table)->where('user_id', 12001)->value('uploaded'))->toBe(100);
})->with([
    ['peers', 'peers', 'auto:upsert_peers'],
    ['history', 'histories', 'auto:upsert_histories'],
]);
