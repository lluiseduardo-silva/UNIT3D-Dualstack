<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use InvalidArgumentException;
use OverflowException;

/** Leitor do contrato administrativo schema 1. Nao usa a projecao legada de IP. */
final class ExternalTorrent
{
    public static function normalize(array $torrent): array
    {
        $capabilities = $torrent['capabilities'] ?? null;

        if (!\is_array($capabilities) || ($capabilities['dualstack'] ?? null) !== true
            || ($capabilities['peer_schema'] ?? null) !== 1 || ($capabilities['peer_count'] ?? null) !== 'unique'
            || !\in_array($capabilities['max_endpoints'] ?? null, [1, 2], true)) {
            return [];
        }

        foreach (['seeders', 'leechers'] as $kind) {
            foreach ([$kind, $kind.'_ipv4', $kind.'_ipv6'] as $field) {
                if (!\is_int($torrent[$field] ?? null) || $torrent[$field] < 0) {
                    return [];
                }
            }

            if ($torrent[$kind] < max($torrent[$kind.'_ipv4'], $torrent[$kind.'_ipv6'])
                || $torrent[$kind] > $torrent[$kind.'_ipv4'] + $torrent[$kind.'_ipv6']) {
                return [];
            }
        }

        foreach ($torrent['peers'] as $key => &$peer) {
            if (!\is_array($peer) || !preg_match('/^([1-9][0-9]*)-([0-9a-fA-F]{40})$/D', (string) $key, $identity)
                || !\is_array($peer['endpoints'] ?? null) || !array_is_list($peer['endpoints']) || \count($peer['endpoints']) > 2) {
                return [];
            }

            foreach (['is_seeder', 'is_active', 'is_visible', 'connectable'] as $field) {
                if (!\is_bool($peer[$field] ?? null)) {
                    return [];
                }
            }

            foreach (['updated_at', 'created_at', 'state_version', 'session_generation'] as $field) {
                if (!\is_int($peer[$field] ?? null) || $peer[$field] < 0) {
                    return [];
                }
            }

            try {
                foreach (['uploaded', 'downloaded', 'left'] as $field) {
                    if (!\is_string($peer[$field] ?? null)) {
                        return [];
                    }
                    $peer[$field] = Counter::of($peer[$field]);
                }

                $families = [];

                foreach ($peer['endpoints'] as &$endpoint) {
                    if (!\is_array($endpoint) || !\in_array($endpoint['family'] ?? null, [4, 6], true)
                        || isset($families[$endpoint['family']]) || !\is_string($endpoint['ip_address'] ?? null)
                        || !\is_int($endpoint['port'] ?? null) || $endpoint['port'] < 1024 || $endpoint['port'] > 65535
                        || !\array_key_exists('connectable', $endpoint) || ($endpoint['connectable'] !== null && !\is_bool($endpoint['connectable']))) {
                        return [];
                    }

                    $address = EndpointAddress::observed($endpoint['ip_address'], true);

                    if ($address->family !== $endpoint['family']) {
                        return [];
                    }

                    foreach (['last_announced_at', 'revision'] as $field) {
                        if (!\is_int($endpoint[$field] ?? null) || $endpoint[$field] < 0) {
                            return [];
                        }
                    }

                    if (!\array_key_exists('connectivity_checked_at', $endpoint)
                        || ($endpoint['connectivity_checked_at'] !== null && (!\is_int($endpoint['connectivity_checked_at']) || $endpoint['connectivity_checked_at'] < 0))) {
                        return [];
                    }
                    $families[$endpoint['family']] = true;
                    $endpoint['ip_address'] = $address->text();
                }
                unset($endpoint);
            } catch (InvalidArgumentException|OverflowException) {
                return [];
            }

            if ($peer['is_active'] !== ($peer['endpoints'] !== [])) {
                return [];
            }
            $peer['user_id'] = (int) $identity[1];
            $peer['peer_id'] = hex2bin($identity[2]);
        }
        unset($peer);

        return $torrent;
    }
}
