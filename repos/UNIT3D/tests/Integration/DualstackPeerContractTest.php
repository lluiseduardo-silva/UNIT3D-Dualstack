<?php

declare(strict_types=1);

use App\Services\Dualstack\Counter;
use App\Services\Dualstack\PeerTransition;

$fixturePath = getenv('DUALSTACK_PEER_FIXTURES');
$contract = $fixturePath ? json_decode(file_get_contents($fixturePath), true, flags: JSON_THROW_ON_ERROR) : null;
$cases = $contract === null ? ['fixture ausente' => [null]] : array_column($contract['cases'], null, 'name');

it('executa o contrato compartilhado de peer', function (?array $case) use ($contract): void {
    if ($case === null) {
        $this->markTestSkipped('Defina DUALSTACK_PEER_FIXTURES para o contrato compartilhado peer-v1.json.');
    }
    $state = null;
    $config = array_replace($contract['defaults'], $case['config'] ?? []);

    foreach ($case['operations'] as $operation) {
        $request = array_replace($contract['request_defaults'], $operation);
        $result = PeerTransition::apply($state, $request, $config);
        $state = $result['peer'];
        $observed = $state ?? [];
        $observed['families'] = array_keys($state['endpoints'] ?? []);
        $observed['exists'] = $state !== null;

        foreach ([4, 6] as $family) {
            $observed['ipv'.$family] = $state['endpoints'][$family]['ip'] ?? null;
            $observed['revision'.$family] = $state['endpoints'][$family]['revision'] ?? null;
            $observed['connectable'.$family] = $state['endpoints'][$family]['connectable'] ?? null;
        }
        $observed = array_replace($observed, $result);

        foreach (array_replace(['outcome' => 'accepted'], $operation['expect'] ?? []) as $field => $value) {
            expect($observed[$field], $case['name'].' @'.$operation['at'].' '.$field)->toBe($value);
        }
        expect(\count($observed['families']))->toBeLessThanOrEqual($config['max_endpoints']);
    }
})->with(array_map(fn ($case) => [$case], $cases));

it('mantem precisao uint64 e fatores financeiros sem floats', function (): void {
    expect(Counter::delta('18446744073709551615', '18446744073709551614'))->toBe('1')
        ->and(Counter::percent('9007199254740993', 200))->toBe('18014398509481986')
        ->and(Counter::percent('101', 75))->toBe('75')
        ->and(Counter::percent('18446744073709551615', 0))->toBe('0');
    expect(fn () => Counter::of('18446744073709551616'))->toThrow(OverflowException::class);
    expect(fn () => Counter::of('1e3'))->toThrow(InvalidArgumentException::class);
});
