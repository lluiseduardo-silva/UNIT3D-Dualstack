<?php

declare(strict_types=1);

use App\Services\Dualstack\Counter;
use App\Services\Unit3dAnnounce;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Http\Client\Factory;
use Illuminate\Support\Facades\Http;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

beforeEach(function (): void {
    Http::swap(new Factory());
    Http::preventStrayRequests();
    config(['announce.external_tracker' => ['is_enabled' => true, 'host' => 'dualstack.test', 'port' => 80, 'unix_socket' => null, 'key' => str_repeat('a', 32)]]);
});

function administrativeTorrent(): array
{
    return [
        'id'              => 12001, 'status' => 'Approved', 'is_deleted' => false,
        'capabilities'    => ['dualstack' => true, 'peer_schema' => 1, 'peer_count' => 'unique', 'max_endpoints' => 2],
        'seeders'         => 1, 'leechers' => 0, 'seeders_ipv4' => 1, 'seeders_ipv6' => 1, 'leechers_ipv4' => 0, 'leechers_ipv6' => 0,
        'times_completed' => 1, 'download_factor' => 100, 'upload_factor' => 100,
        'peers'           => ['12001-'.bin2hex('-DS9200-000000000001') => [
            'is_seeder'  => true, 'is_active' => true, 'is_visible' => true, 'connectable' => true,
            'uploaded'   => Counter::MAX, 'downloaded' => '100', 'left' => '0',
            'updated_at' => 1700000000, 'created_at' => 1700000000, 'state_version' => 4, 'session_generation' => 1,
            // A projecao propositalmente ausente nao impede o leitor schema 1.
            'endpoints' => [
                ['family'               => 4, 'ip_address' => '192.0.2.30', 'port' => 6881, 'connectable' => true,
                    'last_announced_at' => 1700000000, 'connectivity_checked_at' => 1700000000, 'revision' => 1],
                ['family'               => 6, 'ip_address' => '2001:db8::30', 'port' => 6882, 'connectable' => null,
                    'last_announced_at' => 1700000000, 'connectivity_checked_at' => null, 'revision' => 1],
            ],
        ]],
    ];
}

it('le um peer com dois endpoints e preserva uint64 sem projecao legada', function (): void {
    Http::fake(['*' => Http::response(administrativeTorrent())]);
    $torrent = Unit3dAnnounce::getTorrent(12001);
    $peer = array_values($torrent['peers'])[0];
    expect($torrent['seeders'])->toBe(1)->and($torrent['capabilities']['dualstack'])->toBeTrue()
        ->and($torrent['peers'])->toHaveCount(1)->and($peer['endpoints'])->toHaveCount(2)
        ->and($peer['uploaded'])->toBe(Counter::MAX)->and($peer['user_id'])->toBe(12001)
        ->and($peer['peer_id'])->toBe('-DS9200-000000000001');
});

it('recusa contratos novos invalidos', function (string $case): void {
    $torrent = administrativeTorrent();
    $peer = &$torrent['peers'][array_key_first($torrent['peers'])];

    switch ($case) {
        case 'familia repetida': $peer['endpoints'][1] = $peer['endpoints'][0];

            break;
        case 'ip nao corresponde': $peer['endpoints'][1]['ip_address'] = '192.0.2.99';

            break;
        case 'terceiro endpoint': $peer['endpoints'][] = $peer['endpoints'][0];

            break;
        case 'contador arredondado': $peer['uploaded'] = (float) Counter::MAX;

            break;
        case 'overflow': $peer['uploaded'] = '18446744073709551616';

            break;
        case 'schema desconhecido': $torrent['capabilities']['peer_schema'] = 2;

            break;
        case 'total duplicado': $torrent['seeders'] = 3;

            break;
        case 'ativo sem endpoint': $peer['endpoints'] = [];

            break;
    }
    Http::fake(['*' => Http::response($torrent)]);
    expect(Unit3dAnnounce::getTorrent(12001))->toBe([]);
})->with(['familia repetida', 'ip nao corresponde', 'terceiro endpoint', 'contador arredondado', 'overflow', 'schema desconhecido', 'total duplicado', 'ativo sem endpoint']);

it('aceita tracker legado sem apresenta-lo como dualstack', function (): void {
    $torrent = administrativeTorrent();
    unset($torrent['capabilities']);
    $peer = &$torrent['peers'][array_key_first($torrent['peers'])];
    unset($peer['endpoints']);
    $peer['uploaded'] = 1000;
    $peer['downloaded'] = 100;
    $peer['ip_address'] = '192.0.2.30';
    $peer['port'] = 6881;
    Http::fake(['*' => Http::response($torrent)]);
    expect(Unit3dAnnounce::getTorrent(12001)['capabilities']['dualstack'])->toBeFalse();
});

it('funciona sem backend externo configurado e sem fazer requests', function (): void {
    config(['announce.external_tracker.is_enabled' => false]);
    expect(Unit3dAnnounce::getCapabilities())->toBeTrue()->and(Unit3dAnnounce::getTorrent(12001))->toBeTrue();
    Http::assertNothingSent();
});

it('reconhece capacidade explicita e endpoint ausente de backend antigo', function (): void {
    Http::fake(['*' => Http::response(administrativeTorrent()['capabilities'])]);
    expect(Unit3dAnnounce::getCapabilities()['peer_schema'])->toBe(1);
    Http::swap(new Factory());
    Http::fake(['*' => Http::response('', 404)]);
    expect(Unit3dAnnounce::getCapabilities())->toBeFalse();
});

it('renderiza endpoints apenas quando a permissao de ip permite', function (): void {
    $peer = array_values(administrativeTorrent()['peers'])[0];
    $view = 'torrent.partials.external-peer-endpoints';
    $hidden = view($view, ['peer' => $peer, 'dualstack' => true, 'canView' => false])->render();
    expect($hidden)->not->toContain('192.0.2.30', '2001:db8::30', '6881', '6882');
    $visible = view($view, ['peer' => $peer, 'dualstack' => true, 'canView' => true])->render();
    expect($visible)->toContain('IPv4: 192.0.2.30', 'IPv6: 2001:db8::30', 'IPv4: 6881', 'IPv6: 6882')
        ->and(substr_count($visible, '<td>'))->toBe(2);
});
