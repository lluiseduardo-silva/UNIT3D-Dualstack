#!/usr/bin/env python3
"""Analisa o perfil original de seis horas a partir das evidências públicas."""
import json
from pathlib import Path
import statistics
import sys


root = Path(sys.argv[1])


def read(path):
    return json.loads((root / path).read_text(encoding='utf-8-sig'))


def lines(path):
    return [json.loads(line) for line in (root / path).read_text().splitlines()]


def process_summary(rows, pid):
    values = [(row['at'], row['processes'][pid]) for row in rows
              if pid in row['processes']]
    first, last = values[0], values[-1]
    return {
        'pid': pid,
        'samples': len(values),
        'rss_median_mib': statistics.median(p['rss'] for _, p in values) / 2**20,
        'rss_max_mib': max(p['rss'] for _, p in values) / 2**20,
        'rss_last_mib': last[1]['rss'] / 2**20,
        'pss_max_mib': max(p['pss'] for _, p in values) / 2**20,
        'cpu_one_core_percent': (last[1]['cpu_ticks'] - first[1]['cpu_ticks'])
        / (last[0] - first[0]),  # CLK_TCK=100 verificado nas três VMs.
    }


status = read('supervisor/status.json')
final = read('clients/final.json')
summary = read('summary.json')
integrity = read('sample-integrity.json')
audit = read('clients/sample-accounting-audit.json')
windows = [w for w in final['phases'] if w['phase'] == 'measurement']
assert status['plan']['comparison_variant'] == 'original'
assert status['status'] == final['status'] == audit['status'] == 'passed'
assert status['tracker_drain']['status'] == 'passed'
assert len(windows) == 72 and sum(w['seconds'] for w in windows) == 21600
assert [w['window'] for w in windows] == list(range(1, 73))
assert all(w['errors'] == 0 and w['accepted'] == 2400000 for w in windows)
assert sum(w['accepted'] for w in windows) == 172800000
assert final['main_accepted'] == 175200000 and final['maintenance_accepted'] == 146000
assert final['accepted'] == final['sample_count'] == audit['records'] == integrity['records'] == 175346000
assert integrity['sha256_crc_and_count'] == 'passed' and integrity['segments'] == 73
assert final['audit'] == audit['audit'] and audit['audit']['credit'] == 17520000000
assert audit['audit']['mismatches'] == 0 and final['errors'] == 0
assert final['mapped_ipv4_responses'] == final['main_accepted']
observers = {role: lines(role + '/observer.jsonl') for role in ('tracker', 'data', 'clients')}
assert all(not row['failures'] for rows in observers.values() for row in rows)
pids = {}
for role, name in [('tracker', 'unit3d-announce'), ('data', 'mysqld'), ('clients', 'python3')]:
    # No cliente, o gerador é o processo com maior consumo acumulado de CPU.
    candidates = {pid: p for pid, p in summary['roles'][role]['processes'].items() if p['name'] == name}
    pids[role] = max(candidates, key=lambda pid: candidates[pid]['last_cpu_ticks'] - candidates[pid]['first_cpu_ticks'])

monitor = lines('supervisor/monitor.jsonl')
lags = [row['observed_persistence_lag'] for row in monitor if 'observed_persistence_lag' in row]
hourly = []
for hour in range(6):
    group = windows[hour * 12:(hour + 1) * 12]
    begin, end = group[0]['at'] - group[0]['elapsed'], group[-1]['at']
    hourly.append({
        'hour': hour + 1, 'windows': len(group),
        'rps_min': min(w['completed_rps'] for w in group),
        'rps_median': statistics.median(w['completed_rps'] for w in group),
        'median_window_response_p95_ms': statistics.median(w['metrics']['response_ms']['p95'] for w in group),
        'median_window_response_p99_ms': statistics.median(w['metrics']['response_ms']['p99'] for w in group),
        'median_window_queue_p99_ms': statistics.median(w['metrics']['queue_ms']['p99'] for w in group),
        'max_observed_credit_lag': max(row['observed_persistence_lag'] for row in monitor
                                     if begin <= row['at'] <= end and 'observed_persistence_lag' in row),
        'processes': {role: process_summary([row for row in rows if begin <= row['at'] <= end], pids[role])
                      for role, rows in observers.items()},
    })

manifest = lines('clients/samples/manifest.jsonl')
result = {
    'name': status['name'], 'status': 'passed',
    'scope': 'sustentacao do Rust original neste perfil; comparacao com candidato e PHP pendentes',
    'load_started_at': status['load_started_at'], 'last_window_at': windows[-1]['at'],
    'finished_at': status['finished_at'], 'measured_seconds': 21600,
    'measured_main_accepted': 172800000, 'total_accepted': final['accepted'],
    'credit_bytes': audit['audit']['credit'], 'mismatches': 0,
    'tracker_drain': status['tracker_drain']['status'], 'accounting_drain_seconds': final['drain_seconds'],
    'completed_rps': summary['completed_rps'],
    'window_percentile_medians_ms': summary['window_metrics_median'],
    'percentile_scope': 'medianas de percentis por janela; nao sao percentis globais',
    'max_window_response_p99_ms': max(w['metrics']['response_ms']['p99'] for w in windows),
    'clock_ticks_per_second': 100,
    'cpu_scope': 'media entre amostras do processo; 100% = um nucleo; total inclui aquecimento',
    'processes': {role: process_summary(rows, pids[role]) for role, rows in observers.items()},
    'hourly': hourly,
    'backlog_estimated_credit_steps': {'max': max(lags), 'median': statistics.median(lags),
        'last': lags[-1], 'above_80000_samples': sum(v > 80000 for v in lags),
        'note': 'inclui defasagem da coleta; nao representa cardinalidade real das filas'},
    'storage': {
        'data_ssd_min_gib': summary['roles']['data']['min_ssd_free'] / 2**30,
        'thin_pool_min_gib': summary['min_thin_free'] / 2**30,
        'archive_min_gib': summary['roles']['data']['min_archive_free'] / 2**30,
        'archive_net_used_growth_bytes': observers['data'][0]['archive_free'] - observers['data'][-1]['archive_free'],
        'max_closed_binlog_bytes': summary['roles']['data']['max_closed_binlog_bytes'],
        'max_archive_age_seconds': summary['roles']['data']['max_archive_age'],
        'sample_segments': len(manifest), 'sample_compressed_bytes': sum(r['bytes'] for r in manifest),
        'mysql_restarts_max': max(r['mysql_restarts'] for r in observers['data']),
    },
    'payload': {'source_families': [4], 'mapped_ipv4_responses': final['mapped_ipv4_responses'],
                'main_compact_list_bytes': 180, 'renewal_compact_list_bytes': 0,
                'note': 'peers6 com IPv4 mapeado; sem IPv6 nativo; exclui envelope bencode'},
    'limitations': ['sem falha injetada, churn ou expiracao provocada',
                    'CPU por processo e latencia do cliente nao isolam gargalo de rede, host, disco ou Rust',
                    'peer_ips e fixture estatica; endpoints auditados nas colunas legadas'],
}
print(json.dumps(result, indent=2))
