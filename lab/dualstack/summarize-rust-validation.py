#!/usr/bin/env python3
"""Consolida rodadas e deltas de I/O, sem juntar percentis de populacoes diferentes."""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics

spec = importlib.util.spec_from_file_location('io_metrics', Path(__file__).with_name('analyze-benchmark-io.py'))
io_metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(io_metrics)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    runs = {}
    for path in sorted(args.directory.glob('validation-*-summary.json')):
        label = path.name.removesuffix('-summary.json')
        run = read(path)
        assert run['status'] == 'passed' and not run['errors'] and run['generator_dropped'] == 0
        start = run['measured_at_epoch']
        observations = []
        for host in ['data', 'host']:
            samples = [json.loads(line) for line in (args.directory/(label+'-'+host+'.jsonl')).read_text(encoding='utf-8-sig').splitlines()]
            observations.append(io_metrics.summarize(samples, start, start+run['seconds']))
        output = dict(summary=run, io=observations)
        raw_path = args.directory.parent/'benchmarks'/Path(run['result']).name
        if raw_path.exists():
            raw = read(raw_path)
            output['final'] = raw['after']
            output['peak_observed_pending_bytes'] = max((r['pending_bytes'] for r in raw['samples']), default=None)
            if run['variant'] == 'candidate':
                # Estimativa: o contador de requests e coletado depois do snapshot SQL.
                output['peak_observed_unconfirmed_versions'] = max((max(0, r['accepted']-(r['state']['peers']['versions']-raw['before']['peers']['versions'])) for r in raw['samples']), default=None)
        runs[label] = output
    pairs = []
    for label, data in runs.items():
        if not label.endswith('-original'):
            continue
        other = label.removesuffix('-original')+'-candidate'
        if other not in runs:
            other = label.removesuffix('-original')+'-retry-candidate'
        if other not in runs:
            continue
        a, b = data['summary'], runs[other]['summary']
        assert all(a[k] == b[k] for k in ['rate','seconds','warmup','numwant','load'])
        assert a.get('monitor_interval', 5) == b.get('monitor_interval', 5)
        assert a.get('fixture_statistics_analyzed', False) == b.get('fixture_statistics_analyzed', False)
        assert all(a['population'][k] == b['population'][k] for k in ['peers','dual_percent','distribution'])
        changes = {metric: {q: 100*(b[metric][q]/a[metric][q]-1) for q in ['p95','p99']}
                   for metric in ['latency_ms','response_read_ms']}
        pairs.append(dict(original=label, candidate=other, change_percent=changes,
            accepted_throughput_ratio=b['achieved_rps']/a['achieved_rps'],
            short_latency_gate=all(v <= 10 for v in changes['latency_ms'].values())))
    groups = {}
    for variant in ['original','candidate']:
        repeated = [r['summary'] for label, r in runs.items() if label.startswith(('validation-r1-','validation-r2-','validation-r3-')) and label.endswith('-'+variant)]
        if repeated:
            groups[variant] = dict(repetitions=len(repeated), metrics={metric: {q: dict(
                minimum=min(r[metric][q] for r in repeated),
                median=statistics.median(r[metric][q] for r in repeated),
                maximum=max(r[metric][q] for r in repeated)) for q in ['p95','p99']}
                for metric in ['latency_ms','response_read_ms']})
    print(json.dumps(dict(runs=runs, pairs=pairs, repeated_groups=groups,
                         full_performance_acceptance=False), indent=2))


if __name__ == '__main__':
    main()
