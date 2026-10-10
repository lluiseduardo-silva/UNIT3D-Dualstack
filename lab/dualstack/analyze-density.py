#!/usr/bin/env python3
"""Reproduz medianas entre repeticoes e correlaciona recursos na janela medida."""
import argparse
import collections
import importlib.util
import json
import re
import statistics
from pathlib import Path


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def span(values):
    return dict(median=statistics.median(values), minimum=min(values), maximum=max(values))


def analyze(root, series):
    records = lines(root/(series+'-load.jsonl'))
    assert records[-1]['status'] == 'series_passed'
    runs = records[:-1]
    assert all(r['status'] == 'passed' for r in runs)
    assert sum(r['accepted'] for r in runs) == records[-1]['accepted']
    buckets = collections.defaultdict(list)
    for r in runs:
        buckets[re.sub(r'-r\d+$', '', r['name'])].append(r)
    cases = {}
    for name, rows in buckets.items():
        groups = {}
        for group in rows[0]['groups']:
            members = [r['groups'][group] for r in rows]
            assert len({m['rate'] for m in members}) == 1
            groups[group] = dict(rate=members[0]['rate'],
                accepted=sum(m['accepted'] for m in members),
                errors=sum(sum(m['errors'].values()) for m in members),
                dropped=sum(m['dropped'] for m in members),
                completed_rps=span([m['completed_rps'] for m in members]),
                **{metric: {percentile: span([m[metric][percentile] for m in members])
                            for percentile in ['p50', 'p95', 'p99']}
                   for metric in ['response_read_ms', 'queue_wait_ms', 'end_to_end_ms', 'validation_ms']})
        cases[name] = dict(repetitions=len(rows), groups=groups,
            generator_cpu_percent=span([r['generator_cpu_percent'] for r in rows]),
            drain_seconds=span([r['drain_seconds'] for r in rows]))
    spec = importlib.util.spec_from_file_location('io_analysis', Path(__file__).with_name('analyze-benchmark-io.py'))
    io = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(io)
    samples = {kind: lines(root/(series+'-'+kind+'.jsonl')) for kind in ['data', 'host']}
    tracker_file = root/(series+'-unit3d-ds-tracker.jsonl')
    tracker = lines(tracker_file) if tracker_file.exists() else []
    resources = {}
    for r in runs:
        start = r['measured_at_epoch']
        end = start+r['spec']['seconds']
        usage = [container for row in tracker if start <= row['at'] <= end
                 for container in row['containers'] if container['Name'] == 'unit3d-ds-rust']
        resources[r['name']] = dict(
            observations={k: io.summarize(v, start, end) for k, v in samples.items()},
            tracker_cpu_percent=span([float(c['CPUPerc'].rstrip('%')) for c in usage]) if usage else None,
            tracker_memory_samples=[c['MemUsage'] for c in usage])
    output = dict(series=series, phase_count=len(runs), accepted=records[-1]['accepted'],
        resident_peers=sum(runs[0]['sizes']), resident_torrents=len(runs[0]['sizes']),
        resident_users=runs[0]['users'], dual_percent=100, cases=cases, resources=resources,
        description='Medianas/minimos/maximos de percentis por repeticao; nao sao percentis de amostras agrupadas.')
    comparisons = {}
    for name, case in cases.items():
        if name.startswith(('curve-n', 'refine-n')):
            control, group = name.split('-n')[0]+'-n50', 'target'
        elif name.startswith('fixed-dense-'):
            control, group = 'fixed-control', 'probe'
        elif '-dense-' in name:
            control, group = name.replace('-dense-', '-control-'), 'probe'
        else:
            continue
        baseline = cases[control]['groups'][group]['response_read_ms']['p99']['median']
        value = case['groups'][group]['response_read_ms']['p99']['median']
        comparisons[name] = dict(control=control, group=group, baseline_p99_ms=baseline,
            p99_ms=value, delta_ms=value-baseline, delta_percent=100*(value/baseline-1),
            large_degradation=value >= 1.5*baseline and value-baseline >= .5)
    output['comparisons'] = comparisons
    target = root/(series+'-analysis.json')
    target.write_text(json.dumps(output, indent=2)+'\n')
    return dict(series=series, phases=len(runs), accepted=output['accepted'], analysis=str(target))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('series', nargs='+')
    parser.add_argument('--root', type=Path, default=Path(__file__).parent/'results'/'density')
    args = parser.parse_args()
    for name in args.series:
        assert re.fullmatch(r'density-[a-z0-9-]+', name)
        print(json.dumps(analyze(args.root, name)))
