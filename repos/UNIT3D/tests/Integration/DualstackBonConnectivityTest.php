<?php

declare(strict_types=1);

use App\Http\Livewire\UserEarnings;
use App\Models\User;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Illuminate\View\Component;
use Livewire\Livewire;

beforeAll(function (): void {
    Component::flushCache();
    Component::forgetFactory();
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

afterAll(function (): void {
    Component::flushCache();
    Component::forgetFactory();
});

beforeEach(function (): void {
    if (getenv('DUALSTACK_BON_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL real e banco isolado unit3d_dualstack_journal_test.');
    }
    expect(DB::getDriverName())->toBe('mysql')
        ->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    DB::beginTransaction();
    Carbon::setTestNow('2026-10-08 12:00:00');
    config(['dualstack.enabled' => true, 'dualstack.endpoint_ttl' => 7200, 'cache.default' => 'array', 'scout.driver' => 'null']);
    cache()->flush();
    DB::table('peers')->delete();
    DB::table('history')->delete();
    DB::table('bon_earnings')->delete();
    DB::table('users')->where('id', 12001)->update(['deleted_at' => null, 'tracker_removal_state' => 0]);
    $this->user = User::findOrFail(12001);
    auth()->setUser($this->user);
    DB::table('history')->insert([
        'user_id'         => 12001, 'torrent_id' => 12001, 'agent' => 'bon-test',
        'client_uploaded' => 1000, 'client_downloaded' => 0, 'active' => true,
        'seeder'          => true, 'immune' => false, 'seedtime' => 3600,
        'created_at'      => now()->subHour(), 'updated_at' => now(),
    ]);
    $this->rule = bonConnectivityRule();
});

afterEach(function (): void {
    DB::disableQueryLog();
    Carbon::setTestNow();

    if (getenv('DUALSTACK_BON_TESTS') === '1' && DB::transactionLevel() > 0) {
        DB::rollBack();
    }
});

function bonConnectivityRule(string $variable = '1', string $operation = 'append', int $multiplier = 10, ?int $condition = 1, int $position = 1): int
{
    $id = DB::table('bon_earnings')->insertGetId([
        'position'  => $position, 'variable' => $variable, 'multiplier' => $multiplier,
        'operation' => $operation, 'name' => 'BON vigente', 'description' => 'Fixture isolada',
    ]);

    if ($condition !== null) {
        DB::table('bon_earning_conditions')->insert([
            'bon_earning_id' => $id, 'operand1' => 'connectable', 'operator' => '=', 'operand2' => $condition,
        ]);
    }

    return $id;
}

/** Endpoints: [familia, conectividade, idade em segundos]. */
function bonConnectivityPeer(array $endpoints, string $letter = 'B', array $overrides = []): void
{
    $peer = array_replace([
        'user_id'    => 12001, 'torrent_id' => 12001, 'peer_id' => str_repeat($letter, 20),
        'ip'         => inet_pton('192.0.2.30'), 'port' => 6881, 'agent' => 'bon-test',
        'uploaded'   => 1000, 'downloaded' => 0, 'left' => 0, 'seeder' => true,
        'active'     => true, 'visible' => true, 'connectable' => true,
        'created_at' => now()->subHour(), 'updated_at' => now(),
    ], $overrides);
    DB::table('peers')->insert($peer);

    foreach ($endpoints as [$family, $connectable, $age]) {
        DB::table('peer_ips')->insert([
            'user_id'           => $peer['user_id'], 'torrent_id' => $peer['torrent_id'], 'peer_id' => $peer['peer_id'],
            'family'            => $family, 'ip' => inet_pton($family === 4 ? '192.0.2.30' : '2001:db8::30'),
            'port'              => 6881, 'connectable' => $connectable, 'revision' => 1,
            'last_announced_at' => now()->subSeconds($age), 'created_at' => now(), 'updated_at' => now(),
        ]);
    }
}

function bonConnectivityAssert(User $user, float $earnings, int $connectable, array $ruleCounts): void
{
    $before = (float) $user->fresh()->seedbonus;
    expect(app(Kernel::class)->call('auto:bon_allocation'))->toBe(0);
    expect((float) $user->fresh()->seedbonus - $before)->toBe($earnings);
    $component = new UserEarnings();
    $component->user = $user;
    $data = $component->render()->getData();
    expect((float) $data['total'])->toBe($earnings)
        ->and($data['torrents']->total())->toBe(1)
        ->and((float) $data['torrents']->first()->hourly_earnings)->toBe($earnings)
        ->and((int) $data['torrents']->first()->connectable)->toBe($connectable);

    foreach ($ruleCounts as $id => $count) {
        expect((int) $data['bonEarnings']->firstWhere('id', $id)->torrents_count)->toBe($count);
    }
    expect((int) DB::table('history')->where('user_id', 12001)->where('torrent_id', 12001)->value('seedtime'))->toBe(3600);
}

it('usa somente checagens positivas de endpoints vigentes no credito e na tela', function (array $endpoints, int $expected, bool $external): void {
    config(['announce.external_tracker.is_enabled' => $external]);
    bonConnectivityPeer($endpoints);
    bonConnectivityAssert($this->user, $expected * 10.0, $expected, [$this->rule => $expected]);
})->with([
    'ipv4 expirado e ipv6 desconhecido' => [[[4, true, 7201], [6, null, 0]], 0],
    'ipv6 expirado e ipv4 desconhecido' => [[[4, null, 0], [6, true, 7201]], 0],
    'ipv6 positivo preservado'          => [[[4, false, 0], [6, true, 0]], 1],
    'ipv4 positivo preservado'          => [[[4, true, 0], [6, false, 0]], 1],
    'dois positivos nao duplicam'       => [[[4, true, 0], [6, true, 0]], 1],
    'limite exato expira'               => [[[4, true, 7200], [6, null, 0]], 0],
    'um segundo antes do limite'        => [[[4, true, 7199], [6, null, 0]], 1],
    'desconhecido nao comprova'         => [[[4, null, 0], [6, null, 0]], 0],
    'negativos nao comprovam'           => [[[4, false, 0], [6, false, 0]], 0],
    'sem endpoints nao comprova'        => [[], 0],
])->with(['standalone' => false, 'externo' => true]);

it('respeita ttl configurado e ignora a projecao legada desatualizada', function (): void {
    config(['dualstack.endpoint_ttl' => 300]);
    bonConnectivityPeer([[6, true, 299]], overrides: ['connectable' => false]);
    bonConnectivityAssert($this->user, 10.0, 1, [$this->rule => 1]);
    DB::table('peer_ips')->update(['last_announced_at' => now()->subSeconds(300)]);
    bonConnectivityAssert($this->user, 0.0, 0, [$this->rule => 0]);
});

it('nao usa conectividade de outra identidade ou peer inelegivel', function (array $overrides): void {
    bonConnectivityPeer([[4, true, 7201], [6, null, 0]]);
    bonConnectivityPeer([[4, true, 0], [6, true, 0]], overrides: $overrides);
    bonConnectivityAssert($this->user, 0.0, 0, [$this->rule => 0]);
})->with([
    'outro usuario com mesmo peer id' => [['user_id' => 12002]],
    'outro torrent com mesmo peer id' => [['torrent_id' => 12002]],
    'outro peer inativo'              => [['peer_id' => str_repeat('I', 20), 'active' => false]],
    'outro peer leecher'              => [['peer_id' => str_repeat('L', 20), 'seeder' => false, 'left' => 100]],
]);

it('agrega conectividade por usuario torrent tambem na contagem das regras', function (): void {
    bonConnectivityPeer([[4, null, 0]]);
    bonConnectivityPeer([[4, true, 0], [6, true, 0]], 'C');
    $negative = bonConnectivityRule(condition: 0, position: 2);
    bonConnectivityAssert($this->user, 10.0, 1, [$this->rule => 1, $negative => 0]);
    DB::table('peer_ips')->update(['connectable' => null]);
    bonConnectivityAssert($this->user, 10.0, 0, [$this->rule => 0, $negative => 1]);
});

it('preserva variavel conectividade e operacoes de acrescimo e multiplicacao', function (): void {
    DB::table('bon_earnings')->delete();
    $append = bonConnectivityRule(variable: 'connectable', condition: null);
    $multiply = bonConnectivityRule(operation: 'multiply', multiplier: 2, position: 2);
    bonConnectivityPeer([[4, true, 0], [6, true, 0]]);
    bonConnectivityPeer([[6, true, 0]], 'C');
    bonConnectivityAssert($this->user, 20.0, 1, [$append => 1, $multiply => 1]);
    DB::table('peer_ips')->update(['last_announced_at' => now()->subSeconds(7200)]);
    bonConnectivityAssert($this->user, 0.0, 0, [$append => 1, $multiply => 0]);
});

it('preserva modo legado sem ler peer_ips quando dualstack esta desativado', function (): void {
    config(['dualstack.enabled' => false]);
    bonConnectivityPeer([]);
    DB::enableQueryLog();
    DB::flushQueryLog();
    bonConnectivityAssert($this->user, 10.0, 1, [$this->rule => 1]);
    expect(collect(DB::getQueryLog())->contains(fn ($query) => str_contains($query['query'], 'peer_ips')))->toBeFalse();
});

it('renderiza e atualiza a tela real com consultas constantes para um ou cinquenta peers', function (): void {
    bonConnectivityPeer([[4, true, 7201], [6, null, 0]]);
    $counts = [];

    foreach ([1, 50] as $amount) {
        if ($amount === 50) {
            foreach (range(1, 49) as $number) {
                bonConnectivityPeer([[4, true, 7201], [6, null, 0]], overrides: ['peer_id' => str_pad((string) $number, 20, '0', STR_PAD_LEFT)]);
            }
        }
        cache()->flush();
        DB::enableQueryLog();
        DB::flushQueryLog();
        $screen = Livewire::actingAs($this->user)->test(UserEarnings::class, ['userId' => 12001]);
        $screen->assertSuccessful()->assertSee('BON vigente')
            ->assertViewHas('total', fn ($total) => (float) $total === 0.0)
            ->assertViewHas('torrents', fn ($torrents) => $torrents->total() === 1)
            ->assertViewHas('bonEarnings', fn ($rules) => (int) $rules->first()->torrents_count === 0);
        $counts[] = \count(DB::getQueryLog());
        DB::disableQueryLog();
        $screen->set('showMorePrecision', true)->assertSuccessful()
            ->assertViewHas('total', fn ($total) => (float) $total === 0.0);
    }
    expect($counts[1])->toBe($counts[0])->and($counts[0])->toBeLessThanOrEqual(15);
});
