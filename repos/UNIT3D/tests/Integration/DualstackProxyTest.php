<?php

declare(strict_types=1);

use App\Http\Middleware\TrustProxies;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Http\Request;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

beforeEach(function (): void {
    $this->originalProxyConfig = array_combine(
        ['dualstack.enabled', 'dualstack.trusted_proxies', 'trustedproxy.proxies'],
        [config('dualstack.enabled'), config('dualstack.trusted_proxies'), config('trustedproxy.proxies')]
    );
});

afterEach(function (): void {
    config($this->originalProxyConfig);
    Request::setTrustedProxies([], Request::HEADER_X_FORWARDED_FOR);
});

it('usa somente proxies dualstack explicitos e preserva a origem no modo legado', function (bool $enabled, array $proxies, string $remote, string $expected): void {
    config(['dualstack.enabled' => $enabled, 'dualstack.trusted_proxies' => $proxies, 'trustedproxy.proxies' => '*']);
    $request = Request::create('https://tracker.on-forge.com/announce/test', server: [
        'REMOTE_ADDR' => $remote, 'HTTP_X_FORWARDED_FOR' => '2001:db8::30',
    ]);
    // Simula confianca residual de outra request no mesmo processo.
    Request::setTrustedProxies([$remote], Request::HEADER_X_FORWARDED_FOR);
    $result = (new TrustProxies())->handle($request, fn (Request $request): string => $request->ip());
    expect($result)->toBe($expected);
})->with([
    'proxy IPv4 confiavel'     => [true, ['127.0.0.1/32'], '127.0.0.1', '2001:db8::30'],
    'proxy IPv6 confiavel'     => [true, ['::1/128'], '::1', '2001:db8::30'],
    'origem sem confianca'     => [true, ['127.0.0.1/32'], '172.29.92.30', '172.29.92.30'],
    'lista vazia sem fallback' => [true, [], '172.29.92.30', '172.29.92.30'],
    'legado nao usa headers'   => [false, ['127.0.0.1/32'], '127.0.0.1', '127.0.0.1'],
]);

it('recusa proxies sem endereco explicito ou com prefixo invalido', function (string $proxy): void {
    config(['dualstack.enabled' => true, 'dualstack.trusted_proxies' => [$proxy]]);
    expect(fn () => (new TrustProxies())->handle(Request::create('/'), fn () => null))
        ->toThrow(RuntimeException::class, 'proxies confiaveis explicitos');
})->with(['*', '**', 'REMOTE_ADDR', 'tracker.lab', '127.0.0.1/33', '::1/129', '::1/-1']);
