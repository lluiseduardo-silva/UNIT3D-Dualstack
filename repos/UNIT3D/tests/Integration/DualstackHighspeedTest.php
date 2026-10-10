<?php

declare(strict_types=1);

use App\Models\Seedbox;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

beforeEach(function (): void {
    if (getenv('DUALSTACK_HIGHSPEED_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL real e banco isolado unit3d_dualstack_journal_test.');
    }
    expect(DB::getDriverName())->toBe('mysql')->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    DB::beginTransaction();
    Carbon::setTestNow('2026-10-08 12:00:00');
    config(['dualstack.enabled' => true, 'dualstack.endpoint_ttl' => 7200]);
    DB::table('peers')->delete();
    DB::table('seedboxes')->delete();
    DB::table('torrents')->update(['highspeed' => true]);
});

afterEach(function (): void {
    DB::disableQueryLog();
    Carbon::setTestNow();

    if (getenv('DUALSTACK_HIGHSPEED_TESTS') === '1' && DB::transactionLevel() > 0) {
        DB::rollBack();
    }
});

function highspeedSeedbox(string $ip): void
{
    Seedbox::withoutEvents(fn () => Seedbox::create(['user_id' => 12001, 'name' => 'Fixture isolada', 'ip' => $ip]));
}

function highspeedPeer(array $overrides = [], int $ipv6Age = 0): void
{
    $peer = array_replace([
        'user_id'    => 12001, 'torrent_id' => 12001, 'peer_id' => str_repeat('S', 20),
        'ip'         => inet_pton('192.0.2.199'), 'port' => 6999, 'agent' => 'highspeed-test',
        'uploaded'   => 1000, 'downloaded' => 0, 'left' => 0, 'seeder' => true,
        'active'     => true, 'visible' => true, 'connectable' => false,
        'created_at' => now()->subHour(), 'updated_at' => now(),
    ], $overrides);
    DB::table('peers')->insert($peer);

    foreach ([4 => '192.0.2.30', 6 => '2001:db8::30'] as $family => $ip) {
        DB::table('peer_ips')->insert(array_intersect_key($peer, array_flip(['user_id', 'torrent_id', 'peer_id'])) + [
            'family'     => $family, 'ip' => inet_pton($ip), 'port' => 6881, 'connectable' => null,
            'revision'   => 1, 'last_announced_at' => now()->subSeconds($family === 6 ? $ipv6Age : 0),
            'created_at' => now(), 'updated_at' => now(),
        ]);
    }
}

it('identifica seedbox em qualquer familia vigente sem depender da projecao', function (string $ip, int $age, bool $expected, bool $external): void {
    config(['announce.external_tracker.is_enabled' => $external]);
    highspeedSeedbox($ip);
    highspeedPeer(ipv6Age: $age);
    $before = DB::table('torrents')->find(12001);
    expect(app(Kernel::class)->call('auto:highspeed_tag'))->toBe(0);
    $after = DB::table('torrents')->find(12001);
    expect((bool) $after->highspeed)->toBe($expected)
        ->and($after->updated_at)->toBe($before->updated_at)
        ->and($after->seeders)->toBe($before->seeders)
        ->and(DB::table('peer_ips')->count())->toBe(2)
        ->and((bool) DB::table('torrents')->where('id', 12002)->value('highspeed'))->toBeFalse();
})->with([
    'ipv4 vigente'         => ['192.0.2.30', 0, true],
    'ipv6 vigente'         => ['2001:db8::30', 0, true],
    'ipv6 antes do limite' => ['2001:db8::30', 7199, true],
    'ipv6 no limite'       => ['2001:db8::30', 7200, false],
    'ipv6 expirado'        => ['2001:db8::30', 7201, false],
    'projecao obsoleta'    => ['192.0.2.199', 0, false],
    'cadastro invalido'    => ['not-an-ip', 0, false],
])->with(['standalone' => false, 'externo' => true]);

it('nao usa endpoints de outra identidade ou seeder inelegivel', function (array $overrides): void {
    highspeedSeedbox('2001:db8::30');
    highspeedPeer();
    DB::table('peer_ips')->delete();
    highspeedPeer($overrides);
    expect(app(Kernel::class)->call('auto:highspeed_tag'))->toBe(0);
    expect((bool) DB::table('torrents')->where('id', 12001)->value('highspeed'))->toBeFalse();
})->with([
    'outro torrent'         => [['torrent_id' => 12002]],
    'outro usuario inativo' => [['user_id' => 12002, 'active' => false]],
    'outro peer leecher'    => [['peer_id' => str_repeat('L', 20), 'seeder' => false, 'left' => 100]],
]);

it('preserva modo legado e nao exige schema expandido', function (): void {
    config(['dualstack.enabled' => false]);
    highspeedSeedbox('192.0.2.199');
    highspeedPeer();
    DB::table('peer_ips')->delete();
    DB::enableQueryLog();
    DB::flushQueryLog();
    expect(app(Kernel::class)->call('auto:highspeed_tag'))->toBe(0);
    expect((bool) DB::table('torrents')->where('id', 12001)->value('highspeed'))->toBeTrue();
    expect(collect(DB::getQueryLog())->contains(fn ($query) => str_contains($query['query'], 'peer_ips')))->toBeFalse();
});

it('remove marca sem seedboxes e respeita ttl configurado', function (): void {
    highspeedPeer(ipv6Age: 300);
    expect(app(Kernel::class)->call('auto:highspeed_tag'))->toBe(0);
    expect(DB::table('torrents')->where('highspeed', true)->count())->toBe(0);
    highspeedSeedbox('2001:db8::30');
    config(['dualstack.endpoint_ttl' => 300]);
    app(Kernel::class)->call('auto:highspeed_tag');
    expect((bool) DB::table('torrents')->where('id', 12001)->value('highspeed'))->toBeFalse();
});

it('processa fronteira de lotes preservando exclusao logica e status', function (): void {
    expect(DB::table('torrents')->whereBetween('id', [20001, 20501])->exists())->toBeFalse();
    $template = (array) DB::table('torrents')->find(12001);

    foreach (range(20001, 20501) as $id) {
        DB::table('torrents')->insert(array_replace($template, ['id' => $id, 'info_hash' => sha1('highspeed-'.$id, true), 'highspeed' => true]));
    }
    highspeedSeedbox('2001:db8::30');

    foreach ([20001, 20500, 20501] as $id) {
        highspeedPeer(['torrent_id' => $id]);
    }
    DB::table('torrents')->where('id', 20500)->update(['status' => 0]);
    DB::table('torrents')->where('id', 20002)->update(['deleted_at' => now()]);
    DB::enableQueryLog();
    DB::flushQueryLog();
    expect(app(Kernel::class)->call('auto:highspeed_tag'))->toBe(0);
    $writes = collect(DB::getQueryLog())->filter(fn ($query) => str_starts_with(strtoupper($query['query']), 'UPDATE'));
    expect($writes)->toHaveCount(2);

    foreach ($writes as $write) {
        expect(strtolower($write['query']))->not->toContain('join')->not->toContain('peers');
    }
    expect(DB::table('torrents')->whereBetween('id', [20001, 20501])->where('highspeed', true)->orderBy('id')->pluck('id')->all())
        ->toBe([20001, 20002, 20500, 20501]);
});
