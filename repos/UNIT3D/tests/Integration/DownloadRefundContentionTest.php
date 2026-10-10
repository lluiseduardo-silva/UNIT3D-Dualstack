<?php

declare(strict_types=1);

use App\Services\DownloadRefund;
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

it('preserva reembolsos e trafego com dezesseis processos sobre as mesmas chaves', function (): void {
    if (getenv('DUALSTACK_REFUND_CONTENTION_TESTS') !== '1' || !\function_exists('pcntl_fork')) {
        $this->markTestSkipped('Exige MySQL/Redis reais, pcntl e banco isolado de dualstack.');
    }
    expect(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test')
        ->and(DB::selectOne('SELECT @@transaction_isolation AS level')->level)->toBe('REPEATABLE-READ')
        ->and((int) DB::selectOne('SELECT @@innodb_lock_wait_timeout AS seconds')->seconds)->toBe(10)
        ->and(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    $metrics = fn () => DB::table('information_schema.INNODB_METRICS')
        ->whereIn('NAME', ['lock_deadlocks', 'lock_timeouts', 'lock_row_lock_waits', 'lock_row_lock_time'])
        ->pluck('COUNT', 'NAME')->map(fn ($n) => (int) $n)->all();
    $before = $metrics();
    $users = DB::table('users')->whereIn('id', [12001, 12002, 12003])->get(['id', 'downloaded', 'uploaded', 'group_id'])->all();
    $torrents = DB::table('torrents')->whereIn('id', [12001, 12002])->get(['id', 'size', 'user_id'])->all();
    DB::table('peers')->delete();
    DB::table('history')->delete();
    DB::table('users')->whereIn('id', [12001, 12002, 12003])->update(['downloaded' => 1000000, 'uploaded' => 0, 'group_id' => DB::table('groups')->orderBy('id')->value('id')]);
    // The uploader cannot also be a refund recipient.
    DB::table('torrents')->whereIn('id', [12001, 12002])->update(['size' => 1000, 'user_id' => 1]);
    config(['cache.prefix'                  => 'refund-contention:'.bin2hex(random_bytes(8)), 'dualstack.enabled' => true,
        'dualstack.allow_private_addresses' => true, 'other.refundable' => true, 'hitrun.seedtime' => 3600]);
    $lease = TrackerLease::acquire();
    $writer = new TransitionWriter($lease);
    $writer->prepare();
    $lease->ready(true);
    $journal = new TransitionJournal($lease);
    $policy = ['endpoint_ttl'     => 7200, 'max_endpoints' => 2, 'max_peers' => 3, 'min_interval' => 0,
        'allow_private_addresses' => true, 'require_connectivity' => false, 'max_pending_transitions' => 2000];
    $credit = ['upload_percent' => 100, 'download_percent' => 100, 'immune' => false];
    $request = ['event' => '', 'ip' => '192.0.2.30', 'port' => 6881, 'uploaded' => '1000', 'downloaded' => '1000', 'left' => '0', 'visible' => true, 'agent' => 'refund-contention'];
    $children = $gates = $files = [];

    try {
        foreach ([12001, 12002, 12003] as $user) {
            foreach ([12001, 12002] as $torrent) {
                $identity = ['user_id' => $user, 'torrent_id' => $torrent, 'peer_id' => bin2hex(str_repeat('F', 20))];

                foreach (['192.0.2.30', '2001:db8::30'] as $ip) {
                    expect($journal->publish($identity, array_replace($request, ['ip' => $ip]), $policy, $credit)['outcome'])->toBe('accepted');
                }
            }
        }
        $writer->flush('setup');
        DB::table('history')->update(['seedtime' => 12 * 30 * 24 * 60 * 60 + 3600, 'created_at' => now()->subDays(2)]);

        foreach (range(1, 100) as $step) {
            foreach ([12001, 12002, 12003] as $user) {
                foreach ([12001, 12002] as $torrent) {
                    $identity = ['user_id' => $user, 'torrent_id' => $torrent, 'peer_id' => bin2hex(str_repeat('F', 20))];
                    expect($journal->publish($identity, array_replace($request, ['ip' => $step % 2 ? '192.0.2.30' : '2001:db8::30',
                        'uploaded'                                                    => (string) (1000 + $step * 100), 'downloaded' => (string) (1000 + $step * 100)]), $policy, $credit)['outcome'])->toBe('accepted');
                }
            }
        }
        $messages = $writer->read('dispatch', 1000);
        expect($messages)->toHaveCount(600);
        $lease->renew();
        DB::disconnect();
        Redis::purge('announce');

        for ($worker = 0; $worker < 16; $worker++) {
            $files[$worker] = tempnam(sys_get_temp_dir(), 'refund-worker-');
            $sockets = stream_socket_pair(STREAM_PF_UNIX, STREAM_SOCK_STREAM, STREAM_IPPROTO_IP);
            $pid = pcntl_fork();

            if ($pid === -1 || $sockets === false) {
                throw new RuntimeException('Falha ao criar processos reais.');
            }

            if ($pid === 0) {
                fclose($sockets[0]);

                try {
                    if (fread($sockets[1], 1) !== 'G') {
                        exit(1);
                    }
                    $started = microtime(true);

                    if ($worker < 8) {
                        foreach ($messages as $id => $message) {
                            $writer->persist([$id => $message]);
                        }
                    } else {
                        for ($iteration = 0; $iteration < 20; $iteration++) {
                            app(DownloadRefund::class)->run();
                        }
                    }
                    file_put_contents($files[$worker], json_encode(['worker' => $worker, 'seconds' => microtime(true) - $started]));

                    exit(0);
                } catch (Throwable $error) {
                    fwrite(STDERR, 'Refund contention: '.$error::class.' code '.$error->getCode().' at '.basename($error->getFile()).':'.$error->getLine()."\n");

                    exit(1);
                }
            }
            fclose($sockets[1]);
            $children[] = $pid;
            $gates[] = $sockets[0];
        }
        DB::beginTransaction();
        DB::table('users')->whereIn('id', [12001, 12002, 12003])->orderBy('id')->lockForUpdate()->get(['id']);

        foreach ($gates as $gate) {
            fwrite($gate, 'G');
            fclose($gate);
        }
        $gates = [];
        $deadline = microtime(true) + 5;

        do {
            $waiting = (int) DB::table('information_schema.INNODB_METRICS')->where('NAME', 'lock_row_lock_current_waits')->value('COUNT');

            if ($waiting >= 16) {
                break;
            }
            usleep(20000);
        } while (microtime(true) < $deadline);
        DB::commit();
        $deadline = microtime(true) + 120;
        $renewAt = 0;

        while ($children !== []) {
            foreach ($children as $key => $pid) {
                if (pcntl_waitpid($pid, $status, WNOHANG) > 0) {
                    unset($children[$key]);
                    expect(pcntl_wifexited($status))->toBeTrue()->and(pcntl_wexitstatus($status))->toBe(0);
                }
            }
            expect(microtime(true))->toBeLessThan($deadline);

            if (microtime(true) >= $renewAt) {
                $lease->renew();
                $renewAt = microtime(true) + 3;
            }
            usleep(20000);
        }
        $writer->acknowledge(array_keys($messages));
        $after = $metrics();
        $credits = DB::table('users')->whereIn('id', [12001, 12002, 12003])->orderBy('id')->get(['id', 'uploaded', 'downloaded'])->all();

        foreach ($credits as $row) {
            expect((int) $row->uploaded)->toBe(20000)->and((int) $row->downloaded)->toBe(1018000);
        }
        fwrite(STDOUT, "\nrefund contention ".json_encode(['sql_writers' => 16, 'waiting' => $waiting,
            'unique_transitions'                                         => 600, 'persistence_attempts' => 4800, 'refund_commands' => 160,
            'before'                                                     => $before, 'after' => $after, 'credits' => $credits,
            'workers'                                                    => array_map(fn ($path) => json_decode(file_get_contents($path), true), $files)])."\n");
        expect($waiting)->toBeGreaterThanOrEqual(16)->and($after['lock_deadlocks'])->toBe($before['lock_deadlocks'])
            ->and($after['lock_timeouts'])->toBe($before['lock_timeouts'])
            ->and((int) DB::table('history')->sum('refunded_download'))->toBe(6000)
            ->and(DB::table('peers')->count())->toBe(6)->and(DB::table('peer_ips')->count())->toBe(12)
            ->and((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions'))->toBe(0);
    } finally {
        if (DB::transactionLevel() > 0) {
            DB::rollBack();
        }

        foreach ($gates as $gate) {
            fclose($gate);
        }

        foreach ($children as $pid) {
            posix_kill($pid, SIGTERM);
            pcntl_waitpid($pid, $status);
        }
        $lease->release();
        // Remove only this test's private, drained namespace. Keep pending evidence on failure.
        $redis = Redis::connection('announce');

        if ((int) $redis->xLen(TrackerLease::base().':transitions') === 0) {
            $cursor = '0';

            do {
                [$cursor, $keys] = $redis->command('rawCommand', ['SCAN', $cursor, 'MATCH', TrackerLease::base().':*', 'COUNT', 1000]);

                if ($keys !== []) {
                    $redis->command('rawCommand', ['UNLINK', ...$keys]);
                }
            } while ((string) $cursor !== '0');
        }

        foreach ($files as $file) {
            unlink($file);
        }

        foreach ($users as $user) {
            DB::table('users')->where('id', $user->id)->update((array) $user);
        }

        foreach ($torrents as $torrent) {
            DB::table('torrents')->where('id', $torrent->id)->update((array) $torrent);
        }
    }
});
