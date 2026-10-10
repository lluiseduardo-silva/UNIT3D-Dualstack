#!/usr/bin/env python3
"""Direciona resultados ao ZFS, conservando uma cópia anterior no SSD."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

role = socket.gethostname().removeprefix('unit3d-ds-')
assert role in ('data', 'tracker', 'clients') and os.geteuid() == 0
os.umask(0o077)
root = Path('/mnt/unit3d-archive')
base = Path('/opt/unit3d-dualstack')
tag = 'unit3d-ds-' + role
assert subprocess.check_output(['findmnt', '-n', '-o', 'SOURCE,FSTYPE', '--mountpoint', str(root)], text=True).split() == [tag, 'virtiofs']
assert (root / '.unit3d-archive').read_text().strip() == tag


def hashes(directory):
    result = {}
    for p in sorted(directory.rglob('*')):
        assert not p.is_symlink(), 'unexpected link in existing artifacts'
        if p.is_file():
            h = hashlib.sha256()
            with p.open('rb') as f:
                while chunk := f.read(1048576):
                    h.update(chunk)
            result[str(p.relative_to(directory))] = h.hexdigest()
    return result


report = []
for name in (['results', 'density-results', 'benchmarks'] if role == 'clients' else ['results']):
    source = base / name
    destination = root / name
    backup = base / (name + '.before-zfs')
    if source.is_symlink():
        assert source.resolve() == destination
        continue
    if not source.exists() and backup.is_dir():
        assert hashes(backup) == hashes(destination)
        source.symlink_to(destination, target_is_directory=True)
        continue
    assert source.is_dir() and not backup.exists()
    before = hashes(source)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    assert hashes(destination) == before
    for p in destination.rglob('*'):
        if p.is_file():
            with p.open('rb') as f:
                os.fsync(f.fileno())
    for p in [p for p in destination.rglob('*') if p.is_dir()] + [destination, root]:
        fd = os.open(p, os.O_DIRECTORY)
        os.fsync(fd)
        os.close(fd)
    source.rename(backup)
    source.symlink_to(destination, target_is_directory=True)
    report.append({'directory': name, 'files_verified': len(before), 'backup': str(backup), 'destination': str(destination)})
print(json.dumps({'role': role, 'redirects': report}, indent=2))
