<?php

declare(strict_types=1);

use App\Services\Dualstack\TrackerLease;
use App\Services\Dualstack\TransitionJournal;
use App\Services\Dualstack\TransitionWriter;
use App\Models\Seedbox;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

beforeEach(function (): void {
    if (getenv('DUALSTACK_BON_CONTENTION_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL/Redis reais, banco unit3d_dualstack_journal_test e DUALSTACK_BON_CONTENTION_TESTS=1.');
    }
    expect(DB::getDriverName())->toBe('mysql')->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::selectOne('SELECT @@transaction_isolation AS level')->level)->toBe('REPEATABLE-READ');
    expect((int) DB::selectOne('SELECT @@innodb_lock_wait_timeout AS seconds')->seconds)->toBe(10);
    expect(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    DB::table('peers')->delete();
    DB::table('history')->delete();
    DB::table('users')->update(['uploaded' => 0, 'downloaded' => 0]);
    DB::table('torrents')->update(array_fill_keys(['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6', 'times_completed'], 0));
    config(['cache.prefix' => 'dualstack-bon-test:'.bin2hex(random_bytes(8)), 'dualstack.allow_private_addresses' => true]);
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

afterEach(function (): void {
    if (getenv('DUALSTACK_BON_CONTENTION_TESTS') !== '1' || !isset($this->lease)) {
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

it('preserva creditos com quatro gravadores e consumidor concorrente', function (string $command): void {
    if (getenv('DUALSTACK_BON_TESTS') !== '1' || !\function_exists('pcntl_fork')) {
        $this->markTestSkipped('Exige DUALSTACK_BON_TESTS=1 e cinco processos reais.');
    }
    config(['dualstack.enabled' => getenv('DUALSTACK_BON_LEGACY_CONTROL') !== '1', 'dualstack.endpoint_ttl' => 7200]);
    $metrics = fn () => DB::table('information_schema.INNODB_METRICS')
        ->whereIn('NAME', ['lock_deadlocks', 'lock_timeouts'])->pluck('COUNT', 'NAME')
        ->map(fn ($value) => (int) $value)->all();
    $beforeMetrics = $metrics();
    expect($beforeMetrics)->toHaveKeys(['lock_deadlocks', 'lock_timeouts']);
    $savedRules = DB::table('bon_earnings')->get()->map(fn ($row) => (array) $row)->all();
    $savedConditions = DB::table('bon_earning_conditions')->get()->map(fn ($row) => (array) $row)->all();
    $balances = DB::table('users')->pluck('seedbonus', 'id')->all();
    $seedboxes = DB::table('seedboxes')->get()->map(fn ($row) => (array) $row)->all();
    $highspeed = DB::table('torrents')->pluck('highspeed', 'id')->all();
    $children = $gates = [];

    try {
        if ($command === 'auto:highspeed_tag') {
            DB::table('seedboxes')->delete();

            foreach (['172.29.92.30', 'fd42:756e:6974:92::30'] as $ip) {
                Seedbox::withoutEvents(fn () => Seedbox::create(['user_id' => 12001, 'name' => 'Fixture concorrente', 'ip' => $ip]));
            }
            DB::table('torrents')->update(['highspeed' => false]);
        }
        DB::table('bon_earnings')->delete();
        $rule = DB::table('bon_earnings')->insertGetId([
            'position' => 1, 'variable' => '1', 'multiplier' => 10, 'operation' => 'append',
            'name'     => 'BON concorrente', 'description' => 'Fixture isolada',
        ]);
        DB::table('bon_earning_conditions')->insert(['bon_earning_id' => $rule, 'operand1' => 'connectable', 'operator' => '=', 'operand2' => 1]);

        foreach ([12001, 12002, 12003] as $user) {
            foreach ([12001, 12002] as $torrent) {
                $identity = array_replace($this->identity, ['user_id' => $user, 'torrent_id' => $torrent]);

                foreach (['172.29.92.30', 'fd42:756e:6974:92::30'] as $ip) {
                    $result = $this->journal->publish($identity, array_replace($this->request, ['ip' => $ip, 'left' => '0']), $this->policy, $this->credit, time() - 3600);
                    expect($result['outcome'])->toBe('accepted');
                }
                $probe = $this->journal->publish($identity, ['kind' => 'probe', 'ip' => 'fd42:756e:6974:92::30', 'port' => 6881, 'revision' => $result['peer']['endpoints'][6]['revision'], 'connectable' => true], $this->policy, $this->credit, time() - 3600);
                expect($probe['outcome'])->toBe('accepted');
            }
        }
        $this->writer->flush('bon-setup');
        expect(DB::table('peer_ips')->where('connectable', true)->count())->toBe(6)
            ->and(DB::table('peers')->where('created_at', '<', now()->subMinutes(30))->count())->toBe(6);

        foreach (range(1, 4) as $step) {
            foreach ([12001, 12002, 12003] as $user) {
                foreach ([12001, 12002] as $torrent) {
                    $identity = array_replace($this->identity, ['user_id' => $user, 'torrent_id' => $torrent]);
                    $this->journal->publish($identity, array_replace($this->request, ['event' => '', 'left' => '0', 'uploaded' => (string) (1000 + $step * 100)]), $this->policy, $this->credit);
                }
            }
        }
        $messages = $this->writer->read('bon-dispatcher');
        expect($messages)->toHaveCount(24);
        $this->lease->renew();
        config(['database.connections.bon_monitor' => config('database.connections.'.config('database.default'))]);
        DB::disconnect();
        Redis::purge('announce');

        for ($worker = 0; $worker < 5; $worker++) {
            $sockets = stream_socket_pair(STREAM_PF_UNIX, STREAM_SOCK_STREAM, STREAM_IPPROTO_IP);
            $pid = pcntl_fork();

            if ($pid === -1 || $sockets === false) {
                throw new RuntimeException('Falha ao criar processo de contencao.');
            }

            if ($pid === 0) {
                fclose($sockets[0]);

                try {
                    if (fread($sockets[1], 1) !== 'G') {
                        exit(1);
                    }

                    if ($worker === 4) {
                        foreach (range(1, 5) as $hour) {
                            app(Kernel::class)->call($command);
                        }
                    } else {
                        foreach ($messages as $id => $message) {
                            $this->writer->persist([$id => $message]);
                        }
                    }

                    exit(0);
                } catch (Throwable $error) {
                    fwrite(STDERR, 'Contencao BON: '.$error::class.' codigo '.$error->getCode()."\n");

                    exit(1);
                }
            }
            fclose($sockets[1]);
            $children[] = $pid;
            $gates[] = $sockets[0];
        }
        DB::beginTransaction();
        DB::table('users')->whereIn('id', [12001, 12002, 12003])->orderBy('id')->lockForUpdate()->get(['id']);

        if ($command === 'auto:highspeed_tag') {
            DB::table('torrents')->whereIn('id', [12001, 12002])->orderBy('id')->lockForUpdate()->get(['id']);
        }

        foreach ($gates as $gate) {
            fwrite($gate, 'G');
            fclose($gate);
        }
        $gates = [];
        $deadline = microtime(true) + 5;

        do {
            $waiting = (int) DB::connection('bon_monitor')->table('information_schema.INNODB_METRICS')
                ->where('NAME', 'lock_row_lock_current_waits')->value('COUNT');

            if ($waiting >= 5) {
                break;
            }
            usleep(20000);
        } while (microtime(true) < $deadline);
        DB::commit();

        foreach ($children as $pid) {
            pcntl_waitpid($pid, $status);
            expect(pcntl_wifexited($status))->toBeTrue()->and(pcntl_wexitstatus($status))->toBe(0);
        }
        $children = [];
        $this->writer->acknowledge(array_keys($messages));
        $afterMetrics = $metrics();
        $credits = [];

        foreach ([12001, 12002, 12003] as $user) {
            $row = DB::table('users')->find($user);
            $credits[$user] = ['uploaded' => (string) $row->uploaded, 'bon_delta' => (float) $row->seedbonus - (float) $balances[$user]];
            expect((string) $row->uploaded)->toBe('800')
                ->and((float) $row->seedbonus - (float) $balances[$user])->toBe($command === 'auto:bon_allocation' ? 100.0 : 0.0);
        }
        expect(DB::table('peers')->count())->toBe(6)->and(DB::table('peer_ips')->count())->toBe(12)
            ->and((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions'))->toBe(0);
        fwrite(STDOUT, "\nBON contention ".json_encode([
            'command' => $command, 'dualstack_query' => config('dualstack.enabled'), 'waiting' => $waiting,
            'before'  => $beforeMetrics, 'after' => $afterMetrics, 'credits' => $credits,
        ])."\n");
        expect($waiting)->toBeGreaterThanOrEqual(5)->and($afterMetrics)->toBe($beforeMetrics);

        if ($command === 'auto:highspeed_tag') {
            expect(DB::table('torrents')->whereIn('id', [12001, 12002])->where('highspeed', true)->count())->toBe(2);
        }
    } finally {
        if (DB::transactionLevel() > 0) {
            DB::rollBack();
        }

        foreach ($gates as $gate) {
            fclose($gate);
        }

        foreach ($children as $pid) {
            pcntl_waitpid($pid, $status);
        }
        DB::table('bon_earnings')->delete();

        if ($savedRules !== []) {
            DB::table('bon_earnings')->insert($savedRules);
        }

        if ($savedConditions !== []) {
            DB::table('bon_earning_conditions')->insert($savedConditions);
        }

        foreach ($balances as $user => $balance) {
            DB::table('users')->where('id', $user)->update(['seedbonus' => $balance]);
        }

        if ($command === 'auto:highspeed_tag') {
            DB::table('seedboxes')->delete();

            if ($seedboxes !== []) {
                DB::table('seedboxes')->insert($seedboxes);
            }

            foreach ($highspeed as $torrent => $value) {
                DB::table('torrents')->where('id', $torrent)->update(['highspeed' => $value]);
            }
        }
        DB::purge('bon_monitor');
    }
})->with(['BON' => 'auto:bon_allocation', 'seedbox' => 'auto:highspeed_tag']);
