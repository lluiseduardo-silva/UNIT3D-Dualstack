#!/usr/bin/env python3
"""Resumo de uma execução coletada; percentis são medianas por janela."""
import json
from pathlib import Path
import statistics
import sys

root=Path(sys.argv[1])
status=json.loads((root/'supervisor/status.json').read_text())
final=json.loads((root/'clients/final.json').read_text())
windows=[json.loads(line) for line in (root/'clients/windows.jsonl').read_text().splitlines()]
comparison='comparison_variant' in status['plan']
if comparison:
    measured={p['window'] for p in final['phases'] if p['phase']=='measurement'}
    windows=[w for w in windows if w['window'] in measured]
result={'name':status['name'],'status':status['status'],'reason':status.get('reason'),
        'load':final,'windows':len(windows),'roles':{}}
if comparison:
    result['metric_scope']='measurement_only_excludes_warmup'
    result['backlog_unit']='estimated_100_byte_credit_steps_including_observer_delay'
if windows:
    result['completed_rps']={'min':min(w['completed_rps'] for w in windows),
                             'median':statistics.median(w['completed_rps'] for w in windows)}
    result['window_metrics_median']={key:{p:statistics.median(w['metrics'][key][p] for w in windows)
                                        for p in ('p95','p99')}
                                     for key in windows[0]['metrics']}
for role in ('tracker','data','clients'):
    summary={'samples':0,'failures':[],'processes':{}}
    with (root/role/'observer.jsonl').open() as source:
        for line in source:
            row=json.loads(line);summary['samples']+=1
            summary['failures']=sorted(set(summary['failures']+row['failures']))
            for field in ('ssd_free','archive_free','memory_available'):
                summary['min_'+field]=min(summary.get('min_'+field,row[field]),row[field])
            for field in ('archive_age','closed_binlog_bytes'):
                if field in row:summary['max_'+field]=max(summary.get('max_'+field,0),row[field])
            for pid,proc in row['processes'].items():
                if pid not in summary['processes']:
                    summary['processes'][pid]={'name':proc['name'],'first_pss':proc['pss'],'first_rss':proc['rss'],
                        'first_cpu_ticks':proc['cpu_ticks'],'first_at':row['at'],'max_pss':0,'max_rss':0}
                p=summary['processes'][pid]
                p.update(last_pss=proc['pss'],last_rss=proc['rss'],last_cpu_ticks=proc['cpu_ticks'],last_at=row['at'],
                         max_pss=max(p['max_pss'],proc['pss']),max_rss=max(p['max_rss'],proc['rss']))
    result['roles'][role]=summary
with (root/'supervisor/monitor.jsonl').open() as source:
    for line in source:
        row=json.loads(line)
        if 'thin_free' in row:result['min_thin_free']=min(result.get('min_thin_free',row['thin_free']),row['thin_free'])
        if 'observed_persistence_lag' in row:
            result['max_observed_persistence_lag']=max(result.get('max_observed_persistence_lag',0),row['observed_persistence_lag'])
print(json.dumps(result,indent=2))
