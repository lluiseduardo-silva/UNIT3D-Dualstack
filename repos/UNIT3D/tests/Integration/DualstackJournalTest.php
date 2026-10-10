<?php

declare(strict_types=1);

use App\Services\Dualstack\TrackerLease;
use App\Services\Dualstack\TrackerRecovery;
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
    if (getenv('DUALSTACK_JOURNAL_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL/Redis reais, banco unit3d_dualstack_journal_test e DUALSTACK_JOURNAL_TESTS=1.');
    }
    expect(DB::getDriverName())->toBe('mysql')->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::selectOne('SELECT @@transaction_isolation AS level')->level)->toBe('REPEATABLE-READ');
    expect((int) DB::selectOne('SELECT @@innodb_lock_wait_timeout AS seconds')->seconds)->toBe(10);
    DB::table('peers')->delete();
    DB::table('history')->delete();
    DB::table('users')->update(['uploaded' => 0, 'downloaded' => 0]);
    DB::table('torrents')->update(array_fill_keys(['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6', 'times_completed'], 0));
    DB::table('tracker_ownership')->where('id', 1)->update(['lease_expires_at' => null]);
    config(['cache.prefix' => 'dualstack-journal-test:'.bin2hex(random_bytes(8)), 'dualstack.allow_private_addresses' => true]);
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
    if (getenv('DUALSTACK_JOURNAL_TESTS') !== '1' || !isset($this->lease)) {
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

it('certifica drenagem somente depois de fechar produtores e reconhecer o journal', function (): void {
    expect((bool) DB::table('tracker_ownership')->where('id', 1)->value('php_journal_drained'))->toBeFalse();
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit);
    $this->lease->release();
    expect((bool) DB::table('tracker_ownership')->where('id', 1)->value('php_journal_drained'))->toBeFalse();
    expect(fn () => $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit))->toThrow(RuntimeException::class, 'proprietario ativo');
    $this->lease = TrackerLease::acquire();
    $report = (new TrackerRecovery($this->lease, $this->policy))->restore();
    expect($report['replayed_transitions'])->toBe(1);
    $this->lease->release();
    expect((bool) DB::table('tracker_ownership')->where('id', 1)->value('php_journal_drained'))->toBeTrue()
        ->and((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions'))->toBe(0);
});

it('nao permite que uma geracao antiga certifique a nova como drenada', function (): void {
    $old = $this->lease;
    $old->release();
    $this->lease = TrackerLease::acquire();
    $this->lease->ready(true);
    $old->release();
    expect((bool) DB::table('tracker_ownership')->where('id', 1)->value('php_journal_drained'))->toBeFalse()
        ->and(Redis::connection('announce')->get(TrackerLease::base().':heartbeat'))->toBe($this->lease->ownerId)
        ->and(Redis::connection('announce')->hGet(TrackerLease::base().':owner', 'ready'))->toBe('1');
});

it('nao certifica drenagem enquanto houver filas legadas', function (): void {
    $redis = Redis::connection('announce');

    foreach (['peers', 'histories'] as $queue) {
        $key = config('cache.prefix').':'.$queue.':batch';
        $redis->rPush($key, 'ensaio');

        try {
            $this->lease->release();
            expect((bool) DB::table('tracker_ownership')->where('id', 1)->value('php_journal_drained'))->toBeFalse();
        } finally {
            $redis->del($key);
        }
    }
    $this->lease->release();
    expect((bool) DB::table('tracker_ownership')->where('id', 1)->value('php_journal_drained'))->toBeTrue();
});

it('confirma referencias e credito juntos e tolera reentrega depois do commit', function (): void {
    foreach ([['172.29.92.30', '1000'], ['fd42:756e:6974:92::30', '1000'], ['fd42:756e:6974:92::30', '1100'], ['172.29.92.30', '1050'], ['172.29.92.30', '1200']] as [$ip, $upload]) {
        expect($this->journal->publish($this->identity, array_replace($this->request, ['ip' => $ip, 'uploaded' => $upload]), $this->policy, $this->credit)['outcome'])->toBe('accepted');
    }
    $messages = $this->writer->read('worker-a');
    expect($messages)->toHaveCount(5);
    expect($this->writer->persist($messages))->toBe(5);
    // A mensagem permanece pendente: representa o processo morto antes do ACK.
    $replay = $this->writer->read('worker-b', claimAfterMs: 0);
    expect($replay)->toHaveCount(5)->and($this->writer->persist($replay))->toBe(0);
    $this->writer->acknowledge(array_keys($replay));
    expect((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions'))->toBe(0);
    $peer = DB::table('peers')->first();
    expect((string) $peer->uploaded)->toBe('1200')->and((int) $peer->state_version)->toBe(5)
        ->and(DB::table('peer_ips')->count())->toBe(2)
        ->and((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('200')
        ->and((string) DB::table('history')->value('actual_uploaded'))->toBe('200');
    $torrent = DB::table('torrents')->find(12001);
    expect((int) $torrent->leechers)->toBe(1)->and((int) $torrent->leechers_ipv4)->toBe(1)->and((int) $torrent->leechers_ipv6)->toBe(1);
});

it('recusa fila cheia antes de avancar a referencia e preserva uint64', function (): void {
    $request = array_replace($this->request, ['uploaded' => '9007199254740993']);
    $this->journal->publish($this->identity, $request, $this->policy, $this->credit);
    $request['uploaded'] = '9007199254740994';
    expect(fn () => $this->journal->publish($this->identity, $request, array_replace($this->policy, ['max_pending_transitions' => 1]), $this->credit))->toThrow(RuntimeException::class, 'backlog_full');
    $snapshot = json_decode(Redis::connection('announce')->get($this->journal->keys($this->identity)[0]), true);
    expect($snapshot['uploaded'])->toBe('9007199254740993')->and($snapshot['state_version'])->toBe(1);
    $this->writer->flush('worker');
    expect($this->journal->publish($this->identity, $request, $this->policy, $this->credit)['upload_delta'])->toBe('1');
    $this->writer->flush('worker');
    expect((string) DB::table('peers')->value('uploaded'))->toBe('9007199254740994')
        ->and((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('1');
});

it('aplica limites ao peer logico e ao endpoint separadamente', function (): void {
    for ($n = 0; $n < 3; $n++) {
        $identity = array_replace($this->identity, ['peer_id' => bin2hex(str_repeat((string) $n, 20))]);

        foreach (['172.29.92.30', 'fd42:756e:6974:92::30'] as $ip) {
            expect($this->journal->publish($identity, array_replace($this->request, ['ip' => $ip]), $this->policy, $this->credit)['outcome'])->toBe('accepted');
        }
    }
    expect($this->journal->publish($this->identity, $this->request, $this->policy, $this->credit)['reason'])->toBe('peer_limit');
    $this->writer->flush('worker');
    expect(DB::table('peers')->count())->toBe(3)->and(DB::table('peer_ips')->count())->toBe(6)
        ->and((int) DB::table('torrents')->where('id', 12001)->value('leechers'))->toBe(3);
    $identity = array_replace($this->identity, ['user_id' => 12002]);
    $single = array_replace($this->policy, ['max_endpoints' => 1]);
    $this->journal->publish($identity, $this->request, $single, $this->credit);
    expect($this->journal->publish($identity, array_replace($this->request, ['ip' => 'fd42:756e:6974:92::30']), $single, $this->credit)['reason'])->toBe('endpoint_limit');
});

it('deduplica conclusao por usuario torrent e preserva historico no stopped parcial', function (): void {
    $now = (int) Redis::connection('announce')->time()[0];
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit, $now);
    $complete = array_replace($this->request, ['event' => 'completed', 'left' => '0', 'downloaded' => '100']);
    $this->journal->publish($this->identity, $complete, $this->policy, $this->credit, $now + 10);
    $complete['ip'] = 'fd42:756e:6974:92::30';
    $this->journal->publish($this->identity, $complete, $this->policy, $this->credit, $now + 20);
    $this->journal->publish($this->identity, array_replace($complete, ['event' => 'stopped', 'port' => 0]), $this->policy, $this->credit, $now + 30);
    $other = array_replace($this->identity, ['peer_id' => bin2hex(str_repeat('K', 20))]);
    $this->journal->publish($other, $this->request, $this->policy, $this->credit, $now + 30);
    $this->journal->publish($other, $complete, $this->policy, $this->credit, $now + 40);
    $this->writer->flush('worker');
    expect((int) DB::table('torrents')->where('id', 12001)->value('times_completed'))->toBe(1)
        ->and((bool) DB::table('history')->value('active'))->toBeTrue()
        ->and((int) DB::table('history')->value('seedtime'))->toBe(30)
        ->and(DB::table('peer_ips')->count())->toBe(3);
});

it('recusa dois proprietarios e recupera ambos endpoints e credito entre geracoes', function (): void {
    expect(fn () => TrackerLease::acquire())->toThrow(RuntimeException::class, 'proprietario ativo');
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit);
    $this->journal->publish($this->identity, array_replace($this->request, ['ip' => 'fd42:756e:6974:92::30', 'uploaded' => '1100']), $this->policy, $this->credit);
    $oldWriter = $this->writer;
    $pending = $oldWriter->read('crashed-worker');
    $oldWriter->persist($pending);
    $this->lease->release();
    $this->lease = TrackerLease::acquire();
    expect(fn () => $oldWriter->persist($pending))->toThrow(RuntimeException::class, 'proprietario ou geracao');
    $report = (new TrackerRecovery($this->lease, $this->policy))->restore();
    expect($report['loaded_peers'])->toBe(1)->and($report['replayed_transitions'])->toBe(2);
    $this->journal = new TransitionJournal($this->lease);
    $this->writer = new TransitionWriter($this->lease);
    $state = json_decode(Redis::connection('announce')->get($this->journal->keys($this->identity)[0]), true);
    expect($state['endpoints'])->toHaveCount(2)->and($state['uploaded'])->toBe('1100');
    expect($this->journal->publish($this->identity, array_replace($this->request, ['uploaded' => '1200']), $this->policy, $this->credit)['upload_delta'])->toBe('100');
    $this->writer->flush('restored-worker');
    expect((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('200');
});

it('calcula credito com quatro processos disputando a mesma referencia', function (): void {
    if (!\function_exists('pcntl_fork')) {
        $this->markTestSkipped('Exige pcntl e quatro processos reais.');
    }
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit);
    $this->lease->renew();
    $barrier = TrackerLease::base().':test-barrier';
    DB::disconnect();
    Redis::purge('announce');
    $children = [];

    for ($worker = 0; $worker < 4; $worker++) {
        $pid = pcntl_fork();

        if ($pid === -1) {
            throw new RuntimeException('Falha ao criar processo de teste.');
        }

        if ($pid === 0) {
            try {
                $redis = Redis::connection('announce');
                $redis->rPush($barrier.':ready', '1');
                $deadline = hrtime(true) + 5e9;

                while (!$redis->lPop($barrier.':go')) {
                    if (hrtime(true) > $deadline) {
                        throw new RuntimeException('Timeout da barreira de concorrencia.');
                    }
                    usleep(1000);
                }

                for ($iteration = 1; $iteration <= 10; $iteration++) {
                    $result = $this->journal->publish($this->identity, array_replace($this->request, [
                        'ip'       => $worker % 2 === 0 ? '172.29.92.30' : 'fd42:756e:6974:92::30',
                        'uploaded' => (string) (1000 + $worker * 1000 + $iteration * 100),
                    ]), $this->policy, $this->credit);

                    if ($result['outcome'] !== 'accepted') {
                        throw new RuntimeException('Announce concorrente recusado.');
                    }
                }

                exit(0);
            } catch (Throwable $error) {
                fwrite(STDERR, 'Processo concorrente: '.$error::class.' '.$error->getMessage()."\n");

                exit(1);
            }
        }
        $children[] = $pid;
    }
    $redis = Redis::connection('announce');
    $deadline = hrtime(true) + 5e9;

    while ((int) $redis->lLen($barrier.':ready') !== 4) {
        if (hrtime(true) > $deadline) {
            throw new RuntimeException('Processos nao chegaram a barreira.');
        }
        usleep(1000);
    }
    $redis->rPush($barrier.':go', '1', '1', '1', '1');

    foreach ($children as $pid) {
        pcntl_waitpid($pid, $status);
        expect(pcntl_wifexited($status))->toBeTrue()->and(pcntl_wexitstatus($status))->toBe(0);
    }
    $this->lease->renew();
    expect($this->writer->flush('persist-concurrency'))->toBe(41);
    expect((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('4000')
        ->and((int) DB::table('peers')->value('state_version'))->toBe(41)
        ->and((string) DB::table('peers')->value('uploaded'))->toBe('5000')
        ->and(DB::table('peer_ips')->count())->toBe(2);
});

it('recupera um lote interrompido antes do commit sem avancar SQL parcialmente', function (): void {
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit);
    $this->journal->publish($this->identity, array_replace($this->request, ['uploaded' => '1100']), $this->policy, $this->credit);
    $messages = $this->writer->read('interrupted');
    $interrupt = true;
    DB::listen(function (Illuminate\Database\Events\QueryExecuted $query) use (&$interrupt): void {
        if ($interrupt && str_starts_with($query->sql, 'insert into `peer_ips`')) {
            throw new RuntimeException('INTERRUPCAO_ANTES_DO_COMMIT');
        }
    });

    try {
        expect(fn () => $this->writer->persist($messages))->toThrow(RuntimeException::class, 'INTERRUPCAO_ANTES_DO_COMMIT');
    } finally {
        $interrupt = false;
    }
    expect(DB::table('peers')->count())->toBe(0)->and(DB::table('history')->count())->toBe(0)
        ->and((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('0')
        ->and((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions'))->toBe(2);
    expect($this->writer->persist($messages))->toBe(2);
    $this->writer->acknowledge(array_keys($messages));
    expect((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('100');
});

it('expira somente a familia vencida depois da recuperacao', function (): void {
    $now = (int) Redis::connection('announce')->time()[0];
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit, $now - 7199);
    $this->journal->publish($this->identity, array_replace($this->request, ['ip' => 'fd42:756e:6974:92::30']), $this->policy, $this->credit, $now - 7000);
    $this->writer->flush('worker');
    // Relogio controlado no estado confirmado, sem aguardar duas horas.
    DB::table('peer_ips')->where('family', 4)->update(['last_announced_at' => gmdate('Y-m-d H:i:s', $now - 7201)]);
    $this->lease->release();
    $this->lease = TrackerLease::acquire();
    $recovery = new TrackerRecovery($this->lease, $this->policy);
    $report = $recovery->restore();
    expect($report['expired_peers'])->toBe(1)->and(DB::table('peer_ips')->pluck('family')->map(fn ($v) => (int) $v)->all())->toBe([6]);
    $torrent = DB::table('torrents')->find(12001);
    expect((int) $torrent->leechers)->toBe(1)->and((int) $torrent->leechers_ipv4)->toBe(0)->and((int) $torrent->leechers_ipv6)->toBe(1)
        ->and((bool) DB::table('history')->value('active'))->toBeTrue();
    expect($recovery->expire())->toBe(0);
});

it('recupera o consumidor morto por SIGKILL na fronteira do commit', function (bool $beforeCommit): void {
    if (!\function_exists('pcntl_fork') || !\function_exists('posix_kill')) {
        $this->markTestSkipped('Exige pcntl, posix e morte real do consumidor.');
    }
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit);
    $this->journal->publish($this->identity, array_replace($this->request, ['uploaded' => '1100']), $this->policy, $this->credit);
    $messages = $this->writer->read('consumer-to-kill');
    $this->lease->renew();
    DB::disconnect();
    Redis::purge('announce');
    $pid = pcntl_fork();

    if ($pid === -1) {
        throw new RuntimeException('Falha ao criar consumidor para SIGKILL.');
    }

    if ($pid === 0) {
        try {
            if ($beforeCommit) {
                DB::listen(function (Illuminate\Database\Events\QueryExecuted $query): void {
                    if (str_starts_with($query->sql, 'insert into `peer_ips`')) {
                        posix_kill(getmypid(), SIGKILL);
                    }
                });
            }
            $this->writer->persist($messages);

            if (!$beforeCommit) {
                posix_kill(getmypid(), SIGKILL);
            }
        } catch (Throwable $error) {
            fwrite(STDERR, 'Consumidor a interromper: '.$error::class."\n");
        }

        exit(2);
    }
    pcntl_waitpid($pid, $status);
    expect(pcntl_wifsignaled($status))->toBeTrue()->and(pcntl_wtermsig($status))->toBe(SIGKILL);
    $this->lease->renew();
    expect(DB::table('peers')->count())->toBe($beforeCommit ? 0 : 1)
        ->and(DB::table('history')->count())->toBe($beforeCommit ? 0 : 1)
        ->and(DB::table('peer_ips')->count())->toBe($beforeCommit ? 0 : 1)
        ->and((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe($beforeCommit ? '0' : '100');
    $replay = $this->writer->read('replacement-consumer', claimAfterMs: 0);
    expect($replay)->toHaveCount(2)->and($this->writer->persist($replay))->toBe($beforeCommit ? 2 : 0);
    $this->writer->acknowledge(array_keys($replay));
    expect((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('100')
        ->and((string) DB::table('peers')->value('uploaded'))->toBe('1100')
        ->and((string) DB::table('history')->value('actual_uploaded'))->toBe('100')
        ->and((int) DB::table('peers')->value('state_version'))->toBe(2)
        ->and((int) DB::table('torrents')->where('id', 12001)->value('leechers'))->toBe(1)
        ->and((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions'))->toBe(0);
})->with(['antes do commit' => [true], 'depois do commit antes do ACK' => [false]]);

it('persiste lotes sobrepostos em dois processos sem deadlock ou credito duplicado', function (): void {
    if (!\function_exists('pcntl_fork')) {
        $this->markTestSkipped('Exige pcntl e dois consumidores reais.');
    }
    $metrics = fn () => DB::table('information_schema.INNODB_METRICS')->whereIn('NAME', ['lock_deadlocks', 'lock_timeouts'])->pluck('COUNT', 'NAME')->map(fn ($value) => (int) $value)->all();
    $beforeMetrics = $metrics();
    expect($beforeMetrics)->toHaveKeys(['lock_deadlocks', 'lock_timeouts']);
    $messages = [];

    foreach ([12001, 12002, 12003] as $user) {
        foreach ([12001, 12002] as $torrent) {
            $identity = array_replace($this->identity, ['user_id' => $user, 'torrent_id' => $torrent]);
            $this->journal->publish($identity, $this->request, $this->policy, $this->credit);
            $this->journal->publish($identity, array_replace($this->request, ['uploaded' => '1100']), $this->policy, $this->credit);
        }
    }
    $messages = $this->writer->read('dispatcher');
    $this->lease->renew();
    DB::disconnect();
    Redis::purge('announce');
    $children = [];

    for ($worker = 0; $worker < 2; $worker++) {
        $pid = pcntl_fork();

        if ($pid === -1) {
            throw new RuntimeException('Falha ao criar consumidor.');
        }

        if ($pid === 0) {
            try {
                $batch = $worker === 0 ? $messages : array_reverse($messages, true);
                $this->writer->persist($batch);

                exit(0);
            } catch (Throwable $error) {
                fwrite(STDERR, 'Consumidor concorrente: '.$error::class.' '.$error->getMessage()."\n");

                exit(1);
            }
        }
        $children[] = $pid;
    }

    foreach ($children as $pid) {
        pcntl_waitpid($pid, $status);
        expect(pcntl_wifexited($status))->toBeTrue()->and(pcntl_wexitstatus($status))->toBe(0);
    }
    $this->writer->acknowledge(array_keys($messages));
    expect($metrics())->toBe($beforeMetrics)
        ->and(DB::table('peers')->count())->toBe(6)
        ->and(DB::table('history')->count())->toBe(6);

    foreach ([12001, 12002, 12003] as $user) {
        expect((string) DB::table('users')->where('id', $user)->value('uploaded'))->toBe('200');
    }
});

it('limita peers logicos na resposta sem truncar contadores ou perder caminhos', function (): void {
    config(['dualstack.require_connectivity' => false, 'dualstack.endpoint_ttl' => 7200]);

    foreach ([12001, 12002, 12003] as $user) {
        $identity = array_replace($this->identity, ['user_id' => $user]);

        foreach (['172.29.92.30', 'fd42:756e:6974:92::30'] as $ip) {
            $this->journal->publish($identity, array_replace($this->request, ['ip' => $ip, 'left' => '0']), $this->policy, $this->credit);
        }
    }
    $this->writer->flush('worker');
    $builder = new App\Services\Dualstack\AnnounceResponse();

    foreach ([0, 1, 25] as $numwant) {
        $response = App\Helpers\Bencode::bdecode($builder->build(12001, 12001, false, $numwant, false));
        expect($response['complete'])->toBe(3)->and($response['incomplete'])->toBe(0)
            ->and(\strlen($response['peers']))->toBe(6 * min($numwant, 2))
            ->and(\strlen($response['peers6']))->toBe(18 * min($numwant, 2));
    }
    $response = App\Helpers\Bencode::bdecode($builder->build(12001, 12001, false, 25, true));
    expect($response['complete'])->toBe(3)->and($response['peers'])->toBe('')->and($response['peers6'])->toBe('');
    DB::table('peer_ips')->where('family', 6)->update(['last_announced_at' => now()->subSeconds(7201)]);
    $response = App\Helpers\Bencode::bdecode($builder->build(12001, 12001, false, 25, false));
    expect($response['complete'])->toBe(3)->and(\strlen($response['peers']))->toBe(12)->and($response['peers6'])->toBe('');
});

it('retira somente peers confirmados e preserva uma reativacao pendente', function (): void {
    config(['dualstack.inactive_peer_retention' => 172800]);
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit);
    $stop = array_replace($this->request, ['event' => 'stopped', 'port' => 0]);
    $this->journal->publish($this->identity, $stop, $this->policy, $this->credit);
    $this->writer->flush('worker');
    DB::table('peers')->update(['updated_at' => now()->subSeconds(172801)]);
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit);
    $recovery = new TrackerRecovery($this->lease, $this->policy);
    expect($recovery->retire())->toBe(0)->and((bool) DB::table('peers')->value('active'))->toBeTrue();
    $this->journal->publish($this->identity, $stop, $this->policy, $this->credit);
    $this->writer->flush('worker');
    DB::table('peers')->update(['updated_at' => now()->subSeconds(172801)]);
    expect($recovery->retire())->toBe(1)->and(DB::table('peers')->count())->toBe(0)->and(DB::table('peer_ips')->count())->toBe(0);
    expect($this->journal->publish($this->identity, array_replace($this->request, ['uploaded' => '5000']), $this->policy, $this->credit)['upload_delta'])->toBe('0');
    $this->writer->flush('worker');
    expect((int) DB::table('peers')->value('state_version'))->toBe(1)->and((int) DB::table('history')->value('state_version'))->toBe(5)
        ->and((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('0');
});

it('verifica TCP por familia sem desconectar o caminho valido', function (): void {
    $address4 = getenv('DUALSTACK_TEST_BIND_IPV4');
    $address6 = getenv('DUALSTACK_TEST_BIND_IPV6');

    if (!$address4 || !$address6) {
        $this->markTestSkipped('Exige IPv4 e IPv6 locais reais em DUALSTACK_TEST_BIND_IPV4/IPV6.');
    }
    config(['announce.connectable_check'       => true, 'dualstack.require_connectivity' => true,
        'dualstack.connectivity_cache_entries' => 2, 'dualstack.connectivity_cache_ttl' => 1800]);
    $this->policy['require_connectivity'] = true;
    $server4 = stream_socket_server('tcp://'.$address4.':0', $errno, $error);
    $server6 = stream_socket_server('tcp://['.$address6.']:0', $errno, $error);
    expect(\is_resource($server4))->toBeTrue()->and(\is_resource($server6))->toBeTrue();
    $port4 = (int) substr(strrchr(stream_socket_get_name($server4, false), ':'), 1);
    $port6 = (int) substr(strrchr(stream_socket_get_name($server6, false), ':'), 1);

    try {
        foreach ([[$address4, $port4], [$address6, $port6]] as [$ip, $port]) {
            $this->journal->publish($this->identity, array_replace($this->request, ['ip' => $ip, 'port' => $port, 'left' => '0']), $this->policy, $this->credit);
        }
        $this->writer->flush('worker');
        $probe = new App\Services\Dualstack\EndpointProbe();
        expect($probe->runBatch())->toBe(2);
        $this->writer->flush('worker');
        expect((int) DB::table('peer_ips')->where('connectable', true)->count())->toBe(2);
        fclose($server6);
        $server6 = null;
        Redis::connection('announce')->zAdd($this->lease->prefix().':probe-expiry', 0, hash('sha256', inet_pton($address6).pack('n', $port6)));
        DB::table('peer_ips')->where('family', 6)->update(['connectivity_checked_at' => now()->subSeconds(1801)]);
        expect($probe->runBatch())->toBe(1);
        $this->writer->flush('worker');
        expect((bool) DB::table('peers')->value('connectable'))->toBeTrue()
            ->and((int) DB::table('torrents')->where('id', 12001)->value('seeders'))->toBe(1)
            ->and((int) DB::table('torrents')->where('id', 12001)->value('seeders_ipv4'))->toBe(1)
            ->and((int) DB::table('torrents')->where('id', 12001)->value('seeders_ipv6'))->toBe(0);
    } finally {
        fclose($server4);

        if (\is_resource($server6)) {
            fclose($server6);
        }
        config(['announce.connectable_check' => false, 'dualstack.require_connectivity' => false]);
    }
});

it('limita o cache de conectividade durante rotacao de portas', function (): void {
    $address = getenv('DUALSTACK_TEST_BIND_IPV4');

    if (!$address) {
        $this->markTestSkipped('Exige DUALSTACK_TEST_BIND_IPV4.');
    }
    config(['announce.connectable_check'       => true, 'dualstack.require_connectivity' => false,
        'dualstack.connectivity_cache_entries' => 2, 'dualstack.connectivity_cache_ttl' => 1800]);

    try {
        $probe = new App\Services\Dualstack\EndpointProbe();

        for ($port = 59100; $port < 59108; $port++) {
            $this->journal->publish($this->identity, array_replace($this->request, ['ip' => $address, 'port' => $port]), $this->policy, $this->credit);
            $this->writer->flush('worker');
            $probe->runBatch();
            $this->writer->flush('worker');
            expect((int) Redis::connection('announce')->hLen($this->lease->prefix().':probe-values'))->toBeLessThanOrEqual(2)
                ->and((int) Redis::connection('announce')->zCard($this->lease->prefix().':probe-expiry'))->toBeLessThanOrEqual(2)
                ->and(DB::table('peer_ips')->count())->toBe(1);
        }
    } finally {
        config(['announce.connectable_check' => false]);
    }
});

it('recupera mensagens nao confirmadas e bloqueia o proprietario vencido', function (): void {
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit);
    $this->journal->publish($this->identity, array_replace($this->request, ['uploaded' => '1100']), $this->policy, $this->credit);
    $messages = $this->writer->read('crashed-worker');
    $oldLease = $this->lease;
    $oldJournal = $this->journal;
    DB::table('tracker_ownership')->where('id', 1)->update(['lease_expires_at' => now()->subMinute()]);
    expect(fn () => $this->writer->persist($messages))->toThrow(RuntimeException::class, 'proprietario ou geracao');
    $this->lease = TrackerLease::acquire();
    $report = (new TrackerRecovery($this->lease, $this->policy))->restore();
    expect($report['replayed_transitions'])->toBe(2)->and((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('100');
    expect(fn () => $oldJournal->publish($this->identity, $this->request, $this->policy, $this->credit))->toThrow(RuntimeException::class, 'sem proprietario ativo');
    expect(fn () => $oldLease->renew())->toThrow(RuntimeException::class, 'Propriedade do swarm perdida');
});

it('recusa announce sem heartbeat antes de alterar referencia ou journal', function (): void {
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit);
    Redis::connection('announce')->del(TrackerLease::base().':heartbeat');
    expect(fn () => $this->journal->publish($this->identity, array_replace($this->request, ['uploaded' => '1100']), $this->policy, $this->credit))->toThrow(RuntimeException::class, 'sem proprietario ativo');
    $state = json_decode(Redis::connection('announce')->get($this->journal->keys($this->identity)[0]), true);
    expect($state['uploaded'])->toBe('1000')->and($state['state_version'])->toBe(1)
        ->and((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions'))->toBe(1);
});

it('converge announce expiracao e stop sobrepostos sem perder credito ou o caminho renovado', function (?array $order): void {
    if ($order === null && !\function_exists('pcntl_fork')) {
        $this->markTestSkipped('Exige pcntl e tres produtores reais.');
    }
    $now = (int) Redis::connection('announce')->time()[0];
    $this->journal->publish($this->identity, array_replace($this->request, ['ip' => 'fd42:756e:6974:92::30']), $this->policy, $this->credit, $now - 7199);
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit, $now - 10);
    $this->writer->flush('initial-state');
    $operations = [
        ['kind' => 'expire'],
        array_replace($this->request, ['event' => 'completed', 'ip' => 'fd42:756e:6974:92::31', 'uploaded' => '1200', 'left' => '0']),
        array_replace($this->request, ['event' => 'stopped', 'port' => 0, 'uploaded' => '1100']),
    ];

    if ($order !== null) {
        foreach ($order as $index) {
            $this->journal->publish($this->identity, $operations[$index], $this->policy, $this->credit, $now + 2);
        }
    } else {
        $this->lease->renew();
        $barrier = TrackerLease::base().':overlap-barrier';
        DB::disconnect();
        Redis::purge('announce');
        $children = [];

        foreach ($operations as $operation) {
            $pid = pcntl_fork();

            if ($pid === -1) {
                throw new RuntimeException('Falha ao criar produtor da sobreposicao.');
            }

            if ($pid === 0) {
                try {
                    $redis = Redis::connection('announce');
                    $redis->rPush($barrier.':ready', '1');
                    $deadline = hrtime(true) + 5e9;

                    while (!$redis->lPop($barrier.':go')) {
                        if (hrtime(true) > $deadline) {
                            throw new RuntimeException('Timeout da barreira de sobreposicao.');
                        }
                        usleep(1000);
                    }
                    $result = $this->journal->publish($this->identity, $operation, $this->policy, $this->credit, $now + 2);

                    if (!\in_array($result['outcome'], ['accepted', 'ignored'], true)) {
                        throw new RuntimeException('Operacao sobreposta recusada.');
                    }

                    exit(0);
                } catch (Throwable $error) {
                    fwrite(STDERR, 'Sobreposicao: '.$error::class."\n");

                    exit(1);
                }
            }
            $children[] = $pid;
        }
        $redis = Redis::connection('announce');
        $deadline = hrtime(true) + 5e9;

        while ((int) $redis->lLen($barrier.':ready') !== 3) {
            if (hrtime(true) > $deadline) {
                throw new RuntimeException('Produtores nao chegaram a barreira.');
            }
            usleep(1000);
        }
        $redis->rPush($barrier.':go', '1', '1', '1');

        foreach ($children as $pid) {
            pcntl_waitpid($pid, $status);
            expect(pcntl_wifexited($status))->toBeTrue()->and(pcntl_wexitstatus($status))->toBe(0);
        }
        $this->lease->renew();
    }
    $messages = $this->writer->read('overlap-writer');
    expect($messages)->not->toBeEmpty();
    $this->writer->persist($messages);
    expect($this->writer->persist($messages))->toBe(0);
    $this->writer->acknowledge(array_keys($messages));
    $peer = DB::table('peers')->first();
    $torrent = DB::table('torrents')->find(12001);
    $history = DB::table('history')->first();
    expect((string) $peer->uploaded)->toBe('1200')->and((bool) $peer->active)->toBeTrue()
        ->and((int) $peer->session_generation)->toBe(1)
        ->and((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('200')
        ->and((string) $history->actual_uploaded)->toBe('200')->and((bool) $history->active)->toBeTrue()
        ->and((int) $history->seedtime)->toBe(0)
        ->and(DB::table('peer_ips')->count())->toBe(1)
        ->and((int) DB::table('peer_ips')->value('family'))->toBe(6)
        ->and(inet_ntop(DB::table('peer_ips')->value('ip')))->toBe('fd42:756e:6974:92::31')
        ->and((int) $torrent->seeders)->toBe(1)->and((int) $torrent->leechers)->toBe(0)
        ->and((int) $torrent->seeders_ipv4)->toBe(0)->and((int) $torrent->seeders_ipv6)->toBe(1)
        ->and((int) $torrent->leechers_ipv4)->toBe(0)->and((int) $torrent->leechers_ipv6)->toBe(0)
        ->and((int) $torrent->times_completed)->toBe(1)
        ->and((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions'))->toBe(0);
})->with([
    'expira anuncia para'        => [[0, 1, 2]],
    'expira para anuncia'        => [[0, 2, 1]],
    'anuncia expira para'        => [[1, 0, 2]],
    'anuncia para expira'        => [[1, 2, 0]],
    'para expira anuncia'        => [[2, 0, 1]],
    'para anuncia expira'        => [[2, 1, 0]],
    'tres processos simultaneos' => [null],
]);
