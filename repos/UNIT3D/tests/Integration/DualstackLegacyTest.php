<?php

declare(strict_types=1);

use App\Services\Dualstack\LegacyReconciliation;
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
        $this->markTestSkipped('Exige MySQL/Redis reais, banco isolado e DUALSTACK_JOURNAL_TESTS=1.');
    }
    expect(DB::getDriverName())->toBe('mysql')->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    DB::table('peers')->delete();
    DB::table('history')->delete();
    DB::table('tracker_cleanup_requests')->delete();
    DB::table('users')->update(['uploaded' => 0, 'downloaded' => 0, 'tracker_removal_state' => 0]);
    DB::table('torrents')->update(array_fill_keys(['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6', 'times_completed', 'balance', 'tracker_removal_state'], 0));
    DB::table('tracker_ownership')->where('id', 1)->update(['legacy_reconciliation_required' => false, 'lease_expires_at' => null]);
    config(['cache.prefix'                  => 'dualstack-legacy-test:'.bin2hex(random_bytes(8)), 'dualstack.enabled' => false,
        'dualstack.allow_private_addresses' => true, 'dualstack.require_connectivity' => false, 'dualstack.endpoint_ttl' => 7200,
        'queue.default'                     => 'redis', 'queue.connections.redis.queue' => 'dualstack-legacy-test:'.bin2hex(random_bytes(8))]);
    // Cada conexao recebe uma fila exclusiva sem invalidar conexoes de outros testes.
    $queueConnection = config('queue.connections.redis.queue');
    config(['queue.default' => $queueConnection, 'queue.connections.'.$queueConnection => config('queue.connections.redis')]);
    $this->policy = ['endpoint_ttl' => 7200, 'max_endpoints' => 2, 'max_peers' => 3, 'min_interval' => 0,
        'allow_private_addresses'   => true, 'require_connectivity' => false, 'max_pending_transitions' => 1000];
    $this->credit = ['upload_percent' => 100, 'download_percent' => 100, 'immune' => false];
    $this->identity = ['user_id' => 12001, 'torrent_id' => 12001, 'peer_id' => bin2hex(str_repeat('A', 20))];
    $this->request = ['event' => 'started', 'ip' => '172.29.92.30', 'port' => 6881, 'uploaded' => '1000', 'downloaded' => '0', 'left' => '0', 'visible' => true, 'agent' => 'legacy-test'];
    $this->lease = TrackerLease::acquire();
    $this->writer = new TransitionWriter($this->lease);
    $this->writer->prepare();
    $this->lease->ready(true);
    $this->journal = new TransitionJournal($this->lease);
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit);
    $this->journal->publish($this->identity, array_replace($this->request, ['ip' => 'fd42:756e:6974:92::30', 'uploaded' => '1100']), $this->policy, $this->credit);
    $this->writer->flush('test');
    $this->lease->release();
    $this->maintenance = new LegacyReconciliation();
});

afterEach(function (): void {
    if (!isset($this->lease)) {
        return;
    }
    $this->lease->release();
    DB::table('tracker_ownership')->where('id', 1)->update(['legacy_reconciliation_required' => false, 'lease_expires_at' => null]);
    DB::table('users')->update(['tracker_removal_state' => 0]);
    $redis = Redis::connection('announce');
    $cursor = '0';

    do {
        [$cursor, $keys] = $redis->command('rawCommand', ['SCAN', $cursor, 'MATCH', config('cache.prefix').':*', 'COUNT', 1000]);

        if ($keys !== []) {
            $redis->command('rawCommand', ['UNLINK', ...$keys]);
        }
    } while ((string) $cursor !== '0');
});

it('exige preparacao offline explicita e preserva o bloqueio ao repetir a migracao', function (): void {
    $kernel = app(Kernel::class);
    expect($kernel->call('dualstack:legacy', ['action' => 'prepare']))->toBe(1);
    expect(fn () => $this->maintenance->run('reconcile', 1))->toThrow(RuntimeException::class, 'Execute prepare');
    config(['dualstack.enabled' => true]);
    expect($kernel->call('dualstack:legacy', ['action' => 'prepare', '--offline' => true]))->toBe(1);
    config(['dualstack.enabled' => false]);
    expect($kernel->call('dualstack:legacy', ['action' => 'prepare', '--offline' => true, '--batch' => 2001]))->toBe(1);
    expect($kernel->call('dualstack:legacy', ['action' => 'prepare', '--offline' => true]))->toBe(0);
    $migration = require __DIR__.'/../../database/migrations/2026_10_08_000006_add_dualstack_legacy_reconciliation.php';
    $migration->up();
    $migration->up();
    expect((bool) DB::table('tracker_ownership')->value('legacy_reconciliation_required'))->toBeTrue();
    $generation = DB::table('tracker_ownership')->value('generation');
    expect(fn () => TrackerLease::acquire())->toThrow(RuntimeException::class, 'Reconciliacao legada pendente');
    expect(DB::table('tracker_ownership')->value('generation'))->toBe($generation);
});

