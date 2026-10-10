<?php
declare(strict_types=1);

require '/app/vendor/autoload.php';
use App\Services\Dualstack\PeerTransition;

// Funcao pura: nao inicializa Laravel, MySQL, Redis nem o tracker Rust.
$fixture = json_decode(file_get_contents('/lab/fixtures/peer-v1.json'), true, flags: JSON_THROW_ON_ERROR);
$trace = [];
foreach ($fixture['cases'] as $case) {
    $state = null;
    $config = array_replace($fixture['defaults'], $case['config'] ?? []);
    foreach ($case['operations'] as $index => $operation) {
        $request = array_replace($fixture['request_defaults'], $operation);
        $result = PeerTransition::apply($state, $request, $config);
        $state = $result['peer'];
        // PHP codifica mapa vazio como []; o contrato de endpoints e um objeto.
        if ($result['peer'] !== null) {
            foreach (['endpoints', 'last_announces'] as $field) {
                $result['peer'][$field] = (object) $result['peer'][$field];
            }
        }
        $trace[] = [
            'case' => $case['name'], 'operation' => $index, 'transition' => $result,
            'counts' => PeerTransition::counts($state, false),
            'connectable_counts' => PeerTransition::counts($state, true),
            'current_counts' => PeerTransition::counts($state, false, $request['at'], $config['endpoint_ttl']),
            'current_connectable_counts' => PeerTransition::counts($state, true, $request['at'], $config['endpoint_ttl']),
        ];
    }
}
echo json_encode(['version' => 1, 'steps' => $trace], JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR)."\n";
