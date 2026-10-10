<?php

declare(strict_types=1);

use App\Models\ChatStatus;
use App\Models\Torrent;
use App\Models\User;
use App\Services\Dualstack\EndpointAddress;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\QueryException;
use Illuminate\Support\Facades\DB;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

beforeEach(function (): void {
    if (getenv('DUALSTACK_MYSQL_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL real com migracao aplicada e DUALSTACK_MYSQL_TESTS=1.');
    }
    expect(DB::connection()->getDriverName())->toBe('mysql');
    config(['dualstack.enabled' => false, 'dualstack.allow_private_addresses' => true]);
    DB::beginTransaction();
    $this->identity = Model::withoutEvents(function (): array {
        $chatStatus = ChatStatus::query()->firstOrCreate(
            ['color' => 'dualstack-schema'],
            ['name' => 'Dualstack schema', 'icon' => 'fas fa-circle'],
        );
        $user = User::factory()->create(['can_download' => true, 'chat_status_id' => $chatStatus->id]);
        $torrent = Torrent::factory()->create(['user_id' => $user->id, 'seeders' => 1, 'leechers' => 0]);

        return ['user_id' => $user->id, 'torrent_id' => $torrent->id, 'peer_id' => str_repeat('A', 20)];
    });
    DB::table('peers')->insert($this->identity + [
        'ip'       => inet_pton('192.0.2.1'), 'port' => 6881, 'agent' => 'schema-test',
        'uploaded' => 1000, 'downloaded' => 0, 'left' => 0, 'seeder' => 1,
        'active'   => 1, 'visible' => 1, 'created_at' => now(), 'updated_at' => now(),
    ]);
    $this->endpoint = $this->identity + [
        'family'            => 4, 'ip' => inet_pton('192.0.2.1'), 'port' => 6881,
        'last_announced_at' => now(), 'revision' => 1,
    ];
});

afterEach(function (): void {
    if (getenv('DUALSTACK_MYSQL_TESTS') === '1') {
        DB::rollBack();
    }
});

it('impoe um endpoint por familia e permite ambos sem duplicar o peer', function (): void {
    DB::table('peer_ips')->insert($this->endpoint);
    DB::table('peer_ips')->insert(array_replace($this->endpoint, ['family' => 6, 'ip' => inet_pton('2001:db8::1')]));
    expect(DB::table('peer_ips')->where($this->identity)->count())->toBe(2)
        ->and(DB::table('peers')->where($this->identity)->count())->toBe(1);
    expect(fn () => DB::table('peer_ips')->insert(array_replace($this->endpoint, ['ip' => inet_pton('192.0.2.2')])))->toThrow(QueryException::class);
});

it('rejeita familia e comprimento inconsistentes no MySQL', function (int $family, string $ip): void {
    expect(fn () => DB::table('peer_ips')->insert(array_replace($this->endpoint, ['family' => $family, 'ip' => inet_pton($ip)])))->toThrow(QueryException::class);
})->with([[5, '192.0.2.1'], [6, '192.0.2.1'], [4, '2001:db8::1']]);

it('impoe FK composta e remove endpoints em cascata', function (): void {
    DB::table('peer_ips')->insert($this->endpoint);
    expect(fn () => DB::table('peer_ips')->insert(array_replace($this->endpoint, ['peer_id' => str_repeat('B', 20)])))->toThrow(QueryException::class);
    DB::table('peers')->where($this->identity)->delete();
    expect(DB::table('peer_ips')->where($this->identity)->count())->toBe(0);
});

it('retoma backfill sem duplicar ou sobrescrever endpoints nem totais legados', function (): void {
    $kernel = app(Kernel::class);
    expect($kernel->call('dualstack:backfill', ['--offline' => true, '--batch' => 1]))->toBe(0);
    DB::table('peer_ips')->where($this->identity)->update(['ip' => inet_pton('192.0.2.99'), 'revision' => 2]);
    expect($kernel->call('dualstack:backfill', ['--offline' => true, '--batch' => 2]))->toBe(0);
    $endpoints = DB::table('peer_ips')->where($this->identity)->get();
    expect($endpoints)->toHaveCount(1)
        ->and($endpoints[0]->ip)->toBe(inet_pton('192.0.2.99'))
        ->and((int) $endpoints[0]->revision)->toBe(2);
    $torrent = DB::table('torrents')->find($this->identity['torrent_id']);
    expect((int) $torrent->seeders)->toBe(1)->and((int) $torrent->seeders_ipv4)->toBe(1)->and((int) $torrent->seeders_ipv6)->toBe(0);
});

it('normaliza IPv4 mapeado e limita enderecos de laboratorio por configuracao', function (): void {
    $ip = EndpointAddress::observed('::ffff:172.29.92.30', true);
    expect($ip->family)->toBe(4)->and(\strlen($ip->binary))->toBe(4)->and($ip->text())->toBe('172.29.92.30');
    expect(fn () => EndpointAddress::observed('fd42:756e:6974:92::30'))->toThrow(InvalidArgumentException::class);

    foreach (['0.0.0.0', '224.0.0.1', '169.254.1.1', '::', '::1', 'ff02::1', 'fe80::1', 'invalid'] as $invalid) {
        expect(fn () => EndpointAddress::observed($invalid, true))->toThrow(InvalidArgumentException::class);
    }
});

it('preserva auto como escolha separada da resolucao', function (): void {
    $id = $this->identity['user_id'];
    DB::table('users')->where('id', $id)->update(['peer_count_mode' => 'auto', 'peer_count_auto_mode' => 'ipv6']);
    $user = DB::table('users')->find($id);
    expect($user->peer_count_mode)->toBe('auto')->and($user->peer_count_auto_mode)->toBe('ipv6');
});