it('recusa proprietario ativo e journal ainda nao certificado', function (): void {
    $this->lease = TrackerLease::acquire();
    expect(fn () => $this->maintenance->run('prepare', 1))->toThrow(RuntimeException::class, 'proprietario ativo');
    DB::table('tracker_ownership')->update(['lease_expires_at' => null]);
    expect(fn () => $this->maintenance->run('prepare', 1))->toThrow(RuntimeException::class, 'journal PHP');
    expect((bool) DB::table('tracker_ownership')->value('legacy_reconciliation_required'))->toBeFalse();
});

it('preserva filas legadas pendentes e recusa manutencao', function (string $name): void {
    $key = config('cache.prefix').':'.$name.':batch';
    Redis::connection('announce')->rPush($key, 'pendente');
    expect(fn () => $this->maintenance->run('prepare', 1))->toThrow(RuntimeException::class, 'lotes legados');
    expect(Redis::connection('announce')->lLen($key))->toBe(1);
})->with(['peers', 'histories', 'announces']);

it('recusa journal e remocoes pendentes sem apagar trabalho', function (): void {
    $key = TrackerLease::base().':transitions';
    Redis::connection('announce')->xAdd($key, '*', ['test' => 'pendente']);
    expect(fn () => $this->maintenance->run('prepare', 1))->toThrow(RuntimeException::class, 'fila de jobs');
    expect(Redis::connection('announce')->xLen($key))->toBe(1);
    Redis::connection('announce')->del($key);
    DB::table('users')->where('id', 12001)->update(['tracker_removal_state' => 1]);
    expect(fn () => $this->maintenance->run('prepare', 1))->toThrow(RuntimeException::class, 'remocoes pendentes');
});

it('recusa jobs prontos reservados e atrasados na fila real', function (string $suffix, bool $sorted): void {
    $key = 'queues:'.config('queue.connections.redis.queue').$suffix;
    $redis = Redis::connection('job');

    try {
        $sorted ? $redis->zAdd($key, time() + 60, 'pendente') : $redis->rPush($key, 'pendente');
        expect(fn () => $this->maintenance->run('prepare', 1))->toThrow(RuntimeException::class, 'fila de jobs');
    } finally {
        $redis->del($key);
    }
})->with([['', false], [':reserved', true], [':delayed', true]]);

it('exclui outra manutencao em conexao MySQL independente', function (): void {
    $config = config('database.connections.mysql');
    config(['database.connections.legacy_lock_test' => $config]);
    $second = DB::connection('legacy_lock_test');
    $lock = 'dualstack:legacy:'.substr(hash('sha256', DB::getDatabaseName()), 0, 40);

    try {
        expect((int) $second->selectOne('SELECT GET_LOCK(?, 0) AS acquired', [$lock])->acquired)->toBe(1);
        expect(fn () => $this->maintenance->run('prepare', 1))->toThrow(RuntimeException::class, 'Outra reconciliacao');
    } finally {
        $second->selectOne('SELECT RELEASE_LOCK(?)', [$lock]);
        DB::purge('legacy_lock_test');
    }
});

