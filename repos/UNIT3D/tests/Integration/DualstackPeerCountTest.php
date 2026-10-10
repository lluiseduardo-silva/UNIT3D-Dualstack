<?php

declare(strict_types=1);

use App\Http\Controllers\User\GeneralSettingController;
use App\Http\Requests\UpdateGeneralSettingRequest;
use App\Http\Resources\TorrentResource;
use App\Models\Torrent;
use App\Models\User;
use App\Services\Dualstack\PeerCountDisplay;
use App\Services\Dualstack\PeerCountPreference;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\Blade;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Validator;
use Symfony\Component\HttpKernel\Exception\HttpException;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

beforeEach(function (): void {
    if (getenv('DUALSTACK_PREFERENCE_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL real e banco isolado unit3d_dualstack_journal_test.');
    }
    expect(DB::getDriverName())->toBe('mysql')
        ->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    DB::beginTransaction();
    Carbon::setTestNow('2026-10-08 12:00:00');
    config(['dualstack.enabled' => true, 'dualstack.endpoint_ttl' => 7200, 'cache.default' => 'array']);
    config(['scout.driver' => 'null', 'torrent.magnet' => false]);
    cache()->flush();
    DB::table('peers')->whereBetween('user_id', [12001, 12006])->delete();
    DB::table('users')->whereBetween('id', [12001, 12006])->update(['peer_count_mode' => 'auto', 'peer_count_auto_mode' => 'ipv6']);
    $this->user = User::findOrFail(12001);
    Auth::guard()->setUser($this->user);
    Auth::guard('api')->setUser($this->user);
});

afterEach(function (): void {
    Mockery::close();
    DB::disableQueryLog();
    Carbon::setTestNow();

    if (getenv('DUALSTACK_PREFERENCE_TESTS') === '1' && DB::transactionLevel() > 0) {
        DB::rollBack();
    }
});

function preferencePeer(int $user, string $letter, bool $seeder, array $families, int $age = 0, bool $active = true): void
{
    $identity = ['user_id' => $user, 'torrent_id' => 12001, 'peer_id' => str_repeat($letter, 20)];
    DB::table('peers')->insert($identity + [
        'ip'         => inet_pton('192.0.2.30'), 'port' => 6881, 'agent' => 'preference-test',
        'uploaded'   => 1000, 'downloaded' => 0, 'left' => $seeder ? 0 : 100,
        'seeder'     => $seeder, 'active' => $active, 'visible' => true,
        'created_at' => now()->subHour(), 'updated_at' => now(),
    ]);

    foreach ($families as $family) {
        DB::table('peer_ips')->insert($identity + [
            'family'            => $family, 'ip' => inet_pton($family === 4 ? '192.0.2.30' : '2001:db8::30'),
            'port'              => 6881, 'connectable' => null, 'revision' => 1,
            'last_announced_at' => now()->subSeconds($age), 'created_at' => now(), 'updated_at' => now(),
        ]);
    }
}

it('resolve auto por seeding depois atividade e nao duplica dualstack', function (bool $external): void {
    config(['announce.external_tracker.is_enabled' => $external]);
    preferencePeer(12001, 'A', true, [4]);
    preferencePeer(12001, 'B', false, [6]); // Seeding tem prioridade.
    preferencePeer(12002, 'A', true, [6]);
    preferencePeer(12002, 'B', false, [4]);
    preferencePeer(12003, 'A', true, [4, 6]);
    preferencePeer(12004, 'A', false, [6]);
    preferencePeer(12005, 'A', false, [4]);
    preferencePeer(12006, 'A', true, [6], 7200); // Limite exato do TTL expirou.
    preferencePeer(12006, 'B', true, [4], 0, false);
    $before = DB::table('users')->whereBetween('id', [12001, 12006])->get(['id', 'uploaded', 'downloaded', 'seedbonus', 'updated_at'])->toJson();
    expect(app(Kernel::class)->call('auto:resolve_peer_count_mode'))->toBe(0);
    $modes = DB::table('users')->whereBetween('id', [12001, 12006])->orderBy('id')->pluck('peer_count_auto_mode')->all();
    expect($modes)->toBe(['ipv4', 'ipv6', 'sum', 'ipv6', 'ipv4', 'sum'])
        ->and(DB::table('users')->whereBetween('id', [12001, 12006])->where('peer_count_mode', 'auto')->count())->toBe(6);
    expect(app(Kernel::class)->call('auto:resolve_peer_count_mode'))->toBe(0);
    expect(DB::table('users')->whereBetween('id', [12001, 12006])->orderBy('id')->pluck('peer_count_auto_mode')->all())->toBe($modes)
        ->and(DB::table('users')->whereBetween('id', [12001, 12006])->get(['id', 'uploaded', 'downloaded', 'seedbonus', 'updated_at'])->toJson())->toBe($before);
})->with([false, true]);

