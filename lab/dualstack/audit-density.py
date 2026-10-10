#!/usr/bin/env python3
"""Confere percentis contra amostras e contabilidade contra snapshots exportados."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('series', nargs='+')
parser.add_argument('--root', type=Path, default=Path(__file__).parent/'results'/'density')
args = parser.parse_args()
for series in args.series:
    assert series.startswith('density-') and all(c.isalnum() or c == '-' for c in series)
    folder = args.root/series
    hashes, accepted, samples, phases = {}, 0, 0, 0
    for path in sorted(folder.glob('*.json')):
        run = json.loads(path.read_text())
        assert run['status'] == 'passed'
        assert run['after']['peers']['versions'] == run['cumulative_accepted']
        assert run['identities']['mismatches'] == 0
        assert run['after']['peer_ips']['n'] == 2*run['after']['peers']['n']
        for table in ['peers', 'history', 'users']:
            assert run['after'][table]['uploaded'] == run['expected_upload']
        raw_path = folder/(path.stem+'-samples.json.gz')
        with gzip.open(raw_path, 'rt') as source:
            raw = json.load(source)
        for name, group in run['groups'].items():
            rows = raw['groups'][name]
            assert len(rows) == run['spec']['seconds']*group['rate']
            assert all(r[5] for r in rows) and not group['errors'] and not group['dropped']
            values = sorted((r[2]-r[1])*1000 for r in rows)
            for label, q in [('p50', .5), ('p95', .95), ('p99', .99), ('max', 1)]:
                value = values[min(len(values)-1, math.ceil(len(values)*q)-1)]
                assert math.isclose(value, group['response_read_ms'][label], abs_tol=1e-8)
            if 'accepted_by_torrent' in group:
                assert group['accepted_by_torrent'] == group['offered_by_torrent']
                assert set(group['accepted_by_torrent']) == {str(t) for t in run['spec']['groups'][name]['torrents']}
                assert sum(group['accepted_by_torrent'].values()) == group['accepted']
            samples += len(rows)
        accepted += run['accepted']
        phases += 1
        for item in [path, raw_path]:
            hashes[item.name] = hashlib.sha256(item.read_bytes()).hexdigest()
    assert phases > 0
    final = json.loads((args.root/(series+'-load.jsonl')).read_text(encoding='utf-8-sig').splitlines()[-1])
    assert final['status'] == 'series_passed' and final['accepted'] == accepted and final['phases'] == phases
    result = dict(series=series, status='passed', accepted=accepted, measured_samples=samples, phases=phases, sha256=hashes)
    (args.root/(series+'-audit.json')).write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'sha256'}))
