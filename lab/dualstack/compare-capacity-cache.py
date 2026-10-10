#!/usr/bin/env python3
"""Compara as evidências públicas A1/B/A2, sem aprovar teto sustentado."""
import argparse
import bisect
import json
from pathlib import Path
import statistics


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def aligned_windows(root, result):
    """Mesma interpolação do capacity_metrics; conferida contra seu resumo."""
    name = result['name']
    progress = sorted(lines(root/'clients/results/capacity'/name/'progress.jsonl'),
                      key=lambda row: row['at'])
    times = [row['at'] for row in progress]
    observations = lines(root/'data/results/capacity'/name/'data-observer.jsonl')
    rows = []
    for sample in observations:
        at = (sample['sql_start'] + sample['sql_end']) / 2
        if not result['measured_at'] <= at <= result['finish_epoch']:
            continue
        index = bisect.bisect_right(times, at)
        if not 0 < index < len(progress):
            continue
        left, right = progress[index-1:index+1]
        span = right['at'] - left['at']
        if not 0 < span <= 3:
            continue
        persisted = next((int(line.split('\t')[1]) for line in sample['mysql']
                          if line.startswith('persisted\t')), None)
        if persisted is None:
            continue
        accepted = left['accepted'] + (right['accepted']-left['accepted'])*(at-left['at'])/span
        rows.append({'seconds': at-result['measured_at'], 'lag': max(0, accepted-persisted)})
    rows.sort(key=lambda row: row['seconds'])
    assert len(rows) == result['aligned_lag_trend']['samples'], 'amostras_divergentes'
    peak = max(rows, key=lambda row: row['lag'])
    assert abs(peak['lag']-result['aligned_lag_trend']['maximum_lag']) < .001, 'pico_divergente'
    windows = []
    duration = int(round(result['finish_epoch']-result['measured_at']))
    for start in range(0, duration, 30):
        values = [row['lag'] for row in rows if start <= row['seconds'] < start+30]
        if values:
            windows.append({'from_seconds': start, 'samples': len(values),
                            'min': min(values), 'median': statistics.median(values),
                            'max': max(values)})
    return {'peak': peak, 'last': rows[-1], 'windows_30s': windows}


def describe(base, name):
    root = base/name
    folder = root/'supervisor/capacity'/name
    state = load(folder/'status.json')
    assert state['status'] == 'completed' and state['resources_restored'], 'serie_incompleta'
    assert not state.get('probe_failures'), 'falha_coletor'
    memory = load(folder/'memory-summary.json')
    summary = load(folder/'summary.json')
    raw = lines(root/'data/results/capacity'/name/'memory.jsonl')
    assert raw and not memory['failures'], 'coleta_memoria'
    def counter(row, key):
        return int(next(line.split('\t')[1] for line in row['mysql_memory']
                        if line.startswith(key+'\t')))
    trials = []
    hashes = set()
    for item in sorted(summary['trials'], key=lambda item: item['result']['start_epoch']):
        result = item['result']
        assert result['accounting_passed'] and result['drained'] and not result['errors'], 'integridade'
        drain = load(folder/(result['name']+'-tracker-drain.json'))
        assert drain['exit_code'] == 0 and not drain['oom_killed'], 'drenagem'
        if 'binary_sha256' in drain:
            hashes.add(drain['binary_sha256'])
        trials.append({'name': result['name'], 'accepted': result['accepted'],
                       'expected_credit': result['expected_credit'], 'stable': result['stable'],
                       'completed_rps': result['completed_rps'], 'metrics': result['metrics'],
                       'aligned_lag_trend': result['aligned_lag_trend'],
                       'drain_seconds': result['drain_seconds'],
                       'resources': item['resources'], 'aligned': aligned_windows(root, result)})
    assert len(trials) == 9, 'rodadas_incompletas'
    return {'series': name, 'started_at': state['started_at'], 'finished_at': state['finished_at'],
            'accepted': sum(row['accepted'] for row in trials),
            'credit_bytes': sum(row['expected_credit'] for row in trials),
            'drain_binary_hashes': sorted(hashes),
            'memory_samples': len(raw), 'memory_ranges': memory['overall']['ranges'],
            'first_memory': memory['overall']['first'], 'before_restore': memory['before_restore'],
            'max_sample_gap_seconds': memory['max_sample_gap_seconds'],
            'mysql_pids': sorted({pid for row in raw for pid in row['mysql_process_detail']}),
            'instrument_configurations': sorted({line for row in raw for line in row['mysql_memory']
                                                if line.startswith('memory_instruments\t')}),
            'statement_command_deltas': {key: counter(raw[-1], key)-counter(raw[0], key)
                                         for key in ('Com_stmt_prepare', 'Com_stmt_close', 'Com_stmt_execute')},
            'trials': trials}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('collected_root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    names = ['capacity-memory-4g-v1', 'capacity-cache-b-v1', 'capacity-cache-a-repeat-v1']
    result = {'scope': 'A1/B/A2 do candidato dualstack 36823b5; não compara original 0.3.1',
              'series': {name: describe(args.collected_root, name) for name in names},
              'limits': ['host compartilhado, ordem sequencial sem randomização',
                         'atraso estimado por alinhamento temporal, não fila diretamente medida',
                         'p95/p99 por janela, nunca percentis globais combinados',
                         'IOPS do dispositivo da VM, não atribuição exclusiva do SSD físico',
                         'duas confirmações de 300 s não estabelecem teto sustentado']}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'series': len(result['series']),
                      'trials': sum(len(s['trials']) for s in result['series'].values())}))