it('considera somente a familia vigente e respeita escolhas manuais', function (): void {
    preferencePeer(12001, 'A', true, [4, 6]);
    DB::table('peer_ips')->where('user_id', 12001)->where('family', 6)->update(['last_announced_at' => now()->subSeconds(7200)]);
    DB::table('users')->where('id', 12002)->update(['peer_count_mode' => 'ipv4', 'peer_count_auto_mode' => 'ipv6']);
    app(PeerCountPreference::class)->resolve([12001, 12002]);
    expect($this->user->fresh()->peer_count_auto_mode)->toBe('ipv4')
        ->and(User::findOrFail(12002)->peer_count_auto_mode)->toBe('ipv6');
    DB::table('peer_ips')->where('user_id', 12001)->delete();
    app(PeerCountPreference::class)->resolve([12001]);
    expect($this->user->fresh()->peer_count_auto_mode)->toBe('sum')->and($this->user->fresh()->peer_count_mode)->toBe('auto');
});

it('atualiza um lote com uma consulta sem N mais um', function (): void {
    foreach (range(12001, 12006) as $id) {
        preferencePeer($id, 'A', true, [4, 6]);
        preferencePeer($id, 'B', false, [4]);
    }
    DB::enableQueryLog();
    DB::flushQueryLog();
    app(PeerCountPreference::class)->resolve(range(12001, 12006));
    expect(DB::getQueryLog())->toHaveCount(1);
});

it('exibe a preferencia do observador sem mudar atributos e uniao', function (string $mode, string $auto, int $seeds, int $leeches): void {
    $torrent = new Torrent(['seeders' => 3, 'leechers' => 5, 'seeders_ipv4' => 2, 'seeders_ipv6' => 2, 'leechers_ipv4' => 3, 'leechers_ipv6' => 4]);
    $this->user->peer_count_mode = $mode;
    $this->user->peer_count_auto_mode = $auto;
    $before = $torrent->getAttributes();
    DB::enableQueryLog();
    DB::flushQueryLog();
    $html = Blade::render('<x-torrent.peer-count :torrent="$torrent" kind="seeders" />|<x-torrent.peer-count :torrent="$torrent" kind="leechers" />', ['torrent' => $torrent]);
    expect($html)->toContain('>'.$seeds.'</span>', '>'.$leeches.'</span>')
        ->and($torrent->getAttributes())->toBe($before)->and(DB::getQueryLog())->toBe([]);
})->with([
    ['sum', 'ipv6', 3, 5], ['ipv4', 'sum', 2, 3], ['ipv6', 'sum', 2, 4],
    ['auto', 'ipv4', 2, 3], ['auto', 'ipv6', 2, 4], ['auto', 'sum', 3, 5],
]);

it('mantem modo legado e nao consulta endpoints quando desativado', function (): void {
    config(['dualstack.enabled' => false]);
    $this->user->peer_count_mode = 'ipv6';
    DB::enableQueryLog();
    DB::flushQueryLog();
    expect(PeerCountDisplay::count((object) ['seeders' => 3], 'seeders', $this->user, 7))->toBe(7);
    expect(app(Kernel::class)->call('auto:resolve_peer_count_mode'))->toBe(0)
        ->and(DB::getQueryLog())->toBe([]);
});

it('valida apenas os quatro modos e nao aceita resolucao enviada pelo cliente', function (): void {
    $rules = (new UpdateGeneralSettingRequest())->rules();

    foreach (['ipv4', 'ipv6', 'sum', 'auto'] as $mode) {
        expect(Validator::make(['peer_count_mode' => $mode], ['peer_count_mode' => $rules['peer_count_mode']])->passes())->toBeTrue();
    }

    foreach (['both', '', 4, ['ipv6']] as $mode) {
        expect(Validator::make(['peer_count_mode' => $mode], ['peer_count_mode' => $rules['peer_count_mode']])->fails())->toBeTrue();
    }
    expect($rules)->not->toHaveKey('peer_count_auto_mode');
});

function preferenceRequest(User $user, ?string $mode): UpdateGeneralSettingRequest
{
    $request = UpdateGeneralSettingRequest::create('/settings', 'PATCH');
    $data = ['torrent_layout' => 0, 'torrent_sort_field' => 'bumped_at', 'locale' => 'en', 'style' => 0];

    foreach ($request->rules() as $key => $rules) {
        if (\in_array('boolean', $rules, true)) {
            $data[$key] = false;
        } elseif (str_ends_with($key, '_position')) {
            $data[$key] = 1;
        }
    }

    if ($mode !== null) {
        $data['peer_count_mode'] = $mode;
    }
    $data['peer_count_auto_mode'] = 'ipv4'; // Nao deve ser confiado.
    $request->replace($data);
    $request->setUserResolver(fn () => $user);
    $validator = Validator::make($data, $request->rules());
    $validator->validate();
    $request->setValidator($validator);

    return $request;
}

