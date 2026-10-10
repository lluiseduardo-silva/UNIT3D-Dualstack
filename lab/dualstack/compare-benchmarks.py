#!/usr/bin/env python3
"""Compara rodadas equivalentes; nao confunde taxa oferecida com capacidade."""
import argparse
import json
from pathlib import Path


def compare(reference, candidate):
    for item in [reference, candidate]:
        assert item['status'] == 'passed', 'Rodada funcionalmente reprovada'
        assert not item['errors'] and item['generator_dropped'] == 0
        assert item['identity_check']['mismatch_count'] == 0
        assert item['identity_check']['rows'] == item['population']['peers']
    assert reference['variant'] in ['original', 'legacy-fixed']
    assert candidate['variant'] == 'candidate'
    for field in ['backend', 'rate', 'effective_rate', 'seconds', 'warmup', 'numwant', 'load', 'traffic']:
        assert reference[field] == candidate[field], 'Perfis diferentes: '+field
    for field in ['peers', 'dual_percent', 'distribution', 'torrents', 'seeders', 'leechers']:
        assert reference['population'][field] == candidate['population'][field], 'Populacoes diferentes: '+field
    assert reference['before']['database'] == candidate['before']['database']
    assert reference['expected_upload'] == candidate['expected_upload'], 'Volumes logicos diferentes'
    changes = {q: (candidate['latency_ms'][q]/reference['latency_ms'][q]-1)*100 for q in ['p95', 'p99']}
    throughput = candidate['achieved_rps']/reference['achieved_rps']
    return dict(status='passed' if all(v <= 10 for v in changes.values()) and throughput >= .95 else 'failed',
                latency_change_percent=changes, accepted_throughput_ratio=throughput,
                maximum_capacity_established=False,
                payload_p50_bytes={name: item['payload_bytes']['p50'] for name, item in [('reference', reference), ('candidate', candidate)]},
                drain_seconds={name: item['drain_seconds'] for name, item in [('reference', reference), ('candidate', candidate)]})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('reference', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        result = compare(json.loads(args.reference.read_text()), json.loads(args.candidate.read_text()))
    except (AssertionError, KeyError, ZeroDivisionError) as error:
        result = dict(status='invalid', reason=str(error))
    result.update(reference=args.reference.name, candidate=args.candidate.name)
    encoded = json.dumps(result, indent=2)+'\n'
    if args.output:
        args.output.write_text(encoded)
    print(encoded, end='')
    raise SystemExit(0 if result['status'] == 'passed' else 1)
