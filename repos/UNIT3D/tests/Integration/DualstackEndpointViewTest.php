<?php

declare(strict_types=1);

use App\Http\Controllers\TorrentPeerController;
use App\Http\Livewire\UserActive;
use App\Models\Peer;
use App\Models\User;
use App\Services\Dualstack\EndpointView;
use App\Services\Dualstack\ProfileClients;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\Blade;
use Illuminate\Support\Facades\DB;

beforeAll(function (): void {
    Illuminate\View\Component::flushCache();
    Illuminate\View\Component::forgetFactory();
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

afterAll(function (): void {
    // As suites vizinhas recriam a aplicacao; nao conservar views inline entre elas.
    Illuminate\View\Component::flushCache();
    Illuminate\View\Component::forgetFactory();
});

beforeEach(function (): void {
    if (getenv('DUALSTACK_VIEW_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL real e banco isolado.');
    }
    expect(DB::getDriverName())->toBe('mysql')->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    DB::beginTransaction();
    Carbon::setTestNow('2026-10-08 12:00:00');
    config(['dualstack.enabled' => true, 'dualstack.endpoint_ttl' => 7200, 'cache.default' => 'array', 'scout.driver' => 'null', 'announce.connectable_check' => true]);
    cache()->flush();
    DB::table('peers')->delete();
    $this->viewer = User::findOrFail(12001);
    $this->viewer->load('group');
    auth()->setUser($this->viewer);
    $this->request = Request::create('/torrents/12001/peers');
    $this->request->setUserResolver(fn () => $this->viewer);
});

afterEach(function (): void {
    DB::disableQueryLog();
    Carbon::setTestNow();

    if (getenv('DUALSTACK_VIEW_TESTS') === '1' && DB::transactionLevel() > 0) {
        DB::rollBack();
    }
});

function endpointViewPeer(int $number, int $user = 12001, int $torrent = 12001): void
{
    $identity = ['user_id' => $user, 'torrent_id' => $torrent, 'peer_id' => str_pad((string) $number, 20, 'V', STR_PAD_LEFT)];
    DB::table('peers')->insert($identity + ['ip' => inet_pton('192.0.2.199'), 'port' => 6999,
        'agent'                                  => 'endpoint-view-fixture', 'uploaded' => 1000, 'downloaded' => 100, 'left' => 0,
        'active'                                 => true, 'seeder' => true, 'visible' => true, 'connectable' => true,
        'created_at'                             => now()->subHour(), 'updated_at' => now()]);

    foreach ([4 => '192.0.2.30', 6 => '2001:db8::30'] as $family => $address) {
        DB::table('peer_ips')->insert($identity + ['family' => $family, 'ip' => inet_pton($address),
            'port'                                          => $family === 4 ? 6881 : 6882, 'connectable' => $family === 4 ? true : null,
            'revision'                                      => 1, 'last_announced_at' => now(), 'created_at' => now(), 'updated_at' => now()]);
    }
}

it('carrega pagina de peers com dois endpoints e numero constante de consultas', function (): void {
    foreach ([1, 50] as $size) {
        DB::table('peers')->delete();

        for ($i = 0; $i < $size; $i++) {
            endpointViewPeer($i, $i % 2 === 0 ? 12001 : 12002);
        }
        DB::enableQueryLog();
        DB::flushQueryLog();
        $data = app(TorrentPeerController::class)->index(12001, $this->request)->getData();
        $queries = \count(DB::getQueryLog());
        $page = $data['peers'];
        expect($page->count())->toBe($size)->and($page->total())->toBe($size);

        foreach ($page as $peer) {
            expect($peer->endpoints)->toHaveCount(2)
                ->and($peer->endpoints->pluck('family')->all())->toBe([4,6])
                ->and($peer->endpoints->pluck('port')->all())->toBe([6881,6882])
                ->and($peer->endpoints->pluck('ip_address')->all())->toBe(['192.0.2.30','2001:db8::30']);
            $peer->user->group;
            $peer->user->privacy;
        }
        expect(\count(DB::getQueryLog()))->toBe($queries)->and($queries)->toBe(7);
        expect($page->first()->toJson())->not->toContain('VVVV');
        DB::disableQueryLog();
    }
});

it('pagina cinquenta peers logicos sem multiplicar endpoints ou carregar o swarm inteiro', function (): void {
    for ($i = 0; $i < 53; $i++) {
        endpointViewPeer($i);
    }
    $page = app(TorrentPeerController::class)->index(12001, $this->request)->getData()['peers'];
    expect($page->total())->toBe(53)->and($page->count())->toBe(50)
        ->and($page->getCollection()->sum(fn ($p) => $p->endpoints->count()))->toBe(100);
});

it('separa identidades com mesmo peer id em usuarios e torrents diferentes', function (): void {
    endpointViewPeer(1);
    endpointViewPeer(1, 12002);
    endpointViewPeer(1, 12001, 12002);
    DB::table('peer_ips')->where('user_id', 12002)->where('family', 6)->update(['port' => 7001]);
    DB::table('peer_ips')->where('torrent_id', 12002)->where('family', 6)->update(['port' => 7002]);
    $peers = Peer::orderBy('user_id')->orderBy('torrent_id')->get();
    EndpointView::load($peers);
    expect($peers->map(fn ($p) => $p->endpoints->last()->port)->all())->toBe([6882,7002,7001]);
});

it('filtra a familia secundaria e combina ip e porta no mesmo endpoint', function (): void {
    endpointViewPeer(1);
    $component = new UserActive();
    $component->user = $this->viewer;
    $component->ip = '2001:0db8:0000:0000:0000:0000:0000:0030';
    $component->port = '6882';
    DB::enableQueryLog();
    DB::flushQueryLog();
    $page = $component->render()->getData()['actives'];
    expect($page->count())->toBe(1)->and($page->first()->endpoints)->toHaveCount(2)
        ->and(\count(DB::getQueryLog()))->toBe(3);
    $component->port = '6881';
    expect($component->render()->getData()['actives']->total())->toBe(0);
    $component->ip = '192.0.2.199';
    $component->port = '6999';
    expect($component->render()->getData()['actives']->total())->toBe(0);
});

it('exibe estado desconhecido e expirado sem reutilizar conectividade legada', function (): void {
    endpointViewPeer(1);
    DB::table('peer_ips')->where('family', 4)->update(['last_announced_at' => now()->subSeconds(7200)]);
    $peer = Peer::first();
    EndpointView::load(collect([$peer]));
    expect($peer->endpoints->first()->current)->toBeFalse()->and($peer->endpoints->last()->current)->toBeTrue();
    $html = Blade::render('<x-peer.endpoints :peer="$peer" field="connectable" />', ['peer' => $peer]);
    expect($html)->toContain(__('dualstack.endpoint-expired'))->toContain(__('common.unknown'))->not->toContain('192.0.2.30');
    $visible = Blade::render('<x-peer.endpoints :peer="$peer" field="ip" :can-view="true" />', ['peer' => $peer]);
    $hidden = Blade::render('<x-peer.endpoints :peer="$peer" field="ip" :can-view="false" />', ['peer' => $peer]);
    $hiddenPort = Blade::render('<x-peer.endpoints :peer="$peer" field="port" :can-view="false" />', ['peer' => $peer]);
    expect($visible)->toContain('192.0.2.30')->toContain('2001:db8::30');
    expect($hidden)->not->toContain('192.0.2.30')->not->toContain('2001:db8::30');
    expect($hiddenPort)->not->toContain('6881')->not->toContain('6882');
});

it('continua no modo legado sem consultar peer_ips', function (): void {
    endpointViewPeer(1);
    config(['dualstack.enabled' => false]);
    $component = new UserActive();
    $component->user = $this->viewer;
    $component->ip = '192.0.2.199';
    $component->port = '6999';
    DB::enableQueryLog();
    DB::flushQueryLog();
    $page = $component->render()->getData()['actives'];
    expect($page->count())->toBe(1)->and($page->first()->ip)->toBe('192.0.2.199');
    expect(collect(DB::getQueryLog())->contains(fn ($q) => str_contains($q['query'], 'peer_ips')))->toBeFalse();
});

it('preserva permissoes de ip na view real do torrent', function (int $viewerId, bool $moderator, bool $allowed): void {
    endpointViewPeer(1);
    $viewer = User::findOrFail($viewerId);
    $viewer->load('group');
    $viewer->group->is_modo = $moderator;
    auth()->setUser($viewer);
    $request = Request::create('/torrents/12001/peers');
    $request->setUserResolver(fn () => $viewer);
    $data = app(TorrentPeerController::class)->index(12001, $request)->getData();
    // Renderiza o corpo real; o layout global depende de assets e widgets alheios.
    $template = preg_replace('/@extends[^\n]+/', '', file_get_contents(resource_path('views/torrent/peers.blade.php')));
    $html = Blade::render($template."\n@yield('main')", $data);
    expect(str_contains($html, '192.0.2.30'))->toBe($allowed)
        ->and(str_contains($html, '2001:db8::30'))->toBe($allowed);
})->with([[12001,false,true],[12002,false,false],[12002,true,true]]);

it('renderiza a atividade Livewire com ambos endpoints e filtra a segunda familia', function (): void {
    endpointViewPeer(1);
    Livewire\Livewire::actingAs($this->viewer)->test(UserActive::class, ['userId' => 12001])
        ->assertSee('192.0.2.30')->assertSee('2001:db8::30')->assertDontSee('192.0.2.199')
        ->set('ip', '2001:db8::30')->set('port', '6882')->assertSee('2001:db8::30')
        ->set('port', '6881')->assertDontSee('2001:db8::30');
});

it('agrega busca administrativa sem multiplicar trafego ou tamanho por familia', function (string $mode, int $groups): void {
    endpointViewPeer(1);
    endpointViewPeer(1, 12001, 12002);
    endpointViewPeer(2);
    endpointViewPeer(1, 12002);
    $component = new App\Http\Livewire\PeerSearch();
    $component->groupBy = $mode;
    $component->includeSeedsize = true;
    $page = $component->render()->getData()['peers'];
    expect($page->total())->toBe($groups);

    if ($mode === 'none') {
        expect($page->getCollection()->sum('uploaded'))->toBe(4000)
            ->and($page->getCollection()->sum(fn ($p) => $p->endpoints->count()))->toBe(8);
    } else {
        $user = $page->getCollection()->where('user_id', 12001);

        if ($mode === 'user') {
            $row = $user->first();
            expect((int) $row->peer_count)->toBe(3)->and((int) $row->uploaded)->toBe(3000)
                ->and((int) $row->ip)->toBe(2)->and((int) $row->port)->toBe(2);
            $size = (int) DB::table('torrents')->where('id', 12001)->value('size') * 2 + (int) DB::table('torrents')->where('id', 12002)->value('size');
            expect((int) $row->size)->toBe($size);
        } elseif ($mode === 'user_session') {
            expect($user->sum('peer_count'))->toEqual(3)->and($user->sum('uploaded'))->toEqual(3000);

            foreach ($user as $row) {
                expect((int) $row->ip)->toBe(2)->and((int) $row->port)->toBe(2);
            }
        } else {
            foreach ($user as $row) {
                expect((int) $row->peer_count)->toBe(3)->and((int) $row->uploaded)->toBe(3000);
            }
            $component->ip = '2001:db8::30';
            expect($component->render()->getData()['peers']->total())->toBe(2);
        }
    }
})->with([['none',4],['user',2],['user_session',3],['user_ip',4]]);

it('busca endereco secundario e distingue compartilhamento de ip e socket entre usuarios', function (): void {
    endpointViewPeer(1);
    endpointViewPeer(2);
    endpointViewPeer(1, 12002);
    DB::table('peer_ips')->where('user_id', 12002)->where('family', 4)->update(['ip' => inet_pton('192.0.2.31')]);
    DB::table('peer_ips')->where('user_id', 12002)->where('family', 6)->update(['port' => 7000]);
    $component = new App\Http\Livewire\PeerSearch();
    $component->ip = '2001:db8::';
    expect($component->render()->getData()['peers']->total())->toBe(3);
    $component->port = '6881';
    expect($component->render()->getData()['peers']->total())->toBe(0);
    $component->port = '';
    $component->sharedIpsOnly = true;
    expect($component->render()->getData()['peers']->total())->toBe(3);
    $component->sharedSocketsOnly = true;
    expect($component->render()->getData()['peers']->total())->toBe(0);
    $component->ip = '';
    expect($component->render()->getData()['peers']->total())->toBe(0);
});

it('separa desconhecidos e expirados na busca administrativa', function (): void {
    endpointViewPeer(1);
    DB::table('peer_ips')->update(['connectable' => null]);
    $component = new App\Http\Livewire\PeerSearch();
    $component->connectivity = 'unconnectable';
    expect($component->render()->getData()['peers']->total())->toBe(0);
    $component->connectivity = 'unknown';
    expect($component->render()->getData()['peers']->total())->toBe(1);
    $component->groupBy = 'user';
    $row = $component->render()->getData()['peers']->first();
    expect((int) $row->unknown_count)->toBe(1)->and((int) $row->unconnectable_count)->toBe(0);
    DB::table('peer_ips')->update(['connectable' => true,'last_announced_at' => now()->subSeconds(7200)]);
    $component->groupBy = 'none';
    $component->active = 'include';
    expect($component->render()->getData()['peers']->total())->toBe(0);
    $component->active = 'exclude';
    expect($component->render()->getData()['peers']->total())->toBe(1);
});

it('mantem consultas administrativas constantes e renderiza os agrupamentos no Livewire', function (): void {
    foreach ([1,50] as $size) {
        DB::table('peers')->delete();

        for ($i = 0;$i < $size;$i++) {
            endpointViewPeer($i);
        }
        $component = new App\Http\Livewire\PeerSearch();
        $component->perPage = 50;
        DB::enableQueryLog();
        DB::flushQueryLog();
        $page = $component->render()->getData()['peers'];
        expect($page->count())->toBe($size)->and(\count(DB::getQueryLog()))->toBe(6);
        DB::disableQueryLog();
    }
    $this->viewer->group->is_modo = true;
    Livewire\Livewire::actingAs($this->viewer)->test(App\Http\Livewire\PeerSearch::class)
        ->assertSee('192.0.2.30')->assertSee('2001:db8::30')->assertDontSee('192.0.2.199')
        ->set('groupBy', 'user')->assertSee(__('dualstack.peer-group-help'))
        ->set('groupBy', 'user_session')->assertSee(__('dualstack.peer-group-help'))
        ->set('groupBy', 'user_ip')->assertSee('2001:db8::30');
});

it('preserva busca administrativa legada sem ler endpoints', function (): void {
    endpointViewPeer(1);
    config(['dualstack.enabled' => false]);
    $component = new App\Http\Livewire\PeerSearch();
    $component->ip = '192.0.2.199';
    DB::enableQueryLog();
    DB::flushQueryLog();
    $page = $component->render()->getData()['peers'];
    expect($page->total())->toBe(1)->and($page->first()->ip)->toBe('192.0.2.199');
    expect(collect(DB::getQueryLog())->contains(fn ($q) => str_contains($q['query'], 'peer_ips')))->toBeFalse();
});

it('pagina clientes do perfil por peer logico com tres consultas independentes do volume', function (): void {
    $this->viewer->group->is_modo = false;

    foreach ([1, 50] as $size) {
        DB::table('peers')->delete();

        foreach (range(1, $size) as $number) {
            endpointViewPeer($number);
        }
        DB::enableQueryLog();
        DB::flushQueryLog();
        $clients = ProfileClients::get($this->viewer, $this->viewer);
        expect($clients->total())->toBe($size)->and($clients->count())->toBe(min(25, $size));
        $html = view('user.profile.dualstack-clients', ['user' => $this->viewer, 'clients' => $clients])->render();
        expect(\count(DB::getQueryLog()))->toBe(3)
            ->and(substr_count($html, 'endpoint-view-fixture'))->toBe(min(25, $size))
            ->and($clients->getCollection()->sum(fn ($peer) => $peer->endpoints->count()))->toBe(min(50, 2 * $size));
        expect($clients->toJson())->not->toContain('peer_id')->not->toContain('192.0.2.199');
        DB::disableQueryLog();
    }
    Illuminate\Pagination\Paginator::currentPageResolver(fn () => 2);

    try {
        $next = ProfileClients::get($this->viewer, $this->viewer);
        expect($next->count())->toBe(25)->and($next->first()->peer_id)->not->toBe($clients->first()->peer_id);
    } finally {
        Illuminate\Pagination\Paginator::currentPageResolver(fn ($name = 'page') => request()->input($name, 1));
    }
});

it('restringe clientes do perfil e enderecos ao proprietario e moderacao', function (int $viewerId, bool $moderator, bool $allowed): void {
    endpointViewPeer(1);
    $viewer = User::findOrFail($viewerId);
    $viewer->load('group');
    $viewer->group->is_modo = $moderator;
    auth()->setUser($viewer);
    DB::enableQueryLog();
    DB::flushQueryLog();
    $clients = ProfileClients::get($this->viewer, $viewer);

    if (!$allowed) {
        expect($clients)->toHaveCount(0)->and(DB::getQueryLog())->toBe([]);
        // Mesmo dados fornecidos indevidamente nao podem atravessar a view.
        $clients = ProfileClients::get($this->viewer, $this->viewer);
    }
    $html = view('user.profile.dualstack-clients', ['user' => $this->viewer, 'clients' => $clients])->render();
    expect(str_contains($html, '192.0.2.30'))->toBe($allowed)
        ->and(str_contains($html, '2001:db8::30'))->toBe($allowed)
        ->and(str_contains($html, route('staff.peers.index')))->toBe($moderator);
})->with([[12001, false, true], [12002, false, false], [12002, true, true]]);

it('usa endpoints vigentes no perfil sem cache legado e sem cruzar identidades', function (bool $external): void {
    config(['announce.external_tracker.is_enabled' => $external, 'dualstack.endpoint_ttl' => 300]);
    endpointViewPeer(1);
    endpointViewPeer(1, 12002);
    endpointViewPeer(1, 12001, 12002);
    endpointViewPeer(2);
    DB::table('peers')->where('peer_id', str_pad('2', 20, 'V', STR_PAD_LEFT))->update(['active' => false]);
    DB::table('peer_ips')->where('user_id', 12001)->where('torrent_id', 12001)->where('family', 4)
        ->update(['last_announced_at' => now()->subSeconds(300)]);
    DB::table('peer_ips')->where('user_id', 12001)->where('torrent_id', 12002)->update(['last_announced_at' => now()->subSeconds(300)]);
    cache()->put('peers:connectable:192.0.2.199-6999-endpoint-view-fixture', true);
    $clients = ProfileClients::get($this->viewer, $this->viewer);
    expect($clients->total())->toBe(1)->and($clients->first()->torrent_id)->toBe(12001);
    $html = view('user.profile.dualstack-clients', ['user' => $this->viewer, 'clients' => $clients])->render();
    expect($html)->toContain(__('dualstack.endpoint-expired'))->toContain(__('common.unknown'))
        ->not->toContain('192.0.2.199')->not->toContain('6999');
    DB::table('peer_ips')->where('user_id', 12001)->update(['last_announced_at' => now()->subSeconds(300)]);
    expect(ProfileClients::get($this->viewer, $this->viewer)->total())->toBe(0);
})->with(['standalone' => false, 'externo' => true]);

it('preserva agrupamento legado do perfil sem ler endpoints', function (): void {
    config(['dualstack.enabled' => false]);
    endpointViewPeer(1);
    endpointViewPeer(2);
    DB::enableQueryLog();
    DB::flushQueryLog();
    $clients = ProfileClients::get($this->viewer, $this->viewer);
    expect($clients)->toHaveCount(1)->and((int) $clients->first()->num_peers)->toBe(2)
        ->and($clients->first()->ip)->toBe('192.0.2.199');
    expect(collect(DB::getQueryLog())->contains(fn ($q) => str_contains($q['query'], 'peer_ips')))->toBeFalse();
});

it('integra o perfil no controlador sem buscar endpoints para terceiros', function (): void {
    config(['announce.external_tracker.is_enabled' => false]);
    endpointViewPeer(1);
    $controller = app(App\Http\Controllers\User\UserController::class);
    $data = $controller->show($this->request, $this->viewer)->getData();
    expect($data['clients']->total())->toBe(1)->and($data['clients']->first()->endpoints)->toHaveCount(2);
    $other = User::findOrFail(12002);
    $other->load('group');
    $other->group->is_modo = false;
    auth()->setUser($other);
    $this->request->setUserResolver(fn () => $other);
    DB::enableQueryLog();
    DB::flushQueryLog();
    $data = $controller->show($this->request, $this->viewer)->getData();
    expect($data['clients'])->toHaveCount(0);
    expect(collect(DB::getQueryLog())->contains(fn ($q) => str_contains($q['query'], 'peer_ips')))->toBeFalse();
});
