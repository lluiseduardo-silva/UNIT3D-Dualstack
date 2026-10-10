#!/usr/bin/env python3
"""Dois milhões de amostras sintéticas: precisão e RAM, sem tráfego no tracker."""
import json
from pathlib import Path
import resource
import time

from soak_metrics import Metrics,Samples

folder=Path('/mnt/unit3d-archive/results/soak-collector-check-v2')
folder.mkdir(exist_ok=False)
samples=Samples(folder/'samples')
memory=[];start=time.monotonic();metrics=Metrics()
for i in range(2000000):
    if i%100==0:
        time.sleep(max(0,start+i/20000-time.monotonic()))
    scheduled=i/8000;began=scheduled+.0001;received=began+.0002;ended=received+.00002
    metrics.add(scheduled,began,received,ended)
    samples.add(i%10000,4 if i%2 else 6,0,i,scheduled,began,received,ended,240,True)
    if (i+1)%100000==0:
        samples.segment()
        memory.append({'samples':i+1,'rss_peak_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
        metrics=Metrics()
samples.close()
assert memory[-1]['rss_peak_kib']-memory[0]['rss_peak_kib']<16*1024,'collector_memory_growth'
report={'samples':samples.count,'elapsed_seconds':time.monotonic()-start,'memory':memory,
        'peak_queue_blocks':samples.peak_queue,'status':'passed'}
(folder/'result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
