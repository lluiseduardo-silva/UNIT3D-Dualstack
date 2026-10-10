#!/usr/bin/env python3
"""Compara todos os campos das transicoes PHP/Rust, nao somente os exemplos esperados."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', type=Path, required=True)
    parser.add_argument('--rust', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads((Path(__file__).parent/'fixtures/peer-v1.json').read_text(encoding='utf-8'))
    expected = [(case['name'], index) for case in fixture['cases'] for index, _ in enumerate(case['operations'])]
    php = json.loads(args.php.read_text(encoding='utf-8-sig'))
    rust = json.loads(args.rust.read_text(encoding='utf-8-sig'))
    result = {'status': 'failed', 'cases': len(fixture['cases']), 'operations': len(expected),
              'php_sha256': hashlib.sha256(args.php.read_bytes()).hexdigest(),
              'rust_sha256': hashlib.sha256(args.rust.read_bytes()).hexdigest()}
    try:
        assert expected and php['version'] == rust['version'] == fixture['version'], 'Versao ou fixture invalida.'
        for name, trace in [('php', php), ('rust', rust)]:
            assert [(step['case'], step['operation']) for step in trace['steps']] == expected, name+': operacoes ausentes ou fora de ordem.'
        for index, (left, right) in enumerate(zip(php['steps'], rust['steps'])):
            assert left == right, 'Divergencia no caso '+str(expected[index])+'. Consulte os snapshots completos.'
        result['status'] = 'passed'
    except AssertionError as error:
        result['error'] = str(error)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))
    raise SystemExit(0 if result['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()
