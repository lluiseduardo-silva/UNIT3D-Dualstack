<?php

declare(strict_types=1);

use App\Http\Controllers\StatsController;
use App\Models\User;
use App\Notifications\ResurrectionCompleted;
use App\Repositories\ChatRepository;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Notification;
use Illuminate\Support\Facades\Queue;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

beforeEach(function (): void {
    if (getenv('DUALSTACK_CONSUMER_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL real e banco isolado unit3d_dualstack_journal_test.');
    }
    expect(DB::getDriverName())->toBe('mysql')->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    DB::beginTransaction();
    Carbon::setTestNow('2026-10-08 12:00:00');
    config(['dualstack.enabled'                => true, 'cache.default' => 'array', 'scout.driver' => 'null',
        'announce.external_tracker.is_enabled' => false, 'concurrency.default' => 'sync',
        'other.refundable'                     => true, 'hitrun.seedtime' => 3600, 'graveyard.reward' => 5]);
    cache()->flush();
    Http::preventStrayRequests();
    Http::fake();
    Notification::fake();
    Queue::fake();
    $chat = Mockery::mock(ChatRepository::class);
    $chat->shouldReceive('systemMessage')->andReturnSelf();
    app()->instance(ChatRepository::class, $chat);
    DB::table('peers')->delete();
    DB::table('history')->delete();
    DB::table('resurrections')->delete();
    $group = DB::table('groups')->orderBy('id')->value('id');
    expect($group)->not->toBeNull();
    DB::table('users')->where('id', 12001)->update(['group_id' => $group, 'downloaded' => 10000, 'fl_tokens' => 0, 'deleted_at' => null, 'tracker_removal_state' => 0]);
    DB::table('torrents')->whereIn('id', [12001, 12002])->update(['user_id' => 12002, 'size' => 1000, 'status' => 1,
        'deleted_at'                                                        => null, 'tracker_removal_state' => 0, 'free' => 0]);
    $this->user = User::findOrFail(12001);
    auth()->setUser($this->user);
});

afterEach(function (): void {
    Carbon::setTestNow();

    if (getenv('DUALSTACK_CONSUMER_TESTS') === '1' && DB::transactionLevel() > 0) {
        DB::rollBack();
    }
});

function consumerPeer(int $torrent, string $letter, array $families, bool $seeder = true, int $user = 12001): void
{
    $identity = ['user_id' => $user, 'torrent_id' => $torrent, 'peer_id' => str_repeat($letter, 20)];
    DB::table('peers')->insert($identity + ['ip' => inet_pton('192.0.2.30'), 'port' => 6881,
        'agent'                                  => 'consumer-test/1.0', 'uploaded' => 1000, 'downloaded' => 0, 'left' => $seeder ? 0 : 1000,
        'seeder'                                 => $seeder, 'active' => true, 'visible' => true, 'connectable' => true,
        'created_at'                             => now()->subHour(), 'updated_at' => now()]);

    foreach ($families as $family) {
        DB::table('peer_ips')->insert($identity + ['family' => $family, 'ip' => inet_pton($family === 4 ? '192.0.2.30' : '2001:db8::30'),
            'port'                                          => 6881, 'connectable' => true, 'revision' => 1, 'last_announced_at' => now(), 'created_at' => now(), 'updated_at' => now()]);
    }
}

function consumerHistory(int $torrent, int $seedtime): void
{
    DB::table('history')->insert(['user_id' => 12001, 'torrent_id' => $torrent, 'agent' => 'consumer-test/1.0',
        'client_uploaded'                   => 1000, 'client_downloaded' => 1000, 'actual_downloaded' => 1000, 'downloaded' => 1000,
        'refunded_download'                 => 0, 'active' => true, 'seeder' => true, 'immune' => false, 'seedtime' => $seedtime,
        'created_at'                        => now()->subDays(2), 'updated_at' => now()]);
}

it('mantem estatisticas por peer e torrent independentemente das familias', function (array $families): void {
    consumerPeer(12001, 'A', $families);
    consumerPeer(12001, 'B', $families);
    consumerPeer(12002, 'C', $families, false);
    $controller = app(StatsController::class);
    expect((int) $controller->seeders()->getData()['seeders']->firstWhere('user_id', 12001)->value)->toBe(1);
    expect((int) $controller->leechers()->getData()['leechers']->firstWhere('user_id', 12001)->value)->toBe(1);
    $clients = $controller->clients()->getData()['clients'];
    expect((int) $clients['consumer-test']['peer_count'])->toBe(3)
        ->and((int) $clients['consumer-test']['user_count'])->toBe(1)
        ->and((int) $clients['consumer-test']['torrent_count'])->toBe(2);
})->with(['ipv4' => [[4]], 'ipv6' => [[6]], 'dualstack' => [[4, 6]]]);

