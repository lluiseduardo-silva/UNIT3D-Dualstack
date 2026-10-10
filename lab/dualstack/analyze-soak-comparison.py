#!/usr/bin/env python3
"""Medians of the three paired windows; raw samples remain on ZFS."""
import json
from pathlib import Path
import statistics
import sys

root=Path(sys.argv[1])
windows=[json.loads(line) for line in (root/'clients/windows.jsonl').read_text().splitlines()]
assert len(windows)==6
groups={'control':windows[::2],'copy':windows[1::2]}
report={'runs':{},'ratios':{}}
for name,items in groups.items():
    report['runs'][name]=[{'window':i['window'],'rps':i['completed_rps'],
        'p95_ms':i['metrics']['response_ms']['p95'],'p99_ms':i['metrics']['response_ms']['p99'],
        'queue_p99_ms':i['metrics']['queue_ms']['p99']} for i in items]
for key in ('p95_ms','p99_ms','rps'):
    before=statistics.median(r[key] for r in report['runs']['control'])
    after=statistics.median(r[key] for r in report['runs']['copy'])
    report['ratios'][key]={'control':before,'copy':after,'ratio':after/before}
report['status']='passed' if report['ratios']['p95_ms']['ratio']<=1.1 and report['ratios']['p99_ms']['ratio']<=1.1 and report['ratios']['rps']['ratio']>=.95 else 'investigate'
print(json.dumps(report,indent=2))
