#!/usr/bin/env python3
"""Exporta somente relatorios numericos, amostras e recursos das series pedidas."""
import argparse
import gzip
import io
import json
import re
import socket
import tarfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('series', nargs='+')
args = parser.parse_args()
assert all(re.fullmatch(r'density-[a-z0-9-]+', s) for s in args.series)
host = socket.gethostname()
assert host in ['unit3d-ds-clients', 'unit3d-ds-tracker']
root = Path('/opt/unit3d-dualstack')
files = []
for series in args.series:
    if host.endswith('clients'):
        folder = root/'density-results'/series
        assert folder.is_dir()
        for path in sorted(folder.iterdir()):
            assert path.is_file() and not path.is_symlink()
            assert re.fullmatch(r'[a-z0-9-]+(?:-samples)?\.json(?:\.gz)?', path.name)
            files.append((path, series+'/'+path.name))
    else:
        path = root/'results'/'benchmarks'/(series+'-unit3d-ds-tracker.jsonl')
        assert path.is_file() and not path.is_symlink()
        files.append((path, path.name))
target = Path('/tmp/density-export-'+host+'.tar.gz')
with tarfile.open(target, 'w:gz') as archive:
    for path, name in files:
        raw = path.read_bytes()
        decoded = gzip.decompress(raw) if path.suffix == '.gz' else raw
        # Contrato destes relatorios: nao contem URLs, identidades ou credenciais.
        assert not re.search(rb'passkey|password|secret|/announce/|peer_id|info_hash', decoded, re.I)
        if path.suffix == '.jsonl':
            for line in decoded.splitlines():
                json.loads(line)
        else:
            json.loads(decoded)
        entry = tarfile.TarInfo(name)
        entry.size, entry.mode = len(raw), 0o644
        archive.addfile(entry, io.BytesIO(raw))
target.chmod(0o644)
print(json.dumps(dict(files=len(files), bytes=target.stat().st_size, archive=str(target))))