it('reconstroi peers versionados sem alterar contabilidade e retoma PHP sem duplicar credito', function (): void {
    $this->maintenance->run('prepare', 1);
    // Simula o snapshot gravado pelo legado; ensaio das tags originais e separado.
    DB::table('peers')->update(['ip' => inet_pton('::ffff:172.29.92.31'), 'uploaded' => 1200, 'updated_at' => now()]);
    DB::table('users')->where('id', 12001)->update(['uploaded' => 200, 'seedbonus' => 123]);
    DB::table('history')->update(['uploaded' => 200, 'actual_uploaded' => 200, 'seedtime' => 456,
        'refunded_download'                  => 7, 'updated_at' => now(), 'completed_at' => now()]);
    $money = DB::table('users')->where('id', 12001)->first(['uploaded', 'downloaded', 'seedbonus']);
    $history = DB::table('history')->first();
    $version = DB::table('peers')->value('state_version');
    expect($this->maintenance->run('reconcile', 1))->toBe(1);
    $endpoint = DB::table('peer_ips')->sole();
    expect((int) $endpoint->family)->toBe(4)->and($endpoint->ip)->toBe(inet_pton('172.29.92.31'));
    expect(DB::table('peers')->value('protocol_state'))->toBeNull();
    expect(DB::table('peers')->value('state_version'))->toBe($version);
    expect(DB::table('history')->value('swarm_updated_at'))->toBe($history->updated_at);
    expect(DB::table('users')->where('id', 12001)->first(['uploaded', 'downloaded', 'seedbonus']))->toEqual($money);

    foreach (['uploaded', 'actual_uploaded', 'downloaded', 'actual_downloaded', 'refunded_download', 'seedtime', 'completed_at', 'state_version'] as $field) {
        expect(DB::table('history')->value($field))->toBe($history->$field);
    }
    $snapshot = DB::table('peer_ips')->get()->all();
    $this->maintenance->run('prepare', 1);
    $this->maintenance->run('reconcile', 1);
    expect(DB::table('peer_ips')->get()->all())->toEqual($snapshot);
    expect((int) DB::table('torrents')->where('id', 12001)->value('seeders'))->toBe(1);
    expect((int) DB::table('torrents')->where('id', 12001)->value('seeders_ipv6'))->toBe(0);
    $oldLease = $this->lease;
    $this->lease = TrackerLease::acquire();
    (new TrackerRecovery($this->lease, $this->policy))->restore();
    $journal = new TransitionJournal($this->lease);
    $request = array_replace($this->request, ['ip' => '172.29.92.31', 'uploaded' => '1200', 'event' => 'completed']);
    expect($journal->publish($this->identity, $request, $this->policy, $this->credit)['upload_delta'])->toBe('0');
    $request['uploaded'] = '1300';
    expect($journal->publish($this->identity, $request, $this->policy, $this->credit)['upload_delta'])->toBe('100');
    (new TransitionWriter($this->lease))->flush('test');
    expect((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('300');
    expect((int) DB::table('torrents')->where('id', 12001)->value('times_completed'))->toBe(0);
    expect(fn () => DB::transaction(fn () => $oldLease->assertPersistable()))->toThrow(RuntimeException::class, 'geracao expirados');
});

it('mantem bloqueio apos falha parcial e retoma em lotes sem ressuscitar endpoints', function (): void {
    $peer = (array) DB::table('peers')->first();
    DB::table('peers')->insert(array_replace($peer, ['peer_id' => str_repeat('B', 20), 'port' => 0, 'connectable' => true]));
    $this->maintenance->run('prepare', 1);
    expect(fn () => $this->maintenance->run('reconcile', 1))->toThrow(RuntimeException::class, 'porta ou versao');
    expect(DB::table('peer_ips')->count())->toBe(1);
    expect(fn () => TrackerLease::acquire())->toThrow(RuntimeException::class, 'Reconciliacao legada');
    DB::table('peers')->where('peer_id', str_repeat('B', 20))->update(['active' => false]);
    DB::table('peers')->where('peer_id', str_repeat('A', 20))->update(['updated_at' => now()->subSeconds(7201)]);
    expect($this->maintenance->run('reconcile', 1))->toBe(2);
    expect(DB::table('peer_ips')->count())->toBe(0)->and(DB::table('peers')->where('active', true)->count())->toBe(0);
    expect(DB::table('peers')->where('connectable', true)->count())->toBe(0);
    expect((bool) DB::table('history')->value('active'))->toBeFalse();
    expect((int) DB::table('torrents')->where('id', 12001)->value('seeders'))->toBe(0);
    expect((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('100');
});

it('interrompe a reconciliacao se perder a conexao que possui a exclusao', function (): void {
    $this->maintenance->run('prepare', 1);
    $dispatcher = DB::connection()->getEventDispatcher();
    DB::connection()->setEventDispatcher(clone $dispatcher);
    $disconnected = false;
    DB::listen(function ($event) use (&$disconnected): void {
        if (!$disconnected && str_starts_with($event->sql, 'select * from `peers` order by')) {
            $disconnected = true;
            DB::disconnect();
        }
    });

    try {
        expect(fn () => $this->maintenance->run('reconcile', 1))->toThrow(RuntimeException::class, 'perdeu a exclusao');
        expect($disconnected)->toBeTrue();
        expect((bool) DB::table('tracker_ownership')->value('legacy_reconciliation_required'))->toBeTrue();
        expect(DB::table('peer_ips')->count())->toBe(2);
    } finally {
        DB::connection()->setEventDispatcher($dispatcher);
    }
    expect($this->maintenance->run('reconcile', 1))->toBe(1);
});
