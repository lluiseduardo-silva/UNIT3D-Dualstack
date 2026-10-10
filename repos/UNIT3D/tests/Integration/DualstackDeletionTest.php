<?php

declare(strict_types=1);

use App\Models\User;
use App\Services\Dualstack\DeletedEntities;
use App\Services\Dualstack\TrackerLease;
use App\Services\Dualstack\TrackerRecovery;
use App\Services\Dualstack\TransitionJournal;
use App\Services\Dualstack\TransitionWriter;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;
use Illuminate\Support\Facades\Notification;
use Illuminate\Support\Facades\Queue;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});
beforeEach(function (): void {
    if (getenv('DUALSTACK_JOURNAL_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL/Redis reais e banco exclusivo.');
    }
    expect(DB::getDriverName())->toBe('mysql')->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();

    foreach ([20 => 'disabled', 21 => 'pruned'] as $id => $slug) {
        if (!DB::table('groups')->where('id', $id)->exists()) {
            $group = (array) DB::table('groups')->where('id', 3)->first();
            DB::table('groups')->insert(array_replace($group, ['id' => $id,'name' => 'Deletion fixture '.$slug,'slug' => $slug]));
        }
    }

    if (!DB::table('users')->where('id', 1)->exists()) {
        $system = (array) DB::table('users')->where('id', 12002)->first();

        try {
            DB::table('users')->insert(array_replace($system, ['id' => 1,'username' => 'deletion-system-fixture','email' => 'deletion-system@example.invalid',
                'password'                                          => '!', 'passkey' => bin2hex(random_bytes(16)), 'rsskey' => bin2hex(random_bytes(16)), 'api_token' => (string) Illuminate\Support\Str::uuid(),
                'remember_token'                                    => null,'two_factor_secret' => null,'two_factor_recovery_codes' => null]));
        } catch (Illuminate\Database\QueryException $error) {
            throw new RuntimeException('Falha na fixture do usuario de sistema; SQLSTATE '.$error->getCode());
        }
    }
    DB::table('peers')->delete();
    DB::table('history')->delete();
    DB::table('tracker_cleanup_requests')->delete();
    DB::table('users')->whereBetween('id', [12001, 12020])->update(['deleted_at' => null, 'tracker_removal_state' => 0, 'uploaded' => 0, 'downloaded' => 0, 'group_id' => 3, 'can_download' => true]);
    DB::table('torrents')->whereBetween('id', [12001, 12020])->update(['deleted_at' => null, 'tracker_removal_state' => 0, 'user_id' => 12001] + array_fill_keys(['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6', 'times_completed'], 0));
    config(['dualstack.enabled' => true, 'announce.external_tracker.is_enabled' => false, 'dualstack.require_connectivity' => false, 'dualstack.allow_private_addresses' => true,
        'cache.prefix'          => 'dualstack-deletion-test:'.bin2hex(random_bytes(8))]);
    $this->policy = ['endpoint_ttl' => 7200, 'max_endpoints' => 2, 'max_peers' => 300, 'min_interval' => 0,
        'allow_private_addresses'   => true, 'require_connectivity' => false, 'max_pending_transitions' => 100000];
    $this->credit = ['upload_percent' => 100, 'download_percent' => 100, 'immune' => false];
    $this->identity = ['user_id' => 12001, 'torrent_id' => 12001, 'peer_id' => bin2hex(str_repeat('E', 20))];
    $this->request = ['event' => 'started', 'ip' => '172.29.92.30', 'port' => 6881, 'uploaded' => '1000', 'downloaded' => '0', 'left' => '0', 'visible' => true, 'agent' => 'deletion-test'];
    $this->lease = TrackerLease::acquire();
    $this->writer = new TransitionWriter($this->lease);
    $this->writer->prepare();
    $this->lease->ready(true);
    $this->journal = new TransitionJournal($this->lease);
    $this->deletions = new DeletedEntities();
    $this->journal->publish($this->identity, $this->request, $this->policy, $this->credit);
    $this->journal->publish($this->identity, array_replace($this->request, ['ip' => 'fd42:756e:6974:92::30']), $this->policy, $this->credit);
    $this->writer->flush('setup');
});
afterEach(function (): void {
    if (!isset($this->lease)) {
        return;
    }
    $this->lease->release();

    foreach (['users', 'torrents'] as $table) {
        DB::table($table)->whereBetween('id', [12001, 12020])->update(['deleted_at' => null, 'tracker_removal_state' => 0]);
    }
    $redis = Redis::connection('announce');
    $cursor = '0';

    do {
        [$cursor,$keys] = $redis->command('rawCommand', ['SCAN',$cursor,'MATCH',TrackerLease::base().':*','COUNT',1000]);

        if ($keys !== []) {
            $redis->command('rawCommand', ['UNLINK',...$keys]);
        }
    } while ((string) $cursor !== '0');
});
function settleDeletions(object $test): void
{
    for ($i = 0;$i < 20;$i++) {
        $test->lease->renew();

        if (!$test->deletions->processNext($test->lease, $test->writer)) {
            return;
        }
    }

    throw new RuntimeException('Remocao nao drenou.');
}

