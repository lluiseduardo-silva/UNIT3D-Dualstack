#!/usr/bin/env python3
"""Preflight de armazenamento. Não inicia carga nem garante a prontidão do gerador."""
import json
import os
from pathlib import Path
import socket
import subprocess

role = socket.gethostname().removeprefix('unit3d-ds-')
assert role in ('data', 'tracker', 'clients') and os.geteuid() == 0
root = Path('/mnt/unit3d-archive')
tag = 'unit3d-ds-' + role
mount = subprocess.check_output(['findmnt', '-n', '-o', 'SOURCE,FSTYPE', '--mountpoint', str(root)], text=True).split()
assert mount == [tag, 'virtiofs'], 'archive_mount_required'
assert (root / '.unit3d-archive').read_text().strip() == tag
assert (Path('/opt/unit3d-dualstack/results')).resolve() == root / 'results'
ssd = os.statvfs('/')
zfs = os.statvfs(root)
ssd_free = ssd.f_bavail * ssd.f_frsize
zfs_free = zfs.f_bavail * zfs.f_frsize
assert zfs_free >= 200 * 1024**3, 'archive_requires_200_gib_free'
assert ssd_free >= (20 if role == 'data' else 2) * 1024**3, 'ssd_below_start_margin'
if role == 'data':
    assert subprocess.run(['systemctl', 'is-active', '--quiet', 'unit3d-binlog-archive.timer']).returncode == 0
    assert subprocess.run(['systemctl', 'is-failed', '--quiet', 'unit3d-binlog-archive.service']).returncode != 0
    status = json.loads((root / 'archive-status.json').read_text())
    import time
    assert time.time() - status['time'] < 240, 'archive_status_stale'
    assert status['remaining_closed_bytes'] < 2 * 1024**3, 'archive_backlog_not_drained'
print(json.dumps({'role': role, 'mount': str(root), 'free_ssd_bytes': ssd_free,
                  'free_archive_bytes': zfs_free, 'storage_preflight': 'passed',
                  'six_hour_test_started': False}))
