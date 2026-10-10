<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use InvalidArgumentException;

/** Funcao de transicao pura. A referencia so avanca quando o CAS aceita o resultado. */
final class PeerTransition
{
    public static function apply(?array $before, array $request, array $policy): array
    {
        $ttl = (int) $policy['endpoint_ttl'];
        $maxEndpoints = (int) $policy['max_endpoints'];
        $minInterval = (int) $policy['min_interval'];

        if ($ttl < 1 || !\in_array($maxEndpoints, [1, 2], true) || $minInterval < 0) {
            throw new InvalidArgumentException('Configuracao dualstack invalida.');
        }
        $kind = $request['kind'] ?? 'announce';

        if (!\in_array($kind, ['announce', 'expire', 'probe', 'flush'], true)) {
            throw new InvalidArgumentException('Operacao de peer invalida.');
        }
        $now = max((int) $request['at'], (int) ($before['updated_at'] ?? 0));
        $version = (int) ($before['state_version'] ?? 0) + 1;
        $state = $before;

        if ($kind === 'flush') {
            if (!isset($request['cutoff']) || !\is_int($request['cutoff']) || $request['cutoff'] > $now - 4200) {
                throw new InvalidArgumentException('Corte de limpeza invalido.');
            }

            // Nunca inferir a elegibilidade pelo snapshot SQL do site: o CAS relera
            // o endpoint corrente se um announce disputar esta transicao.
            if ($state !== null) {
                foreach ($state['endpoints'] as $family => $endpoint) {
                    if ($endpoint['last_announced_at'] < $request['cutoff']) {
                        unset($state['endpoints'][$family]);
                    }
                }
            }

            if ($state === null || $state['endpoints'] === $before['endpoints']) {
                return self::result('ignored', $before);
            }

            return self::accepted($state, $version, $now);
        }

        if ($state !== null) {
            foreach ($state['endpoints'] as $family => $endpoint) {
                if ($endpoint['last_announced_at'] + $ttl <= $now) {
                    unset($state['endpoints'][$family]);
                }
            }
        }

        if ($kind === 'probe') {
            $ip = EndpointAddress::observed($request['ip'], (bool) ($policy['allow_private_addresses'] ?? false));
            $endpoint = $state['endpoints'][$ip->family] ?? null;

            if ($endpoint === null || $endpoint['ip'] !== $ip->text()
                || $endpoint['port'] !== (int) $request['port']
                || $endpoint['revision'] !== (int) $request['revision']
                || $endpoint['last_announced_at'] + $ttl <= $now) {
                return self::result('ignored', $before);
            }
            $state['endpoints'][$ip->family]['connectable'] = (bool) $request['connectable'];
            $state['endpoints'][$ip->family]['connectivity_checked_at'] = $now;

            return self::accepted($state, $version, $now);
        }

        if ($kind === 'expire') {
            if ($state === null || $state['endpoints'] === $before['endpoints']) {
                return self::result('ignored', $before);
            }

            return self::accepted($state, $version, $now);
        }

        $ip = EndpointAddress::observed($request['ip'], (bool) ($policy['allow_private_addresses'] ?? false));
        $event = $request['event'];
        $uploaded = Counter::of($request['uploaded']);
        $downloaded = Counter::of($request['downloaded']);
        $left = Counter::of($request['left']);
        $port = (int) $request['port'];

        if (!\in_array($event, ['', 'started', 'completed', 'stopped', 'paused'], true)
            || $port < 0 || $port > 65535 || ($port < 1024 && $event !== 'stopped')) {
            throw new InvalidArgumentException('Evento ou porta invalida.');
        }
        $endpoint = $state['endpoints'][$ip->family] ?? null;

        if ($event === 'stopped' && ($endpoint === null || $endpoint['ip'] !== $ip->text())) {
            return self::result('ignored', $before);
        }
        $newSession = $state === null || ($state['endpoints'] === [] && $event === 'started');

        if (!$newSession && !\in_array($event, ['completed', 'stopped'], true)
            && isset($state['last_announces'][$ip->family])
            && $now - $state['last_announces'][$ip->family] < $minInterval) {
            return self::result('rejected', $before, reason: 'interval');
        }

        if ($endpoint === null && $event !== 'stopped' && \count($state['endpoints'] ?? []) >= $maxEndpoints) {
            return self::result('rejected', $before, reason: 'endpoint_limit');
        }

        $uploadDelta = $newSession ? '0' : Counter::delta($uploaded, $state['uploaded']);
        $downloadDelta = $newSession ? '0' : Counter::delta($downloaded, $state['downloaded']);
        $stale = !$newSession && (Counter::compare($downloaded, $state['downloaded']) < 0
            || ($downloaded === $state['downloaded'] && Counter::compare($uploaded, $state['uploaded']) < 0));

        if ($newSession) {
            $state = [
                'uploaded'            => $uploaded, 'downloaded' => $downloaded, 'left' => $left,
                'agent'               => $request['agent'], 'visible' => (bool) $request['visible'],
                'endpoints'           => [], 'last_announces' => [],
                'session_generation'  => (int) ($before['session_generation'] ?? 0) + 1,
                'completion_reported' => $left === '0',
                'created_at'          => $before['created_at'] ?? $now, 'session_started_at' => $now,
                'legacy_endpoint'     => $before['legacy_endpoint'] ?? null,
            ];
        } else {
            $state['uploaded'] = Counter::maximum($state['uploaded'], $uploaded);
            $state['downloaded'] = Counter::maximum($state['downloaded'], $downloaded);

            if (!$stale) {
                $state['left'] = $left;
            }
            $state['agent'] = $request['agent'];
            $state['visible'] = (bool) $request['visible'];
        }
        $completed = !$newSession && !$stale && $event === 'completed' && $left === '0' && !$state['completion_reported'];
        $state['completion_reported'] = $state['completion_reported'] || $completed;
        $state['last_announces'][$ip->family] = $now;

        if ($event === 'stopped') {
            unset($state['endpoints'][$ip->family]);
        } else {
            if ($endpoint === null || $endpoint['ip'] !== $ip->text() || $endpoint['port'] !== $port) {
                $endpoint = [
                    'family'      => $ip->family, 'ip' => $ip->text(), 'port' => $port,
                    'connectable' => null, 'connectivity_checked_at' => null,
                    'revision'    => $version, 'created_at' => $now,
                ];
            }
            $endpoint['last_announced_at'] = $now;
            $state['endpoints'][$ip->family] = $endpoint;
        }

        return self::accepted($state, $version, $now, $uploadDelta, $downloadDelta, (int) $completed);
    }

