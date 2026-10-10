#!/usr/bin/env python3
"""Falhas controladas no arquivo real, com MySQL do laboratório ocioso."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess

spec = importlib.util.spec_from_file_location('archive', '/usr/local/sbin/unit3d-archive-binlogs.py')
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)
archive.verify_mount()
before = archive.inventory()
config = json.loads(archive.CONFIG.read_text())
file = archive.ROOT / 'binlogs' / config['server_uuid'] / before[0][0]
assert file.exists() and file.stat().st_size < 4 * 1024 * 1024, 'run before initial backlog purge'
command = ['python3', '/usr/local/sbin/unit3d-archive-binlogs.py', '--purge', '--max-files', '1']
results = []


def expect_failure(reason):
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and reason in result.stderr, result.stderr
    assert archive.inventory() == before, 'binlogs changed after a failure'
    results.append({'case': reason, 'exit_code': result.returncode, 'binlogs_unchanged': True})


with open('/run/lock/unit3d-binlog-archive.lock', 'w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    expect_failure('BlockingIOError')

subprocess.run(['umount', str(archive.ROOT)], check=True, timeout=15)
try:
    expect_failure('archive_not_mounted')
finally:
    subprocess.run(['mount', str(archive.ROOT)], check=True, timeout=15)
archive.verify_mount()

with file.open('r+b') as f:
    original = f.read(1)
    f.seek(0)
    f.write(bytes([original[0] ^ 0xff]))
    f.flush()
    os.fsync(f.fileno())
try:
    expect_failure('existing_archive_hash_mismatch')
finally:
    with file.open('r+b') as f:
        f.write(original)
        f.flush()
        os.fsync(f.fileno())
assert archive.digest(file) == archive.digest(archive.SOURCE / file.name)
# Real idempotence before enabling purge.
r = subprocess.run(command[:-3] + ['--max-files', '1'], capture_output=True, text=True, timeout=30)
assert r.returncode == 0, r.stderr
report = json.loads(r.stdout.splitlines()[-1])
assert report['files'][0]['copied_bytes'] == 0
assert archive.inventory() == before
results.append({'case': 'reentry', 'copied_bytes': 0, 'binlogs_unchanged': True})
print(json.dumps({'cases': results}, indent=2))
