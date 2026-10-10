<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use App\Models\User;
use InvalidArgumentException;

/** Apresentacao apenas: nunca substituir os atributos contabeis do torrent. */
final class PeerCountDisplay
{
    public const array FAMILY_COLUMNS = ['seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6'];

    public static function mode(?User $viewer): string
    {
        if (!config('dualstack.enabled')) {
            return 'sum';
        }

        $mode = $viewer?->peer_count_mode ?? 'sum';
        $mode = $mode === 'auto' ? ($viewer?->peer_count_auto_mode ?? 'sum') : $mode;

        return \in_array($mode, ['ipv4', 'ipv6'], true) ? $mode : 'sum';
    }

    public static function count(object $torrent, string $kind, ?User $viewer, ?int $legacy = null): int
    {
        if (!\in_array($kind, ['seeders', 'leechers'], true)) {
            throw new InvalidArgumentException('Tipo de contador invalido.');
        }

        if (!config('dualstack.enabled')) {
            return $legacy ?? (int) $torrent->{$kind};
        }

        $mode = self::mode($viewer);
        $column = $mode === 'sum' ? $kind : $kind.'_'.$mode;

        return (int) $torrent->{$column};
    }
}
