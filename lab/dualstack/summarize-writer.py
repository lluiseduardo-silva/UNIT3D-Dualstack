#!/usr/bin/env python3
"""Consolidar somente as series deste incremento; preservar o diagnostico anterior."""
from pathlib import Path
import hashlib
import json
import statistics

root=Path(__file__).parent/'results/throughput'
out=Path(__file__).parent/'results/writer'
series=sorted(root.glob('density-throughput-writer-*-analysis.json'))
assert series
reports=[]
audits=[]
for path in series:
    report=json.loads(path.read_text())
    audit=json.loads((root/(report['series']+'-audit.json')).read_text())
    assert audit['status']=='passed'
    for name,digest in audit['sha256'].items():
        assert hashlib.sha256((root/report['series']/name).read_bytes()).hexdigest()==digest
    audits.append(audit)
    grouped={}
    for phase in report['phases']:
        data=phase['io']['data']; disk=data['devices']['sda']
        item=dict(http_rps=phase['http_rps'],committed_rps=phase['writer']['committed_rps'],
            backlog_growth_rps=phase['writer']['backlog_per_second'],backlog_peak=phase['writer']['backlog_peak'],
            drain_s=phase['drain_seconds'],http_p95_ms=phase['response_ms']['p95'],http_p99_ms=phase['response_ms']['p99'],
            generator_queue_p99_ms=phase['generator_queue_ms']['p99'],
            batch_mean=phase['writer']['batch_mean'],batch_ms=phase['spans']['persist']['mean_us']/1000,
            endpoints_ms=phase['spans']['endpoints']['mean_us']/1000,
            writer_busy=phase['spans']['persist']['seconds_per_second'],
            rust_cpu_percent=phase['rust_cpu_percent']['mean'],
            publish_hold_us=phase['spans']['publish_hold']['mean_us'],
            publish_wait_us=phase['spans']['publish_wait']['mean_us'],
            select_hold_us=phase['spans']['select_hold']['mean_us'],
            select_wait_us=phase['spans']['select_wait']['mean_us'],
            mysql_cpu_percent=data['process_cpu_percent']['mysqld'],db_iowait_percent=data['cpu_iowait_percent'],
            db_write_mib_s=disk['write_mib_per_second'],db_write_iops=disk['write_iops'],
            redo_bytes_s=data['mysql_deltas']['Innodb_os_log_written']/data['observed_seconds'])
        assert phase['writer']['retries']==0
        grouped.setdefault(phase['rate'],[]).append(item)
    medians={rate:dict(repetitions=len(items),**{key:statistics.median(i[key] for i in items) for key in items[0]}) for rate,items in grouped.items()}
    reports.append(dict(series=report['series'],accepted=report['accepted'],rates=medians))
summary=dict(status='passed',status_scope='artifact hashes and final accounting; not a sustained capacity certification',
    accepted=sum(a['accepted'] for a in audits),
    measured_samples=sum(a['measured_samples'] for a in audits),phases=sum(a['phases'] for a in audits),
    series=reports)
by_name={r['series'].removeprefix('density-throughput-writer-'):r['rates'] for r in reports}
comparisons={}
for label,before,after,rate,metrics in [
    ('latency_at_4000','reference200-v1','endpoints200-v1',4000,
        ['http_p95_ms','http_p99_ms','committed_rps','drain_s']),
    ('io_at_8000','cadence500-v1','endpoints500-v1',8000,
        ['redo_bytes_s','db_write_mib_s','batch_ms','endpoints_ms','writer_busy']),
    ('ceiling_at_12000','cadence500-v1','endpoints500-v1',12000,
        ['committed_rps','backlog_growth_rps','redo_bytes_s','db_write_mib_s'])]:
    if before in by_name and after in by_name:
        comparisons[label]={key:dict(before=by_name[before][rate][key],after=by_name[after][rate][key],
            change_percent=100*(by_name[after][rate][key]/by_name[before][rate][key]-1)) for key in metrics}
summary['comparisons']=comparisons
out.mkdir(exist_ok=True)
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
