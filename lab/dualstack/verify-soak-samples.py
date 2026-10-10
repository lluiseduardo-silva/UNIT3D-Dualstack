#!/usr/bin/env python3
"""Valida SHA-256, CRC gzip e cardinalidade com leitura limitada em memória."""
import gzip
import hashlib
import json
from pathlib import Path
import sys

name=sys.argv[1];assert all(c.isalnum() or c=='-' for c in name)
folder=Path('/storage_pool/unit3d-dualstack/clients/results/soak')/name
metadata=json.loads((folder/'sample-format.json').read_text())
rows=[json.loads(l) for l in (folder/'samples/manifest.jsonl').read_text().splitlines()]
count=0
for row in rows:
    path=folder/'samples'/row['file']
    assert path.parent==folder/'samples' and path.stat().st_size==row['bytes']
    h=hashlib.sha256()
    with path.open('rb') as f:
        while data:=f.read(1048576):h.update(data)
    assert h.hexdigest()==row['sha256']
    size=0
    with gzip.open(path,'rb') as f:
        while data:=f.read(1048576):size+=len(data)
    assert size==row['records']*metadata['record_bytes']
    count+=row['records']
final=json.loads((folder/'final.json').read_text())
assert count==final['accepted']==final['sample_count']
print(json.dumps({'name':name,'segments':len(rows),'records':count,'sha256_crc_and_count':'passed'}))
