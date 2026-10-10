<?php

declare(strict_types=1);

use App\Http\Controllers\Staff\FlushController;
use App\Http\Controllers\User\PeerController;
use App\Models\User;
use App\Services\Dualstack\CleanupRejected;
use App\Services\Dualstack\CleanupRequests;
use App\Services\Dualstack\TrackerLease;
use App\Services\Dualstack\TrackerRecovery;
use App\Services\Dualstack\TransitionJournal;
use App\Services\Dualstack\TransitionWriter;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

beforeEach(function (): void {
    if (getenv('DUALSTACK_JOURNAL_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL/Redis reais e banco exclusivo de ensaio.');
    }
    expect(DB::getDriverName())->toBe('mysql')->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    DB::table('tracker_cleanup_requests')->delete();
    DB::table('peers')->delete();
    DB::table('history')->delete();
    DB::table('users')->update(['uploaded' => 0, 'downloaded' => 0, 'own_flushes' => 2]);
    DB::table('torrents')->update(array_fill_keys(['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6', 'times_completed'], 0));
    config(['dualstack.enabled'          => true, 'announce.external_tracker.is_enabled' => false,
        'dualstack.max_cleanup_requests' => 1000, 'dualstack.allow_private_addresses' => true,
        'cache.prefix'                   => 'dualstack-cleanup-test:'.bin2hex(random_bytes(8))]);
    $this->policy = ['endpoint_ttl' => 7200, 'max_endpoints' => 2, 'max_peers' => 3, 'min_interval' => 0,
        'allow_private_addresses'   => true, 'require_connectivity' => false, 'max_pending_transitions' => 100000];
    $this->credit = ['upload_percent' => 100, 'download_percent' => 100, 'immune' => false];
    $this->identity = ['user_id' => 12001, 'torrent_id' => 12001, 'peer_id' => bin2hex(str_repeat('C', 20))];
    $this->request = ['event' => 'started', 'ip' => '172.29.92.30', 'port' => 6881, 'uploaded' => '1000', 'downloaded' => '0', 'left' => '0', 'visible' => true, 'agent' => 'cleanup-test'];
    $this->lease = TrackerLease::acquire();
    $this->writer = new TransitionWriter($this->lease);
    $this->writer->prepare();
    $this->lease->ready(true);
    $this->journal = new TransitionJournal($this->lease);
    $this->cleanups = new CleanupRequests();
    $this->now = (int) Redis::connection('announce')->time()[0];
});

afterEach(function (): void {
    if (getenv('DUALSTACK_JOURNAL_TESTS') !== '1' || !isset($this->lease)) {
        return;
    }
    $this->lease->release();
    DB::table('tracker_cleanup_requests')->delete();
    $redis = Redis::connection('announce');
    $cursor = '0';

    do {
        [$cursor, $keys] = $redis->command('rawCommand', ['SCAN', $cursor, 'MATCH', TrackerLease::base().':*', 'COUNT', 1000]);

        if ($keys !== []) {
            $redis->command('rawCommand', ['UNLINK', ...$keys]);
        }
    } while ((string) $cursor !== '0');
});

function settleCleanups(object $test): void
{
    for ($i = 0; $i < 20; $i++) {
        $test->lease->renew();
        $pending = $test->cleanups->processNext($test->lease, $test->policy);
        $test->writer->flush('cleanup-test');

        if (!$pending) {
            return;
        }
    }

    throw new RuntimeException('Limpeza nao drenou no limite de lotes do ensaio.');
}

function cleanupUserRequest(): Request
{
    $request = Request::create('/lab/flush', 'DELETE');
    $user = User::findOrFail(12001);
    $request->setUserResolver(fn () => $user);

    return $request;
}

