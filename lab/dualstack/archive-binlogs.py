#!/usr/bin/env python3
"""Arquivo verificado dos binlogs do laboratório; só --purge remove via MySQL."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time

ROOT = Path('/mnt/unit3d-archive')
SOURCE = Path('/var/lib/docker/volumes/unit3d-ds-mysql/_data')
CONFIG = Path('/etc/unit3d-binlog-archive.json')
CHUNK = 1024 * 1024


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def mysql(sql, *, timeout=30):
    r = subprocess.run(['docker', 'exec', '-i', 'unit3d-ds-mysql', 'sh', '-c',
                        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --skip-column-names'],
                       input=sql, text=True, capture_output=True, timeout=timeout)
    require(r.returncode == 0, 'mysql_command_failed')
    return [line.split('\t') for line in r.stdout.splitlines()]


def verify_mount(root=ROOT):
    r = subprocess.run(['findmnt', '--json', '--mountpoint', str(root), '-o', 'SOURCE,FSTYPE,TARGET'],
                       capture_output=True, text=True, timeout=5)
    require(r.returncode == 0, 'archive_not_mounted')
    mount = json.loads(r.stdout)['filesystems'][0]
    require(mount == {'source': 'unit3d-ds-data', 'fstype': 'virtiofs', 'target': str(root)},
            'unexpected_archive_mount')
    require((root / '.unit3d-archive').read_text().strip() == 'unit3d-ds-data', 'wrong_archive_marker')


def sync_dir(path):
    fd = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while data := f.read(CHUNK):
            h.update(data)
    return h.hexdigest()


def write_json(path, data):
    tmp = path.with_name(path.name + '.partial')
    require(not tmp.is_symlink(), 'partial_symlink')
    with tmp.open('w') as f:
        json.dump(data, f, sort_keys=True)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    sync_dir(path.parent)


def copy_verified(src, dst, expected_size, mib_per_second=32):
    """Retomável após crash: nunca sobrescreve arquivo final divergente."""
    require(not src.is_symlink() and not dst.is_symlink(), 'symlink_rejected')
    before = src.stat()
    require(before.st_size == expected_size, 'source_size_changed')
    partial = dst.with_name(dst.name + '.partial')
    require(not partial.is_symlink(), 'partial_symlink')
    started = time.monotonic()
    h = hashlib.sha256()
    copied = 0
    if dst.exists():
        require(dst.stat().st_size == expected_size, 'existing_archive_size_mismatch')
        expected_hash = digest(src)
    else:
        with src.open('rb') as inp, partial.open('wb') as out:
            while data := inp.read(CHUNK):
                out.write(data)
                h.update(data)
                copied += len(data)
                delay = copied / (mib_per_second * CHUNK) - (time.monotonic() - started)
                if delay > 0:
                    time.sleep(delay)
            out.flush()
            os.fsync(out.fileno())
        require(copied == expected_size, 'copy_size_changed')
        expected_hash = h.hexdigest()
        require(digest(partial) == expected_hash, 'archive_hash_mismatch')
        os.replace(partial, dst)
        sync_dir(dst.parent)
    require(digest(dst) == expected_hash, 'existing_archive_hash_mismatch')
    after = src.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_ino, after.st_size, after.st_mtime_ns), 'source_changed')
    # Also sync recovered files from a previous interrupted invocation.
    with dst.open('rb') as f:
        os.fsync(f.fileno())
    sync_dir(dst.parent)
    return {'file': src.name, 'bytes': expected_size, 'sha256': expected_hash,
            'elapsed_seconds': round(time.monotonic() - started, 3), 'copied_bytes': copied}


def inventory():
    # Read-only inventory: rotation may occur between the two queries. Never
    # publish that inconsistent snapshot or weaken the active-file guard.
    deadline = time.monotonic() + 5

    def query(sql):
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'binlog_inventory_timeout')
        try:
            rows = mysql(sql, timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('binlog_inventory_timeout') from error
        require(time.monotonic() < deadline, 'binlog_inventory_timeout')
        return rows

    for attempt in range(3):
        logs = query('SHOW BINARY LOGS;')
        require(logs and all(re.fullmatch(r'binlog\.\d{6,}', row[0]) and row[2] == 'No' for row in logs),
                'unexpected_binlog_format_or_encryption')
        master = query('SHOW MASTER STATUS;')
        require(master and master[0], 'missing_active_binlog')
        if logs[-1][0] == master[0][0]:
            return [(row[0], int(row[1])) for row in logs]
        require(attempt < 2, 'rotation_during_inventory_retry_later')
        delay = .1 * (attempt + 1)
        require(deadline - time.monotonic() > delay, 'binlog_inventory_timeout')
        time.sleep(delay)


def server_guard(config):
    info = mysql('SELECT @@server_uuid,@@binlog_expire_logs_auto_purge,@@sync_binlog,@@innodb_flush_log_at_trx_commit;')[0]
    require(info[0] == config['server_uuid'], 'server_uuid_changed')
    require(info[1:] == ['0', '1', '1'], 'retention_or_durability_changed')
    require(not mysql('SHOW REPLICAS;'), 'replica_registered')
    require(mysql("SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE COMMAND LIKE 'Binlog Dump%';")[0][0] == '0',
            'replica_connected')
    require(mysql('SELECT COUNT(*) FROM performance_schema.replication_connection_configuration;')[0][0] == '0',
            'replication_configured')


def run(args):
    require(socket.gethostname() == 'unit3d-ds-data' and os.geteuid() == 0, 'lab_data_root_required')
    os.umask(0o077)
    # Held across I/O deliberately: this locks the maintenance task, never tracker state.
    with open('/run/lock/unit3d-binlog-archive.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify_mount()
        config = json.loads(CONFIG.read_text())
        require(config['exclusive_lab_no_replicas'] is True, 'exclusive_lab_required')
        server_guard(config)
        logs = inventory()
        directory = ROOT / 'binlogs' / config['server_uuid']
        require(not directory.is_symlink() and not directory.parent.is_symlink(), 'archive_symlink')
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        sync_dir(directory.parent)
        sync_dir(ROOT)
        report = {'time': time.time(), 'closed_files': len(logs) - 1,
                  'closed_bytes': sum(size for _, size in logs[:-1]), 'active': logs[-1][0],
                  'free_ssd_bytes': os.statvfs(SOURCE).f_bavail * os.statvfs(SOURCE).f_frsize,
                  'purge_enabled': args.purge, 'files': []}
        for index, (name, size) in enumerate(logs[:-1][:args.max_files]):
            verify_mount()
            free = os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize
            require(free >= size + CHUNK * 1024, 'archive_space_below_margin')
            entry = copy_verified(SOURCE / name, directory / name, size, args.mib_per_second)
            entry['server_uuid'] = config['server_uuid']
            write_json(directory / (name + '.json'), entry)
            if args.purge:
                verify_mount()
                server_guard(config)
                now = inventory()
                # Only a verified contiguous prefix of the current index may be removed.
                require(now[0] == (name, size) and len(now) > 1 and now[1][0] == logs[index + 1][0],
                        'binlog_index_changed')
                mysql("PURGE BINARY LOGS TO '" + now[1][0] + "';")
                require(name not in [n for n, _ in inventory()], 'purge_not_confirmed')
                entry['purged'] = True
            report['files'].append(entry)
            print(json.dumps(entry), flush=True)
        remaining = inventory()
        report['remaining_closed_bytes'] = sum(size for _, size in remaining[:-1])
        report['free_ssd_bytes_after'] = os.statvfs(SOURCE).f_bavail * os.statvfs(SOURCE).f_frsize
        write_json(ROOT / 'archive-status.json', report)
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--purge', action='store_true')
    parser.add_argument('--max-files', type=int, default=2)
    parser.add_argument('--mib-per-second', type=int, default=32)
    args = parser.parse_args()
    require(1 <= args.max_files <= 64 and 1 <= args.mib_per_second <= 256, 'invalid_copy_limits')
    run(args)
