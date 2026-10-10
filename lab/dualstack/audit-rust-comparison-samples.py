#!/usr/bin/env python3
"""Reproduzir contadores aceitos a partir do arquivo e conferir o MySQL antes do reset."""
import gzip
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys

assert os.geteuid()==0 and socket.gethostname()=='unit3d-ds-clients'
os.umask(0o077)
spec=importlib.util.spec_from_file_location('comparison',Path(__file__).with_name('rust-comparison-load.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
name=sys.argv[1];assert all(c.isalnum() or c=='-' for c in name)
obj=object.__new__(m.Comparison)
obj.plan=json.loads((m.soak.BASE/'soak'/(name+'.json')).read_text())
obj.fixture=json.loads((m.soak.BASE/'comparison-fixtures'/name/'density-fixture.json').read_text())
assert obj.fixture['name']==name
obj.lanes=obj.fixture['lanes'];obj.folder=m.soak.ROOT/name
final=json.loads((obj.folder/'final.json').read_text());assert final['status']=='passed'
for p in obj.lanes:p.update(observed=0,accepted=0)
rows=0
for segment in sorted((obj.folder/'samples').glob('*.gz')):
    with gzip.open(segment,'rb') as f:
        while block:=f.read(m.soak.RECORD.size*10000):
            for index,family,event,upload,scheduled,began,received,ended,size,ok in m.soak.RECORD.iter_unpack(block):
                obj.replay_sample(index,family,event,upload,ok);rows+=1
assert rows==final['accepted']==final['sample_count']
audit=obj.audit()
assert audit['credit']==final.get('main_accepted',rows)*100
result=dict(name=name,status='passed',records=rows,audit=audit,source='replay_of_accepted_samples_against_mysql')
m.soak.save(obj.folder/'sample-accounting-audit.json',result)
print(json.dumps(result))