it('recompensa ressurreicao uma vez no limiar do historico sem multiplicar endpoints', function (array $families): void {
    consumerPeer(12001, 'A', $families);
    consumerPeer(12001, 'B', $families);
    consumerHistory(12001, 3599);
    DB::table('resurrections')->insert(['user_id' => 12001, 'torrent_id' => 12001, 'seedtime' => 3600, 'rewarded' => false,
        'created_at'                              => now()->subDay(), 'updated_at' => now()]);
    expect(app(Kernel::class)->call('auto:reward_resurrection'))->toBe(0);
    expect((int) $this->user->fresh()->fl_tokens)->toBe(0);
    DB::table('history')->where('user_id', 12001)->update(['seedtime' => 3600]);

    foreach (range(1, 2) as $retry) {
        expect(app(Kernel::class)->call('auto:reward_resurrection'))->toBe(0);
    }
    expect((int) $this->user->fresh()->fl_tokens)->toBe(5)
        ->and((bool) DB::table('resurrections')->value('rewarded'))->toBeTrue()
        ->and((int) DB::table('torrents')->where('id', 12001)->value('free'))->toBe(100);
    Notification::assertSentToTimes($this->user, ResurrectionCompleted::class, 1);
    Http::assertNothingSent();
})->with(['ipv4' => [[4]], 'ipv6' => [[6]], 'dualstack' => [[4, 6]]]);

it('agrupa versoes do mesmo cliente com SQL estrito e preserva suas contagens', function (): void {
    expect(DB::selectOne('SELECT @@sql_mode AS mode')->mode)->toContain('ONLY_FULL_GROUP_BY');
    consumerPeer(12001, 'A', [4, 6]);
    consumerPeer(12002, 'B', [4, 6], true, 12002);
    DB::table('peers')->where('user_id', 12002)->update(['agent' => 'consumer-test/2.0']);
    $group = app(StatsController::class)->clients()->getData()['clients']['consumer-test'];
    expect((int) $group['peer_count'])->toBe(2)->and((int) $group['user_count'])->toBe(2)
        ->and((int) $group['torrent_count'])->toBe(2)->and((int) $group['single_seed_count'])->toBe(2)
        ->and((int) $group['clients']['consumer-test/1.0']['single_seed_count'])->toBe(1)
        ->and((int) $group['clients']['consumer-test/2.0']['single_seed_count'])->toBe(1);
});

it('reembolsa o historico sem multiplicar familias e sem reaplicar desconto', function (int $torrents, array $families): void {
    $fullRefundSeedtime = 12 * 30 * 24 * 60 * 60 + 3600;

    foreach (\array_slice([12001, 12002], 0, $torrents) as $torrent) {
        consumerPeer($torrent, 'A', $families);
        consumerPeer($torrent, 'B', $families);
        consumerHistory($torrent, $fullRefundSeedtime);
    }
    $expected = 10000 - $torrents * 1000;
    expect(DB::table('history')->join('users', 'users.id', '=', 'history.user_id')
        ->join('groups', 'groups.id', '=', 'users.group_id')->count())->toBe($torrents);
    expect(app(Kernel::class)->call('auto:refund_download'))->toBe(0);
    $actual = (int) $this->user->fresh()->downloaded;
    $refunded = (int) DB::table('history')->sum('refunded_download');
    fwrite(STDOUT, "\nrefund ".json_encode(['torrents' => $torrents, 'families' => $families,
        'expected_downloaded'                          => $expected, 'actual_downloaded' => $actual, 'history_refunded' => $refunded])."\n");
    expect($actual)->toBe($expected)->and($refunded)->toBe($torrents * 1000);
    expect(app(Kernel::class)->call('auto:refund_download'))->toBe(0);
    expect((int) $this->user->fresh()->downloaded)->toBe($expected);
})->with(['um torrent' => 1, 'dois torrents' => 2])->with(['ipv4' => [[4]], 'ipv6' => [[6]], 'dualstack' => [[4, 6]]]);