it('salva a escolha separada das configuracoes e resolve auto imediatamente', function (): void {
    preferencePeer(12001, 'A', true, [6]);
    app(GeneralSettingController::class)->update(preferenceRequest($this->user, 'auto'), $this->user);
    expect($this->user->fresh()->peer_count_mode)->toBe('auto')
        ->and($this->user->fresh()->peer_count_auto_mode)->toBe('ipv6');
    app(GeneralSettingController::class)->update(preferenceRequest($this->user, 'ipv4'), $this->user);
    app(GeneralSettingController::class)->update(preferenceRequest($this->user, null), $this->user);
    expect($this->user->fresh()->peer_count_mode)->toBe('ipv4');
    expect(view('user.general-setting.peer-count-mode', ['user' => $this->user->fresh()])->render())->toContain('value="ipv4" selected');
});

it('preserva a autorizacao das configuracoes', function (): void {
    expect(fn () => app(GeneralSettingController::class)->update(preferenceRequest(User::findOrFail(12002), 'ipv4'), $this->user))
        ->toThrow(HttpException::class);
    expect($this->user->fresh()->peer_count_mode)->toBe('auto');
});

it('mantem totais da API com campos adicionais independentes da preferencia', function (): void {
    $torrent = Torrent::with(['user', 'category', 'type', 'resolution', 'distributor', 'region', 'files'])->findOrFail(12001);
    $torrent->forceFill(['seeders' => 3, 'leechers' => 5, 'seeders_ipv4' => 2, 'seeders_ipv6' => 2, 'leechers_ipv4' => 3, 'leechers_ipv6' => 4, 'meta' => null]);

    foreach (['ipv4', 'ipv6', 'sum', 'auto'] as $mode) {
        $this->user->peer_count_mode = $mode;
        $attributes = (new TorrentResource($torrent))->resolve(Request::create('/api/torrents/12001'))['attributes'];
        expect($attributes['seeders'])->toBe(3)->and($attributes['leechers'])->toBe(5)
            ->and($attributes['seeders_ipv4'])->toBe(2)->and($attributes['seeders_ipv6'])->toBe(2)
            ->and($attributes['leechers_ipv4'])->toBe(3)->and($attributes['leechers_ipv6'])->toBe(4);
    }
    config(['dualstack.enabled' => false]);
    expect((new TorrentResource($torrent))->resolve(Request::create('/api/torrents/12001'))['attributes'])->not->toHaveKey('seeders_ipv6');
});

it('agenda resolucao diaria em ambos os modos de backend', function (): void {
    $events = app(Illuminate\Console\Scheduling\Schedule::class)->events();
    $matches = array_values(array_filter($events, fn ($event) => str_contains($event->command ?? '', 'auto:resolve_peer_count_mode')));
    expect($matches)->toHaveCount(1)->and($matches[0]->expression)->toBe('0 0 * * *')->and($matches[0]->withoutOverlapping)->toBeTrue();
});

it('publica as familias no caminho da busca mesmo com indice antigo sem campos novos', function (): void {
    DB::table('torrents')->where('id', 12001)->update(['seeders' => 3, 'leechers' => 5, 'seeders_ipv4' => 2, 'seeders_ipv6' => 2, 'leechers_ipv4' => 3, 'leechers_ipv6' => 4]);
    $hit = ['id'          => 12001, 'name' => 'Fixture', 'mediainfo' => '', 'bdinfo' => '', 'description' => '', 'size' => 100,
        'num_file'        => 1, 'files' => [], 'free' => 0, 'doubleup' => false, 'refundable' => false, 'internal' => false,
        'featured'        => false, 'personal_release' => false, 'anon' => true, 'seeders' => 0, 'leechers' => 0,
        'times_completed' => 0, 'tmdb_movie_id' => 0, 'tmdb_tv_id' => 0, 'imdb' => 0, 'tvdb' => 0, 'mal' => 0, 'igdb' => 0, 'created_at' => now()->timestamp];
    $engine = Mockery::mock(Laravel\Scout\Engines\Engine::class);
    $engine->shouldReceive('paginate')->twice()->andReturn(['hits' => [$hit]]);
    $engine->shouldReceive('getTotalCount')->twice()->andReturn(1);
    app(Laravel\Scout\EngineManager::class)->extend('dualstack-fixture', fn () => $engine);
    config(['scout.driver' => 'dualstack-fixture']);
    $controller = app(App\Http\Controllers\API\TorrentController::class);
    $request = Request::create('/api/torrents/filter', 'GET');
    config(['dualstack.enabled' => false]);
    $legacy = $controller->filter($request)->getData(true)['data'][0]['attributes'];
    expect($legacy['seeders'])->toBe(0)->and($legacy)->not->toHaveKey('seeders_ipv6');
    config(['dualstack.enabled' => true]);
    DB::enableQueryLog();
    DB::flushQueryLog();
    $attributes = $controller->filter($request)->getData(true)['data'][0]['attributes'];
    expect($attributes['seeders'])->toBe(3)->and($attributes['leechers'])->toBe(5)
        ->and($attributes['seeders_ipv4'])->toBe(2)->and($attributes['seeders_ipv6'])->toBe(2)
        ->and($attributes['leechers_ipv4'])->toBe(3)->and($attributes['leechers_ipv6'])->toBe(4);
    $queries = array_filter(DB::getQueryLog(), fn ($query) => str_contains($query['query'], 'seeders_ipv4'));
    expect($queries)->toHaveCount(1);
    // Mesma resposta cacheada, outro modo visual: nenhum novo acesso ao motor.
    $this->user->peer_count_mode = 'ipv4';
    $cached = $controller->filter($request)->getData(true)['data'][0]['attributes'];
    expect($cached['seeders'])->toBe(3)->and($cached['seeders_ipv6'])->toBe(2);
});

