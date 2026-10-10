#!/usr/bin/env python3
"""Exportacao permitida apenas para resultados JSON e amostras numericas."""
import gzip
import json
import os
from pathlib import Path
import re
import socket
import tarfile

base = Path('/opt/unit3d-dualstack')
assert os.geteuid() == 0
hostname = socket.gethostname()
assert hostname in ['unit3d-ds-clients', 'unit3d-ds-tracker', 'unit3d-ds-data']
if hostname == 'unit3d-ds-clients':
    root = base/'benchmarks'
    files = sorted(p for p in root.iterdir() if re.fullmatch(r'(php|rust)-(original|legacy-fixed|candidate)-[0-9]{8}T[0-9]{6}(-samples)?\.json(\.gz)?', p.name))
    private = json.loads((base/'benchmark-fixture.json').read_text())
    forbidden = {lane['passkey'] for lane in private['lanes']}
else:
    root = base/'results/benchmarks'
    files = sorted(p for p in root.iterdir() if re.fullmatch(r'[a-z0-9-]+-unit3d-ds-(tracker|data)\.jsonl', p.name))
    forbidden = set()
for path in files:
    payload = gzip.decompress(path.read_bytes()).decode() if path.suffix == '.gz' else path.read_text()
    assert all(token not in payload.lower() for token in ['passkey', 'password', '/announce/'])
    assert not forbidden.intersection(re.findall(r'[a-f0-9]{32}', payload))
    if path.suffix == '.jsonl':
        for line in payload.splitlines():
            json.loads(line)
    else:
        json.loads(payload)
target = Path('/tmp/unit3d-benchmark-results.tgz')
with tarfile.open(target, 'w:gz') as archive:
    for path in files:
        archive.add(path, arcname=path.name, recursive=False)
target.chmod(0o644)
print(json.dumps({'exported_files': len(files), 'host': hostname, 'archive': str(target)}))
