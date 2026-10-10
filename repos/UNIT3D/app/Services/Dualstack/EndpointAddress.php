<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use InvalidArgumentException;

final readonly class EndpointAddress
{
    private function __construct(public int $family, public string $binary)
    {
    }

    public static function observed(string $address, bool $allowPrivate = false): self
    {
        $binary = @inet_pton($address);

        if ($binary === false) {
            throw new InvalidArgumentException('Endereco de origem invalido.');
        }

        if (\strlen($binary) === 16 && substr($binary, 0, 12) === str_repeat("\0", 10)."\xff\xff") {
            $binary = substr($binary, 12);
        }
        $family = \strlen($binary) === 4 ? 4 : 6;
        $first = \ord($binary[0]);
        $second = \ord($binary[1]);

        if ($family === 4) {
            $invalid = $first === 0 || $first === 127 || $first >= 224 || ($first === 169 && $second === 254);
            $private = $first === 10 || ($first === 172 && $second >= 16 && $second <= 31)
                || ($first === 192 && $second === 168) || ($first === 100 && $second >= 64 && $second <= 127);
        } else {
            $invalid = $binary === str_repeat("\0", 16) || $binary === str_repeat("\0", 15)."\x01"
                || $first === 255 || ($first === 254 && ($second & 192) === 128);
            $private = ($first & 254) === 252;
        }

        if ($invalid || ($private && !$allowPrivate)) {
            throw new InvalidArgumentException('Endereco de origem nao publicavel.');
        }

        return new self($family, $binary);
    }

    public function text(): string
    {
        return inet_ntop($this->binary);
    }
}
