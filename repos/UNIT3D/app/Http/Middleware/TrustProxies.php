<?php

declare(strict_types=1);

/**
 * NOTICE OF LICENSE.
 *
 * UNIT3D Community Edition is open-sourced software licensed under the GNU Affero General Public License v3.0
 * The details is bundled with this project in the file LICENSE.txt.
 *
 * @project    UNIT3D Community Edition
 *
 * @author     HDVinnie <hdinnovations@protonmail.com>
 * @license    https://www.gnu.org/licenses/agpl-3.0.en.html/ GNU Affero General Public License v3.0
 */

namespace App\Http\Middleware;

use Illuminate\Http\Middleware\TrustProxies as Middleware;
use Symfony\Component\HttpFoundation\Request as RequestAlias;
use Closure;
use RuntimeException;

class TrustProxies extends Middleware
{
    public function handle(\Illuminate\Http\Request $request, Closure $next)
    {
        // O kernel legado nao confiava em headers de proxy. Limpar tambem o
        // estado estatico evita transportar confianca entre requests/testes.
        $request::setTrustedProxies([], $this->headers);

        if (config('dualstack.enabled')) {
            $proxies = config('dualstack.trusted_proxies', []);

            foreach ($proxies as $proxy) {
                $parts = explode('/', $proxy);
                $width = str_contains($parts[0], ':') ? 128 : 32;

                if (filter_var($parts[0], FILTER_VALIDATE_IP) === false || \count($parts) > 2
                    || (isset($parts[1]) && (!ctype_digit($parts[1]) || (int) $parts[1] > $width))) {
                    throw new RuntimeException('Dualstack exige proxies confiaveis explicitos.');
                }
            }
            // Nao usar o fallback do framework para trustedproxy.proxies ou
            // hosts especiais: uma lista dualstack vazia deve continuar vazia.
            $request::setTrustedProxies($proxies, $this->headers);
        }

        return $next($request);
    }

    /**
     * The trusted proxies for this application.
     *
     * @var array<int, string>|string|null
     */
    protected $proxies = [];

    /**
     * The headers that should be used to detect proxies.
     *
     * @var int
     */
    protected $headers = RequestAlias::HEADER_X_FORWARDED_FOR | RequestAlias::HEADER_X_FORWARDED_HOST | RequestAlias::HEADER_X_FORWARDED_PORT | RequestAlias::HEADER_X_FORWARDED_PROTO | RequestAlias::HEADER_X_FORWARDED_AWS_ELB;
}
