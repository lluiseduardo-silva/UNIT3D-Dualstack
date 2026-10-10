<?php

declare(strict_types=1);

use App\Services\Dualstack\TrackerLease;
use App\Services\Dualstack\TransitionJournal;
use App\Services\Dualstack\TransitionWriter;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

beforeEach(function (): void {
    if (getenv('DUALSTACK_HISTORY_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL/Redis reais, banco unit3d_dualstack_journal_test e DUALSTACK_HISTORY_TESTS=1.');
    }
    expect(DB::getDriverName())->toBe('mysql')->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::selectOne('SELECT @@transaction_isolation AS level')->level)->toBe('REPEATABLE-READ');
    expect((int) DB::selectOne('SELECT @@innodb_lock_wait_timeout AS seconds')->seconds)->toBe(10);
    expect(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    DB::table('peers')->delete();
    DB::table('history')->delete();
    DB::table('users')->update(['uploaded' => 0, 'downloaded' => 0]);
    DB::table('torrents')->update(array_fill_keys(['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6', 'times_completed'], 0));
    config(['cache.prefix' => 'dualstack-history-test:'.bin2hex(random_bytes(8)), 'dualstack.allow_private_addresses' => true]);
    $this->policy = ['endpoint_ttl' => 7200, 'max_endpoints' => 2, 'max_peers' => 3, 'min_interval' => 0,
        'allow_private_addresses'   => true, 'require_connectivity' => false, 'max_pending_transitions' => 1000];
    $this->credit = ['upload_percent' => 100, 'download_percent' => 100, 'immune' => false];
    $this->identity = ['user_id' => 12001, 'torrent_id' => 12001, 'peer_id' => bin2hex(str_repeat('J', 20))];
    $this->request = ['event' => 'started', 'ip' => '172.29.92.30', 'port' => 6881, 'uploaded' => '1000', 'downloaded' => '0', 'left' => '100', 'visible' => true, 'agent' => 'dualstack-journal-test'];
    $this->lease = TrackerLease::acquire();
    $this->writer = new TransitionWriter($this->lease);
    $this->writer->prepare();
    $this->lease->ready(true);
    $this->journal = new TransitionJournal($this->lease);
});

it('executa contrato compartilhado de historico e seedtime sem multiplicar familias', function (): void {
    $contract = json_decode(file_get_contents('/lab/fixtures/history-v1.json'), true, flags: JSON_THROW_ON_ERROR);
    $this->policy['endpoint_ttl'] = $contract['endpoint_ttl'];
    $this->policy['seedtime_max_interval'] = $contract['seedtime_max_interval'];
    $base = (int) Redis::connection('announce')->time()[0];

    foreach ($contract['operations'] as $step => $operation) {
        $id = array_replace($this->identity, ['peer_id' => bin2hex(str_repeat($operation['peer'], 20))]);
        $kind = $operation['kind'] ?? 'announce';
        $family = $operation['family'] ?? 4;
        $request = array_replace($this->request, [
            'kind'  => $kind, 'ip' => $family === 4 ? '172.29.92.30' : 'fd42:756e:6974:92::30',
            'event' => $operation['event'] ?? '', 'left' => $operation['left'] ?? '0',
            'port'  => ($operation['event'] ?? '') === 'stopped' ? 0 : 6881,
        ]);

        if ($kind === 'probe') {
            $request['revision'] = (int) DB::table('peer_ips')->where('peer_id', hex2bin($id['peer_id']))->where('family', $family)->value('revision');
            $request['connectable'] = true;
        }
        $result = $this->journal->publish($id, $request, $this->policy, $this->credit, $base + $operation['at']);
        expect($result['outcome'])->toBe(($operation['ignored'] ?? false) ? 'ignored' : 'accepted');
        $messages = $this->writer->read('history-contract');
        $this->writer->persist($messages);
        expect($this->writer->persist($messages))->toBe(0);
        $this->writer->acknowledge(array_keys($messages));
        $history = DB::table('history')->where('user_id', 12001)->where('torrent_id', 12001)->first();
        $torrent = DB::table('torrents')->find(12001);
        expect((int) $history->seedtime)->toBe($operation['seedtime'], 'step '.$step)
            ->and((bool) $history->active)->toBe($operation['seeders'] + $operation['leechers'] > 0)
            ->and((bool) $history->seeder)->toBe($operation['seeders'] > 0)
            ->and((int) $torrent->seeders)->toBe($operation['seeders'])
            ->and((int) $torrent->leechers)->toBe($operation['leechers'])
            ->and((int) $torrent->times_completed)->toBe($operation['completed'])
            ->and(DB::table('peer_ips')->count())->toBe($operation['endpoints'])
            ->and(DB::table('history')->count())->toBe(1)
            ->and((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('0');
    }
});

afterEach(function (): void {
    if (getenv('DUALSTACK_HISTORY_TESTS') !== '1' || !isset($this->lease)) {
        return;
    }
    $this->lease->release();
    $redis = Redis::connection('announce');
    $cursor = '0';

    do {
        [$cursor, $keys] = $redis->command('rawCommand', ['SCAN', $cursor, 'MATCH', TrackerLease::base().':*', 'COUNT', 1000]);

        if ($keys !== []) {
            $redis->command('rawCommand', ['UNLINK', ...$keys]);
        }
    } while ((string) $cursor !== '0');
});