    private static function accepted(array $state, int $version, int $now, string $uploadDelta = '0', string $downloadDelta = '0', int $completed = 0): array
    {
        ksort($state['endpoints']);
        $state['state_version'] = $version;
        $state['updated_at'] = $now;
        $state['active'] = $state['endpoints'] !== [];
        $state['seeder'] = $state['left'] === '0';
        $state['connectable'] = false;

        foreach ($state['endpoints'] as $endpoint) {
            $state['connectable'] = $state['connectable'] || $endpoint['connectable'] === true;
        }

        if ($state['active']) {
            $state['legacy_endpoint'] = reset($state['endpoints']);

            foreach ($state['endpoints'] as $endpoint) {
                if ($endpoint['connectable'] === true) {
                    $state['legacy_endpoint'] = $endpoint;

                    break;
                }
            }
        }

        return self::result('accepted', $state, $uploadDelta, $downloadDelta, $completed);
    }

    private static function result(string $outcome, ?array $state, string $uploadDelta = '0', string $downloadDelta = '0', int $completed = 0, ?string $reason = null): array
    {
        return ['outcome'  => $outcome, 'reason' => $reason, 'peer' => $state,
            'upload_delta' => $uploadDelta, 'download_delta' => $downloadDelta, 'completed_delta' => $completed];
    }

    /** Contribuicao do snapshot persistido; a validade temporal e usada nas leituras. */
    public static function counts(?array $state, bool $requireConnectivity, ?int $now = null, int $ttl = 7200): array
    {
        $counts = array_fill_keys(['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6'], 0);

        if ($state === null || !$state['active'] || !$state['visible']) {
            return $counts;
        }
        $kind = $state['seeder'] ? 'seeders' : 'leechers';

        foreach ($state['endpoints'] as $family => $endpoint) {
            if (($now === null || $endpoint['last_announced_at'] + $ttl > $now)
                && (!$requireConnectivity || $endpoint['connectable'] === true)) {
                $counts[$kind] = 1;
                $counts[$kind.'_ipv'.$family] = 1;
            }
        }

        return $counts;
    }
}