it('enfileira pelo controller sem escrever no swarm e consome cota uma vez', function (): void {
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit, $this->now - 4300);
    $this->journal->publish($this->identity, array_replace($this->request, ['ip' => 'fd42:756e:6974:92::30']), $this->policy, $this->credit, $this->now - 4290);
    $this->writer->flush('setup');
    $before = DB::table('peers')->first();
    $request = cleanupUserRequest();

    foreach ([1, 2] as $attempt) {
        $response = app(PeerController::class)->massDestroy($request, $request->user());
        expect($response->getSession()->get('success'))->toBe(__('dualstack.cleanup-queued'));
    }
    expect(DB::table('tracker_cleanup_requests')->count())->toBe(1)
        ->and((int) User::findOrFail(12001)->own_flushes)->toBe(1)
        ->and(DB::table('peers')->count())->toBe(1)->and(DB::table('peer_ips')->count())->toBe(2)
        ->and((int) DB::table('peers')->value('state_version'))->toBe((int) $before->state_version);
    $this->cleanups->processNext($this->lease, $this->policy);
    expect(DB::table('peer_ips')->count())->toBe(2); // A publicacao ainda nao e commit.
    $messages = $this->writer->read('cleanup');
    expect($messages)->toHaveCount(1)->and(array_values($messages)[0]['operation'])->toBe('flush');
    expect($this->writer->persist($messages))->toBe(1)->and($this->writer->persist($messages))->toBe(0);
    expect(DB::table('tracker_cleanup_requests')->count())->toBe(1);
    $this->writer->acknowledge(array_keys($messages));
    settleCleanups($this);
    expect(DB::table('peer_ips')->count())->toBe(0)->and(DB::table('peers')->count())->toBe(1)
        ->and((string) DB::table('peers')->value('uploaded'))->toBe('1000')
        ->and((bool) DB::table('peers')->value('active'))->toBeFalse()
        ->and((bool) DB::table('history')->value('active'))->toBeFalse()
        ->and((int) DB::table('torrents')->where('id', 12001)->value('seeders'))->toBe(0)
        ->and((string) User::findOrFail(12001)->uploaded)->toBe('0');
});

it('preserva endpoint recente e outro peer do mesmo usuario torrent', function (): void {
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit, $this->now - 4300);
    $this->journal->publish($this->identity, array_replace($this->request, ['ip' => 'fd42:756e:6974:92::30']), $this->policy, $this->credit, $this->now - 10);
    $second = array_replace($this->identity, ['peer_id' => bin2hex(str_repeat('D', 20))]);
    $this->journal->publish($second, $this->request, $this->policy, $this->credit, $this->now - 5);
    $this->writer->flush('setup');
    $this->cleanups->submit(12001);
    settleCleanups($this);
    expect(DB::table('peer_ips')->where('peer_id', hex2bin($this->identity['peer_id']))->pluck('family')->map(fn ($v) => (int) $v)->all())->toBe([6])
        ->and(DB::table('peer_ips')->count())->toBe(2)->and((bool) DB::table('history')->value('active'))->toBeTrue()
        ->and((int) DB::table('torrents')->where('id', 12001)->value('seeders'))->toBe(2);
});

it('revalida o endpoint renovado no journal antes do flush mesmo com SQL atrasado', function (): void {
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit, $this->now - 4300);
    $this->writer->flush('setup');
    $this->cleanups->submit(12001);
    $this->journal->publish($this->identity, array_replace($this->request, ['event' => '', 'ip' => '172.29.92.31', 'uploaded' => '1100']), $this->policy, $this->credit);
    $this->cleanups->processNext($this->lease, $this->policy);
    expect((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions'))->toBe(1);
    settleCleanups($this);
    expect(DB::table('peer_ips')->value('ip'))->toBe(inet_pton('172.29.92.31'))
        ->and((bool) DB::table('peers')->value('active'))->toBeTrue()
        ->and((string) User::findOrFail(12001)->uploaded)->toBe('100');
});

it('mantem corte estrito por usuario e limite administrativo de duas horas', function (): void {
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit, $this->now - 5000);
    $this->writer->flush('setup');
    app(FlushController::class)->peers();
    settleCleanups($this);
    expect(DB::table('peer_ips')->count())->toBe(1)->and((int) User::findOrFail(12001)->own_flushes)->toBe(2);
    $this->cleanups->submit(12002);
    settleCleanups($this);
    expect(DB::table('peer_ips')->count())->toBe(1);
    $this->cleanups->submit(12001);
    DB::table('tracker_cleanup_requests')->update(['cutoff' => gmdate('Y-m-d H:i:s', $this->now - 5000)]);
    settleCleanups($this);
    expect(DB::table('peer_ips')->count())->toBe(1);
    app(FlushController::class)->peers();
    // Relogio de uma fixture antiga: manter bootstrap fora do ensaio para o flush gerar a transicao.
    $keys = $this->journal->keys($this->identity);
    $state = json_decode(Redis::connection('announce')->get($keys[0]), true);
    $state['endpoints'][4]['last_announced_at'] = $this->now - 7300;
    Redis::connection('announce')->set($keys[0], json_encode($state));
    DB::table('peer_ips')->update(['last_announced_at' => gmdate('Y-m-d H:i:s', $this->now - 7300)]);
    settleCleanups($this);
    expect(DB::table('peer_ips')->count())->toBe(0)->and(DB::table('peers')->count())->toBe(1);
});