function preferenceHistory(): void
{
    DB::table('history')->updateOrInsert(['user_id' => 12001, 'torrent_id' => 12001], [
        'agent'      => 'preference-test', 'client_uploaded' => 1000, 'client_downloaded' => 0,
        'active'     => true, 'seeder' => true, 'immune' => false, 'seedtime' => 3600,
        'created_at' => now()->subHour(), 'updated_at' => now(),
    ]);
}

it('carrega contadores nas projecoes das listas sem consultar por endpoint', function (string $component, string $property): void {
    preferencePeer(12001, 'A', true, [4, 6]);
    preferenceHistory();
    DB::table('bookmarks')->updateOrInsert(['user_id' => 12001, 'torrent_id' => 12001], ['created_at' => now(), 'updated_at' => now()]);
    DB::table('torrents')->where('id', 12001)->update(['seeders' => 3, 'leechers' => 5, 'seeders_ipv4' => 2, 'seeders_ipv6' => 2, 'leechers_ipv4' => 3, 'leechers_ipv6' => 4]);
    $view = new $component();
    $view->user = $this->user;
    $page = (new ReflectionProperty($component, $property))->getValue($view);
    $row = $page->first();
    expect($row)->not->toBeNull();
    expect(PeerCountDisplay::count($row, 'seeders', $this->user))->toBe(2)
        ->and(PeerCountDisplay::count($row, 'leechers', $this->user))->toBe(4);
})->with([
    [App\Http\Livewire\UserActive::class, 'actives'],
    [App\Http\Livewire\UserTorrents::class, 'history'],
    [App\Http\Livewire\UserBookmarks::class, 'bookmarks'],
    [App\Http\Livewire\UserEarnings::class, 'torrents'],
]);

it('preserva BON por usuario torrent com dois endpoints e varios peers', function (bool $external): void {
    config(['announce.external_tracker.is_enabled' => $external]);
    DB::table('bon_earnings')->delete();
    $rule = DB::table('bon_earnings')->insertGetId(['position' => 1, 'variable' => 'seeders', 'multiplier' => 10, 'operation' => 'append', 'name' => 'Fixture', 'description' => 'Fixture']);
    DB::table('bon_earning_conditions')->insert(['bon_earning_id' => $rule, 'operand1' => 'connectable', 'operator' => '=', 'operand2' => 1]);
    DB::table('torrents')->where('id', 12001)->update(['seeders' => 3, 'seeders_ipv4' => 2, 'seeders_ipv6' => 2]);
    preferenceHistory();
    preferencePeer(12001, 'A', true, [4]);
    DB::table('peers')->where('user_id', 12001)->update(['connectable' => true]);
    DB::table('peer_ips')->where('user_id', 12001)->where('family', 4)->update(['connectable' => true]);
    $before = (float) $this->user->fresh()->seedbonus;
    app(Kernel::class)->call('auto:bon_allocation');
    expect((float) $this->user->fresh()->seedbonus - $before)->toBe(30.0);
    preferencePeer(12001, 'B', true, [4, 6]);

    foreach (['ipv4', 'ipv6', 'sum', 'auto'] as $mode) {
        DB::table('users')->where('id', 12001)->update(['peer_count_mode' => $mode]);
        $before = (float) $this->user->fresh()->seedbonus;
        app(Kernel::class)->call('auto:bon_allocation');
        expect((float) $this->user->fresh()->seedbonus - $before)->toBe(30.0);
    }
    expect((int) DB::table('history')->where('user_id', 12001)->where('torrent_id', 12001)->value('seedtime'))->toBe(3600);
})->with([false, true]);
