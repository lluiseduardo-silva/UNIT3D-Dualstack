<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use InvalidArgumentException;

final class Policy
{
    public static function configured(): array
    {
        $policy = [
            'endpoint_ttl'            => (int) config('dualstack.endpoint_ttl'),
            'max_endpoints'           => (int) config('dualstack.max_endpoints_per_peer'),
            'max_peers'               => (int) config('announce.rate_limit'),
            'min_interval'            => 1530,
            'seedtime_max_interval'   => 5400,
            'allow_private_addresses' => (bool) config('dualstack.allow_private_addresses'),
            'require_connectivity'    => (bool) config('dualstack.require_connectivity'),
            'max_pending_transitions' => (int) config('dualstack.max_pending_transitions'),
        ];

        if (!\in_array($policy['max_endpoints'], [1, 2], true) || $policy['endpoint_ttl'] < 1
            || $policy['max_peers'] < 1 || $policy['max_pending_transitions'] < 1) {
            throw new InvalidArgumentException('Configuracao dualstack invalida.');
        }

        return $policy;
    }
}