it('recusa admissao sem proprietario ou com outro backend sem gastar cota', function (string $state): void {
    if ($state === 'external') {
        config(['announce.external_tracker.is_enabled' => true]);
    } elseif ($state === 'rust') {
        DB::table('tracker_ownership')->where('id', 1)->update(['backend' => 'rust']);
    } else {
        $this->lease->release();
    }
    expect(fn () => $this->cleanups->submit(12001))->toThrow(CleanupRejected::class);
    expect(DB::table('tracker_cleanup_requests')->count())->toBe(0)->and((int) User::findOrFail(12001)->own_flushes)->toBe(2);
})->with(['external', 'rust', 'offline']);

it('limita backlog e recusa cota esgotada sem perder solicitacao pendente', function (): void {
    config(['dualstack.max_cleanup_requests' => 1]);
    $id = $this->cleanups->submit(12001);
    expect($this->cleanups->submit(12001))->toBe($id);
    expect(fn () => $this->cleanups->submit(12002))->toThrow(CleanupRejected::class);
    expect((int) User::findOrFail(12002)->own_flushes)->toBe(2);
    settleCleanups($this);
    DB::table('users')->where('id', 12001)->update(['own_flushes' => 0]);
    expect(fn () => $this->cleanups->submit(12001))->toThrow(CleanupRejected::class, 'cleanup-quota');
    expect(DB::table('tracker_cleanup_requests')->count())->toBe(0);
});

it('reverte cota quando a persistencia da solicitacao falha', function (): void {
    DB::statement("ALTER TABLE tracker_cleanup_requests ADD CONSTRAINT dualstack_cleanup_reject CHECK (scope <> 'user:12001')");

    try {
        expect(fn () => $this->cleanups->submit(12001))->toThrow(Illuminate\Database\QueryException::class);
        expect((int) User::findOrFail(12001)->own_flushes)->toBe(2)->and(DB::table('tracker_cleanup_requests')->count())->toBe(0);
    } finally {
        DB::statement('ALTER TABLE tracker_cleanup_requests DROP CHECK dualstack_cleanup_reject');
    }
});

it('preserva solicitacao e credito confirmado ao recuperar nova geracao', function (): void {
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit, $this->now - 4300);
    $this->journal->publish($this->identity, array_replace($this->request, ['uploaded' => '1100']), $this->policy, $this->credit, $this->now - 4290);
    $this->writer->flush('setup');
    $this->cleanups->submit(12001);
    $this->cleanups->processNext($this->lease, $this->policy);
    $messages = $this->writer->read('crashed-worker');
    $this->writer->persist($messages); // Crash depois do commit e antes do ack.
    $this->lease->release();
    expect((bool) DB::table('tracker_ownership')->value('php_journal_drained'))->toBeFalse();
    $this->lease = TrackerLease::acquire();
    (new TrackerRecovery($this->lease, $this->policy))->restore();
    $this->writer = new TransitionWriter($this->lease);
    settleCleanups($this);
    $this->lease->release();
    expect((string) User::findOrFail(12001)->uploaded)->toBe('100')
        ->and((bool) DB::table('tracker_ownership')->value('php_journal_drained'))->toBeTrue()
        ->and((int) User::findOrFail(12001)->own_flushes)->toBe(1);
});

it('drena tarefas com entrada fechada e impede certificar handoff prematuro', function (): void {
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit, $this->now - 4300);
    $this->writer->flush('setup');
    $this->cleanups->submit(12001);
    $old = $this->lease;
    $old->release();
    expect((bool) DB::table('tracker_ownership')->value('php_journal_drained'))->toBeFalse();
    $this->lease = TrackerLease::acquire();
    (new TrackerRecovery($this->lease, $this->policy))->restore();
    $this->writer = new TransitionWriter($this->lease);
    $old->release();
    expect((bool) DB::table('tracker_ownership')->value('php_journal_drained'))->toBeFalse();
    $this->lease->ready(false);
    $this->cleanups->drain($this->lease, $this->policy, $this->writer);
    $this->lease->release();
    expect(DB::table('tracker_cleanup_requests')->count())->toBe(0)->and(DB::table('peer_ips')->count())->toBe(0)
        ->and((bool) DB::table('tracker_ownership')->value('php_journal_drained'))->toBeTrue();
});

