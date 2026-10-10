#!/usr/bin/env python3
"""Troca atômica do módulo validado; preserva configuração e cópia anterior."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

assert socket.gethostname() == 'unit3d-ds-data' and os.geteuid() == 0
source = Path(sys.argv[1]).resolve()
assert source.is_file() and source.name == 'archive-binlogs.py'
target = Path('/usr/local/sbin/unit3d-archive-binlogs.py')
old = target.read_bytes()
new = source.read_bytes()
compile(new, str(source), 'exec')
backup = target.with_name(target.name + '.' + hashlib.sha256(old).hexdigest()[:12] + '.bak')
report = {'before_sha256': hashlib.sha256(old).hexdigest(), 'after_sha256': hashlib.sha256(new).hexdigest()}
subprocess.run(['systemctl', 'stop', 'unit3d-binlog-archive.timer'], check=True, timeout=15)
try:
    deadline = time.monotonic() + 180
    while subprocess.check_output(['systemctl', 'show', '--value', '-p', 'ActiveState',
                                   'unit3d-binlog-archive.service'], text=True, timeout=5).strip() in (
                                       'activating', 'active', 'deactivating', 'reloading'):
        assert time.monotonic() < deadline, 'archiver_drain_timeout'
        time.sleep(1)
    if not backup.exists():
        backup.write_bytes(old)
        backup.chmod(0o700)
    else:
        assert backup.read_bytes() == old, 'backup_mismatch'
    temporary = target.with_suffix('.new')
    with temporary.open('wb') as output:
        output.write(new)
        output.flush()
        os.fchmod(output.fileno(), 0o700)
        os.fsync(output.fileno())
    os.replace(temporary, target)
    descriptor = os.open(target.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    # Only the verified archiver may purge; this also drains tiny test rotations.
    result = subprocess.run(['python3', str(target), '--purge', '--max-files', '64', '--mib-per-second', '32'],
                            capture_output=True, text=True, timeout=180, check=True)
    report['archive'] = json.loads(result.stdout.splitlines()[-1])
    # Refresh the service result as well as its metadata after the module swap.
    subprocess.run(['systemctl', 'start', 'unit3d-binlog-archive.service'], check=True, timeout=180)
finally:
    subprocess.run(['systemctl', 'start', 'unit3d-binlog-archive.timer'], check=True, timeout=15)
report['status'] = 'installed_and_drained'
print(json.dumps(report, indent=2))
