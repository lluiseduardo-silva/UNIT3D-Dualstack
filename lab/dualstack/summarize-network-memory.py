#!/usr/bin/env python3
"""Consolida apenas a matriz TLS/rotacao deste incremento, sem inferir capacidade."""
import json
from pathlib import Path

root = Path(__file__).resolve().parent/'results/tls-memory'


def read(name):
    return json.loads((root/name).read_text(encoding='utf-8-sig'))


def lines(name):
    return [json.loads(line) for line in (root/name).read_text(encoding='utf-8-sig').splitlines()]


summary = dict(tls={}, memory={}, throughput_tested=False, six_hours_tested=False)
for backend, tls_name, rotation_name, memory_name in [
    ('php','php-tls-v5.json','php-rotation-v2.json','php-memory-v2.jsonl'),
    ('rust','rust-tls-v1.json','rust-rotation-v1.json','rust-memory-v1.jsonl'),
]:
    tls, rotation, samples = read(tls_name), read(rotation_name), lines(memory_name)
    assert tls['status'] == rotation['status'] == 'passed'
    assert len(tls['steps']) == 19 and rotation['rotations'] == 2048
    assert rotation['aliases_remaining'] == 0
    assert len(rotation['final']['peer']) == 1 and len(rotation['final']['endpoints']) == 2
    assert rotation['final']['user'][0]['uploaded']-rotation['before']['user'][0]['uploaded'] == 2048
    summary['tls'][backend] = dict(status='passed',checks=len(tls['steps']),credit=tls['final']['user'][0]['uploaded'])
    active = [row for row in samples if rotation['batches'][0]['at'] <= row['at'] <= rotation['rotation_finished_at']]
    assert active
    processes = {}
    for name in active[0]['processes']:
        process = {}
        for metric in ['rss_kib','pss_kib']:
            values = [row['processes'][name][metric] for row in active]
            process[metric] = dict(first=values[0],last=values[-1],minimum=min(values),maximum=max(values),growth=values[-1]-values[0])
        processes[name] = process
    caches = [dict(at=row['at'],**row['cache']) for row in samples] if backend == 'php' else lines('rust-cache-v1.jsonl')
    assert all(0 <= row['entries'] <= 16 for row in caches)
    after = [row for row in caches if rotation['rotation_finished_at']+4 <= row['at'] < rotation['finished_at']]
    assert after
    summary['memory'][backend] = dict(status='passed',rotations=rotation['rotations'],maximum_request_rate=20,
        rotation_seconds=rotation['rotation_finished_at']-rotation['started_at'],
        processes_after_first_batch=processes, samples=len(samples),
        cache_entries_max=max(row['entries'] for row in caches),cache_idle_entries_min=min(row['entries'] for row in after),
        cache_idle_live_min=min(row['live'] for row in after),
        cache_idle_entries_max=max(row['entries'] for row in after),
        cache_idle_live_max=max(row['live'] for row in after),
        sample_started_at=samples[0]['at'],sample_finished_at=samples[-1]['at'])
    if backend == 'php':
        assert all(row['deadlines'] == row['entries'] for row in caches)
        summary['memory'][backend].update(cache_bytes_max=max(row['values_bytes']+row['expiry_bytes'] for row in caches),
            peer_json_bytes_min=min(row['peer_json_bytes'] for row in caches if row['peer_json_bytes']),
            peer_json_bytes_max=max(row['peer_json_bytes'] for row in caches),pending_max=max(row['pending'] for row in caches),pending_final=caches[-1]['pending'])
        assert caches[-1]['pending'] == 0
    else:
        assert max(row['in_flight'] for row in caches) <= 128
        summary['memory'][backend]['probes_in_flight_sampled_max'] = max(row['in_flight'] for row in caches)

control = read('rust-product-rotation.json')
assert control['status'] == 'passed' and control['rotations'] == 256 and control['aliases_remaining'] == 0
summary['rust_product_control'] = dict(status='passed',rotations=256,peer_count=len(control['final']['peer']),
    endpoint_count=len(control['final']['endpoints']),credit=control['final']['user'][0]['uploaded'])
auxiliary = read('php-auxiliary-rotation.json')
aux_samples = lines('php-auxiliary-memory.jsonl')
assert auxiliary['status'] == 'passed' and auxiliary['rotations'] == 512
assert auxiliary['aliases_remaining'] == 0 and auxiliary['final']['user'][0]['uploaded'] == 512
expired = [row['cache'] for row in aux_samples if auxiliary['rotation_finished_at']+123 <= row['at'] < auxiliary['finished_at']]
assert expired and min(row['default_keys'] for row in expired) == 0
assert all(row['cache']['entries'] <= 16 for row in aux_samples)
summary['php_auxiliary_cache'] = dict(status='passed',rotations=512,natural_rate_limiter_ttl_seconds=120,
    default_keys_before=aux_samples[0]['cache']['default_keys'],
    default_keys_max=max(row['cache']['default_keys'] for row in aux_samples),
    default_keys_after_expiry=min(row['default_keys'] for row in expired),
    default_keys_final=aux_samples[-1]['cache']['default_keys'],
    redis_used_memory_before=aux_samples[0]['cache']['redis_used_memory'],
    redis_used_memory_max=max(row['cache']['redis_used_memory'] for row in aux_samples),
    redis_used_memory_final=aux_samples[-1]['cache']['redis_used_memory'])
(root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
