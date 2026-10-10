<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use InvalidArgumentException;
use OverflowException;

/** Contadores de protocolo sao uint64; JSON/Lua nao podem arredondar seus valores. */
final class Counter
{
    public const MAX = '18446744073709551615';

    public static function of(string|int $value): string
    {
        $value = (string) $value;

        if ($value === '' || \strlen($value) > 20 || !ctype_digit($value)) {
            throw new InvalidArgumentException('Contador cumulativo invalido.');
        }
        $value = ltrim($value, '0') ?: '0';

        if (self::compare($value, self::MAX) > 0) {
            throw new OverflowException('Contador fora do intervalo uint64.');
        }

        return $value;
    }

    public static function compare(string $a, string $b): int
    {
        return \strlen($a) <=> \strlen($b) ?: strcmp($a, $b);
    }

    public static function maximum(string $a, string $b): string
    {
        return self::compare($a, $b) >= 0 ? $a : $b;
    }

    public static function add(string $a, string $b): string
    {
        $length = max(\strlen($a), \strlen($b));
        $a = str_pad($a, $length, '0', STR_PAD_LEFT);
        $b = str_pad($b, $length, '0', STR_PAD_LEFT);
        $carry = 0;
        $result = '';

        for ($i = $length - 1; $i >= 0; $i--) {
            $digit = (int) $a[$i] + (int) $b[$i] + $carry;
            $result = (string) ($digit % 10).$result;
            $carry = intdiv($digit, 10);
        }

        return self::of(($carry ? (string) $carry : '').$result);
    }

    public static function delta(string $received, string $reference): string
    {
        if (self::compare($received, $reference) <= 0) {
            return '0';
        }
        $reference = str_pad($reference, \strlen($received), '0', STR_PAD_LEFT);
        $result = '';
        $borrow = 0;

        for ($i = \strlen($received) - 1; $i >= 0; $i--) {
            $digit = (int) $received[$i] - (int) $reference[$i] - $borrow;
            $borrow = $digit < 0 ? 1 : 0;
            $result = (string) ($digit + 10 * $borrow).$result;
        }

        return ltrim($result, '0') ?: '0';
    }

    /** Aplica percentual inteiro e arredonda para baixo como a contabilidade legada. */
    public static function percent(string $value, int $percent): string
    {
        if ($percent < 0 || $percent > 200) {
            throw new InvalidArgumentException('Percentual de credito invalido.');
        }
        $carry = 0;
        $product = '';

        for ($i = \strlen($value) - 1; $i >= 0; $i--) {
            $digit = (int) $value[$i] * $percent + $carry;
            $product = (string) ($digit % 10).$product;
            $carry = intdiv($digit, 10);
        }
        $product = ($carry > 0 ? (string) $carry : '').$product;

        return self::of(\strlen($product) > 2 ? (ltrim(substr($product, 0, -2), '0') ?: '0') : '0');
    }
}