function runCleanupRace(array $actions): void
{
    if (!\function_exists('pcntl_fork')) {
        throw new RuntimeException('Exige pcntl para contencao real.');
    }
    $barrier = TrackerLease::base().':cleanup-barrier:'.bin2hex(random_bytes(8));
    DB::disconnect();
    Redis::purge('announce');
    $children = [];

    foreach ($actions as $action) {
        $pid = pcntl_fork();

        if ($pid === -1) {
            throw new RuntimeException('Falha ao iniciar processo.');
        }

        if ($pid === 0) {
            try {
                $redis = Redis::connection('announce');
                $redis->rPush($barrier.':ready', '1');
                $deadline = hrtime(true) + 5e9;

                while (!$redis->lPop($barrier.':go')) {
                    if (hrtime(true) > $deadline) {
                        throw new RuntimeException('Timeout de barreira.');
                    }
                    usleep(1000);
                }
                $action();

                exit(0);
            } catch (Throwable $error) {
                fwrite(STDERR, 'Concorrencia cleanup: '.$error::class."\n");

                exit(1);
            }
        }
        $children[] = $pid;
    }
    $redis = Redis::connection('announce');
    $deadline = hrtime(true) + 5e9;

    while ((int) $redis->lLen($barrier.':ready') !== \count($actions)) {
        if (hrtime(true) > $deadline) {
            throw new RuntimeException('Processos nao chegaram a barreira.');
        }
        usleep(1000);
    }
    $redis->rPush($barrier.':go', ...array_fill(0, \count($actions), '1'));

    foreach ($children as $pid) {
        pcntl_waitpid($pid, $status);
        expect(pcntl_wifexited($status))->toBeTrue()->and(pcntl_wexitstatus($status))->toBe(0);
    }
}

it('deduplica admissao concorrente em quatro processos sem debitar quatro cotas', function (): void {
    $metrics = fn () => DB::table('information_schema.INNODB_METRICS')->whereIn('NAME', ['lock_deadlocks', 'lock_timeouts'])->pluck('COUNT', 'NAME')->all();
    $before = $metrics();
    $this->lease->renew();
    runCleanupRace(array_fill(0, 4, fn () => (new CleanupRequests())->submit(12001)));
    $this->lease->renew();
    expect(DB::table('tracker_cleanup_requests')->count())->toBe(1)
        ->and((int) User::findOrFail(12001)->own_flushes)->toBe(1)
        ->and($metrics())->toBe($before);
});

it('serializa limpeza e announce real em processos separados sem credito duplicado', function (): void {
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit, $this->now - 4300);
    $this->writer->flush('setup');
    $this->cleanups->submit(12001);
    $this->lease->renew();
    runCleanupRace([
        fn () => $this->cleanups->processNext($this->lease, $this->policy),
        fn () => $this->journal->publish($this->identity, array_replace($this->request, ['event' => '', 'uploaded' => '1100', 'ip' => '172.29.92.31']), $this->policy, $this->credit),
    ]);
    settleCleanups($this);
    expect(DB::table('peer_ips')->value('ip'))->toBe(inet_pton('172.29.92.31'))
        ->and((bool) DB::table('peers')->value('active'))->toBeTrue()
        ->and((string) User::findOrFail(12001)->uploaded)->toBe('100')
        ->and((int) DB::table('torrents')->where('id', 12001)->value('seeders'))->toBe(1);
});

it('impede admissao tardia de certificar drenagem falsa durante encerramento', function (): void {
    $this->lease->renew();
    runCleanupRace([
        function (): void {
            try {
                (new CleanupRequests())->submit(12001);
            } catch (CleanupRejected) {
                // O encerramento pode vencer a disputa; nenhuma cota e consumida.
            }
        },
        fn () => $this->lease->release(),
    ]);
    $pending = DB::table('tracker_cleanup_requests')->count();
    expect((bool) DB::table('tracker_ownership')->value('php_journal_drained'))->toBe($pending === 0)
        ->and((int) User::findOrFail(12001)->own_flushes)->toBe(2 - $pending);
});

it('processa solicitacoes em lotes limitados preservando todas as referencias', function (): void {
    for ($id = 0; $id < 60; $id++) {
        $identity = array_replace($this->identity, ['peer_id' => bin2hex(str_pad((string) $id, 20, 'C'))]);
        $policy = array_replace($this->policy, ['max_peers' => 100]);
        $this->journal->publish($identity, $this->request, $policy, $this->credit, $this->now - 4300);
    }
    $this->writer->flush('setup');
    $this->cleanups->submit(12001);
    $this->cleanups->processNext($this->lease, $this->policy);
    expect((int) Redis::connection('announce')->xLen(TrackerLease::base().':transitions'))->toBe(25);
    settleCleanups($this);
    expect(DB::table('peer_ips')->count())->toBe(0)->and(DB::table('peers')->count())->toBe(60)
        ->and(DB::table('peers')->where('active', true)->count())->toBe(0);
});