it('confirma credito pendente antes de remover e ignora reentrega antiga', function (string $table): void {
    $this->journal->publish($this->identity, array_replace($this->request, ['uploaded' => '1100']), $this->policy, $this->credit);
    $messages = $this->writer->read('crashed');
    $this->writer->persist($messages); // Commit anterior ao ack.
    DB::table($table)->where('id', 12001)->update(['deleted_at' => now()]);
    settleDeletions($this);
    expect($this->writer->persist($messages))->toBe(0)
        ->and((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('100')
        ->and(DB::table('peers')->count())->toBe(0)->and(DB::table('peer_ips')->count())->toBe(0)->and(DB::table('history')->count())->toBe(0)
        ->and((int) DB::table($table)->where('id', 12001)->value('tracker_removal_state'))->toBe(2)
        ->and((int) DB::table('torrents')->where('id', 12001)->value('seeders'))->toBe(0);
    expect($this->journal->publish($this->identity, $this->request, $this->policy, $this->credit)['reason'])->toBe('removed');
})->with(['users','torrents']);

it('preserva outros recursos e deduz peers logicos sem duplicar familias', function (): void {
    $other = array_replace($this->identity, ['user_id' => 12002]);
    $this->journal->publish($other, $this->request, $this->policy, $this->credit);
    $this->journal->publish($other, array_replace($this->request, ['uploaded' => '1100']), $this->policy, $this->credit);
    DB::table('users')->where('id', 12001)->update(['deleted_at' => now()]);
    settleDeletions($this);
    expect(DB::table('peers')->count())->toBe(1)->and(DB::table('history')->count())->toBe(1)
        ->and((string) DB::table('users')->where('id', 12002)->value('uploaded'))->toBe('100')
        ->and((int) DB::table('torrents')->where('id', 12001)->value('seeders'))->toBe(1)
        ->and((int) DB::table('torrents')->where('id', 12001)->value('seeders_ipv4'))->toBe(1)
        ->and((int) DB::table('torrents')->where('id', 12001)->value('seeders_ipv6'))->toBe(0);
    expect($this->journal->publish($other, array_replace($this->request, ['uploaded' => '1200']), $this->policy, $this->credit)['outcome'])->toBe('accepted');
    $this->writer->flush('remaining');
    expect((string) DB::table('users')->where('id', 12002)->value('uploaded'))->toBe('200');
});

it('retoma remocao selada depois de rollback SQL e restart sem recreditar', function (): void {
    $this->journal->publish($this->identity, array_replace($this->request, ['uploaded' => '1100']), $this->policy, $this->credit);
    DB::table('users')->where('id', 12001)->update(['deleted_at' => now()]);
    $name = DB::table('torrents')->where('id', 12001)->value('name');
    DB::table('torrents')->where('id', 12001)->update(['name' => 'dualstack-deletion-failure']);
    DB::statement("ALTER TABLE torrents ADD CONSTRAINT dualstack_deletion_failure CHECK (name<>'dualstack-deletion-failure' OR seeders>0)");

    try {
        expect(fn () => $this->deletions->processNext($this->lease, $this->writer))->toThrow(Illuminate\Database\QueryException::class);
        expect(DB::table('peers')->count())->toBe(1)->and(DB::table('peer_ips')->count())->toBe(2)
            ->and((int) DB::table('users')->where('id', 12001)->value('tracker_removal_state'))->toBe(1)
            ->and((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('100');
    } finally {
        DB::statement('ALTER TABLE torrents DROP CHECK dualstack_deletion_failure');
        DB::table('torrents')->where('id', 12001)->update(['name' => $name]);
    }
    $this->lease->release();
    $this->lease = TrackerLease::acquire();
    (new TrackerRecovery($this->lease, $this->policy))->restore();
    $this->writer = new TransitionWriter($this->lease);
    $this->journal = new TransitionJournal($this->lease);
    expect($this->journal->publish($this->identity, $this->request, $this->policy, $this->credit)['reason'])->toBe('removed');
    settleDeletions($this);
    expect(DB::table('peers')->count())->toBe(0)->and(DB::table('history')->count())->toBe(0)
        ->and((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('100');
});

it('remove no maximo duzentos peers por lote', function (): void {
    for ($i = 0;$i < 205;$i++) {
        $id = array_replace($this->identity, ['peer_id' => bin2hex(str_pad((string) $i, 20, 'E'))]);
        $this->journal->publish($id, $this->request, $this->policy, $this->credit);
    }
    DB::table('users')->where('id', 12001)->update(['deleted_at' => now()]);
    $this->deletions->processNext($this->lease, $this->writer);
    expect(DB::table('peers')->count())->toBe(6)->and((int) DB::table('torrents')->where('id', 12001)->value('seeders'))->toBe(6);
    settleDeletions($this);
    expect(DB::table('peers')->count())->toBe(0)->and((int) DB::table('torrents')->where('id', 12001)->value('seeders'))->toBe(0);
});

it('mantem peers e historico nos caminhos do site ate o coordenador confirmar', function (string $action): void {
    Notification::fake();
    Queue::fake();
    $user = User::findOrFail(12001);
    $admin = User::findOrFail(12002);
    $admin->setRelation('group', new App\Models\Group(['is_modo' => true]));
    auth()->setUser($admin);
    $request = Request::create('/lab/remove', 'DELETE', ['message' => 'fixture']);
    $request->setUserResolver(fn () => $admin);

    if ($action === 'torrent') {
        app(App\Http\Controllers\TorrentController::class)->destroy($request, 12001);
    } elseif ($action === 'bulk') {
        deletionBulkComponent()->deleteRecords();
    } elseif ($action === 'user') {
        (new ReflectionMethod(App\Http\Controllers\Staff\UserController::class, 'destroy'))->invoke(app(App\Http\Controllers\Staff\UserController::class), $request, $user);
    } else {
        config(['pruning.user_pruning' => true,'pruning.soft_delete' => 1]);
        DB::table('users')->where('id', 12001)->update(['group_id' => 20,'disabled_at' => now()->subDays(3)]);
        Illuminate\Support\Facades\Artisan::call('auto:softdelete_disabled_users');
    }
    expect(DB::table(\in_array($action, ['torrent', 'bulk'], true) ? 'torrents' : 'users')->where('id', 12001)->value('deleted_at'))->not->toBeNull();
    expect(DB::table('peers')->count())->toBe(1)->and(DB::table('peer_ips')->count())->toBe(2)->and(DB::table('history')->count())->toBe(1);
    settleDeletions($this);
    expect(DB::table('peers')->count())->toBe(0)->and(DB::table('history')->count())->toBe(0);
})->with(['torrent','user','automatic','bulk']);

it('bloqueia announce concorrente antes de esperar lock SQL sem aumentar deadlocks', function (): void {
    expect(\function_exists('pcntl_fork'))->toBeTrue();
    $metrics = fn () => DB::table('information_schema.INNODB_METRICS')->whereIn('NAME', ['lock_deadlocks','lock_timeouts'])->pluck('COUNT', 'NAME')->all();
    $before = $metrics();
    DB::table('users')->where('id', 12001)->update(['deleted_at' => now()]);
    $barrier = TrackerLease::base().':race';
    DB::disconnect();
    Redis::purge('announce');
    $pid = pcntl_fork();

    if ($pid === 0) {
        try {
            $deadline = hrtime(true) + 5e9;

            while (!Redis::connection('announce')->get($barrier)) {
                if (hrtime(true) > $deadline) {
                    throw new RuntimeException('Barreira');
                } usleep(1000);
            }
            $this->deletions->processNext($this->lease, $this->writer);

            exit(0);
        } catch (Throwable $e) {
            fwrite(STDERR, $e::class."\n");

            exit(1);
        }
    }
    expect($pid)->toBeGreaterThan(0);
    DB::beginTransaction();
    DB::table('users')->where('id', 12001)->lockForUpdate()->first();
    Redis::connection('announce')->set($barrier, 'go');

    try {
        $deadline = hrtime(true) + 5e9;

        while (!Redis::connection('announce')->sIsMember($this->lease->prefix().':deleted-users', 12001)) {
            if (hrtime(true) > $deadline) {
                throw new RuntimeException('Fence ausente');
            } usleep(1000);
        }
        expect($this->journal->publish($this->identity, array_replace($this->request, ['uploaded' => '9999']), $this->policy, $this->credit)['reason'])->toBe('removed');
    } finally {
        DB::commit();
        pcntl_waitpid($pid, $status);
    }
    expect(pcntl_wifexited($status))->toBeTrue()->and(pcntl_wexitstatus($status))->toBe(0);
    settleDeletions($this);
    expect($metrics())->toBe($before)->and((string) DB::table('users')->where('id', 12001)->value('uploaded'))->toBe('0');
});

it('recusa backend externo sem capacidade antes de alterar usuario ou torrent', function (string $action): void {
    $http = Illuminate\Support\Facades\Http::class;
    $http::swap(new Illuminate\Http\Client\Factory());
    $http::preventStrayRequests();
    config(['announce.external_tracker' => ['is_enabled' => true,'host' => 'dualstack.test','port' => 80,'unix_socket' => null,'key' => str_repeat('a', 32)]]);
    $http::fake(['*' => $http::response(['dualstack' => true,'peer_schema' => 1,'peer_count' => 'unique','max_endpoints' => 2])]);
    $user = User::findOrFail(12001);
    $admin = User::findOrFail(12002);
    $admin->setRelation('group', new App\Models\Group(['is_modo' => true]));
    auth()->setUser($admin);
    $request = Request::create('/lab/remove', 'DELETE', ['message' => 'fixture']);
    $request->setUserResolver(fn () => $admin);

    if ($action === 'torrent') {
        $call = fn () => app(App\Http\Controllers\TorrentController::class)->destroy($request, 12001);
    } elseif ($action === 'bulk') {
        $call = fn () => deletionBulkComponent()->deleteRecords();
    } elseif ($action === 'user') {
        $call = fn () => (new ReflectionMethod(App\Http\Controllers\Staff\UserController::class, 'destroy'))->invoke(app(App\Http\Controllers\Staff\UserController::class), $request, $user);
    } else {
        config(['pruning.user_pruning' => true,'pruning.soft_delete' => 1]);
        DB::table('users')->where('id', 12001)->update(['group_id' => 20,'disabled_at' => now()->subDays(3)]);
        $call = fn () => Illuminate\Support\Facades\Artisan::call('auto:softdelete_disabled_users');
    }
    expect($call)->toThrow(Symfony\Component\HttpKernel\Exception\HttpException::class);
    expect(DB::table('users')->where('id', 12001)->value('deleted_at'))->toBeNull()
        ->and(DB::table('torrents')->where('id', 12001)->value('deleted_at'))->toBeNull()
        ->and(DB::table('peers')->count())->toBe(1)->and(DB::table('history')->count())->toBe(1);
    $http::swap(new Illuminate\Http\Client\Factory());
    $http::preventStrayRequests();
    $http::fake(['*' => $http::response(['dualstack' => true,'peer_schema' => 1,'peer_count' => 'unique','max_endpoints' => 2,'coordinated_deletion' => true])]);
    DeletedEntities::assertSupported();
})->with(['torrent','user','automatic','bulk']);

function deletionBulkComponent(): App\Http\Livewire\SimilarTorrent
{
    $component = new App\Http\Livewire\SimilarTorrent();
    $component->category = new App\Models\Category(['movie_meta' => false, 'tv_meta' => false, 'game_meta' => false]);
    $component->checked = [12001];
    $component->reason = 'fixture';

    return $component;
}

it('deduz somente endpoints publicaveis quando a conectividade positiva e exigida', function (): void {
    config(['dualstack.require_connectivity' => true]);
    $this->policy['require_connectivity'] = true;
    // Reconciliacao da fixture ao trocar a politica: endpoints inicialmente desconhecidos.
    DB::table('torrents')->where('id', 12001)->update(['seeders' => 0,'seeders_ipv4' => 0,'seeders_ipv6' => 0]);
    $this->journal->publish($this->identity, ['kind' => 'probe','ip' => 'fd42:756e:6974:92::30','port' => 6881,'revision' => 2,'connectable' => true], $this->policy, $this->credit);
    $this->writer->flush('probe');
    expect((int) DB::table('torrents')->where('id', 12001)->value('seeders'))->toBe(1);
    DB::table('users')->where('id', 12001)->update(['deleted_at' => now()]);
    settleDeletions($this);
    expect((int) DB::table('torrents')->where('id', 12001)->value('seeders'))->toBe(0)
        ->and((int) DB::table('torrents')->where('id', 12001)->value('seeders_ipv4'))->toBe(0)
        ->and((int) DB::table('torrents')->where('id', 12001)->value('seeders_ipv6'))->toBe(0);
});
