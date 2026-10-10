#!/usr/bin/env python3
"""Resume alocações públicas e auditorias do diagnóstico, sem inferir causalidade."""
import argparse
import json
from pathlib import Path
import statistics


def load(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def flatten(row):
    if row.get('failures'):
        return {'at': row['at'], 'failures': row['failures']}
    procs = [v for v in row['processes'].values() if v['name'] == 'mysqld']
    assert len(procs) == 1, 'mysql_process_count'
    p = procs[0]
    flat = {'at': row['at'], 'rss_mib': p['rss']/2**20, 'pss_mib': p['pss']/2**20,
            'available_mib': row['memory']['MemAvailable']/2**20,
            'sql_ms': (row['sql_end']-row['sql_start'])*1000,
            'vm_cached_mib': row['memory_detail']['Cached']/2**20,
            'vm_anon_mib': row['memory_detail']['AnonPages']/2**20}
    for detail in row['mysql_process_detail'].values():
        flat['mysql_anon_mib'] = detail['RssAnon']/2**20
        flat['mysql_file_mib'] = detail['RssFile']/2**20
    for line in row['mysql_memory']:
        f = line.split('\t')
        if f[0] == 'memory_total': flat['instrumented_mib'] = int(f[1])/2**20
        elif f[0] == 'memory_group': flat[f[1]+'_mib'] = int(f[2])/2**20
        elif f[0] == 'prepared_aggregate':
            flat.update(prepared_instrumented_count=int(f[1]), prepared_sql_text_bytes=int(f[2]))
        elif f[0] == 'memory_sql' and f[1] == 'memory/sql/Prepared_statement::main_mem_root':
            flat['prepared_mem_root_mib'] = int(f[2])/2**20
        elif f[0] in ('Prepared_stmt_count','Threads_connected','Com_stmt_prepare','Com_stmt_close',
                       'Performance_schema_prepared_statements_lost'):
            flat[f[0]] = int(f[1])
    return flat


def describe(rows):
    valid = [r for r in rows if not r.get('failures')]
    if not valid: return {'samples': 0}
    fields = set.intersection(*(set(r) for r in valid)) - {'at'}
    return {'samples': len(valid), 'first': valid[0], 'last': valid[-1],
            'ranges': {k: {'min': min(r[k] for r in valid), 'max': max(r[k] for r in valid),
                           'median': statistics.median(r[k] for r in valid)} for k in sorted(fields)}}


def summarize(root, series):
    folder = root/'supervisor/capacity'/series
    state = load(folder/'status.json')
    raw = lines(root/'data/results/capacity'/series/'memory.jsonl')
    rows = [flatten(r) for r in raw]
    events = lines(folder/'events.jsonl')
    results = []
    for path in sorted(folder.glob('*-result.json')):
        result = load(path); name = result['name']
        drain = load(folder/(name+'-tracker-drain.json'))
        start = next(e['at'] for e in events if e['trial'] == name and e['phase'] == 'before_reset_and_start')
        end = next((e['at'] for e in events if e['trial'] == name and e['phase'] == 'after_tracker_stop'), None)
        results.append({'trial': name, 'start': start, 'result': result, 'tracker_drain': drain,
                        'reset_bootstrap': describe([r for r in rows if start <= r['at'] < result['start_epoch']]),
                        'load': describe([r for r in rows if result['start_epoch'] <= r['at'] < result['finish_epoch']]),
                        'after_stop': describe([r for r in rows if end is not None and end <= r['at'] < end+10])})
    results.sort(key=lambda r: r['start'])
    gaps = [b['at']-a['at'] for a,b in zip(rows,rows[1:])]
    output = {'series': series, 'status': state, 'overall': describe(rows), 'trials': results,
              'max_sample_gap_seconds': max(gaps, default=0),
              'failures': [r for r in rows if r.get('failures')],
              'before_restore': flatten(load(folder/'probe-before-restore.json')),
              'limits': ['memória instrumentada não equivale a RSS',
                         'picos entre amostras de cinco segundos podem não ser capturados',
                         'intervalo reset/bootstrap agrega duas operações',
                         'alocação liberada sem queda de RSS sugere retenção, não prova vazamento',
                         'nenhum teto sustentado é aprovado por este resumo']}
    (folder/'memory-summary.json').write_text(json.dumps(output, indent=2, ensure_ascii=False)+'\n')
    return {'series': series, 'trials': len(results), 'samples': len(rows),
            'failures': len(output['failures']), 'path': str(folder/'memory-summary.json')}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('root', type=Path); p.add_argument('series')
    a = p.parse_args(); print(json.dumps(summarize(a.root, a.series)))
