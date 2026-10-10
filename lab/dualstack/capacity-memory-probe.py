#!/usr/bin/env python3
"""Alocações agregadas do MySQL; nenhum texto SQL ou identidade é exportado."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


SQL = """
SHOW GLOBAL STATUS WHERE Variable_name IN ('Uptime','Prepared_stmt_count','Threads_connected','Threads_created','Threads_cached','Com_stmt_prepare','Com_stmt_close','Com_stmt_execute','Performance_schema_prepared_statements_lost');
SELECT 'memory_total',SUM(CURRENT_NUMBER_OF_BYTES_USED) FROM performance_schema.memory_summary_global_by_event_name;
SELECT 'memory_group',SUBSTRING_INDEX(EVENT_NAME,'/',2),SUM(CURRENT_NUMBER_OF_BYTES_USED) FROM performance_schema.memory_summary_global_by_event_name GROUP BY SUBSTRING_INDEX(EVENT_NAME,'/',2);
SELECT 'memory_top',EVENT_NAME,CURRENT_NUMBER_OF_BYTES_USED,HIGH_NUMBER_OF_BYTES_USED FROM performance_schema.memory_summary_global_by_event_name WHERE CURRENT_NUMBER_OF_BYTES_USED>1048576 ORDER BY CURRENT_NUMBER_OF_BYTES_USED DESC LIMIT 40;
SELECT 'memory_sql',EVENT_NAME,CURRENT_NUMBER_OF_BYTES_USED,HIGH_NUMBER_OF_BYTES_USED FROM performance_schema.memory_summary_global_by_event_name WHERE EVENT_NAME LIKE 'memory/sql/%' AND (EVENT_NAME LIKE '%stmt%' OR EVENT_NAME LIKE '%Prepared%' OR EVENT_NAME LIKE '%MEM_ROOT%');
SELECT 'prepared_aggregate',COUNT(*),COALESCE(SUM(OCTET_LENGTH(SQL_TEXT)),0),COALESCE(MAX(OCTET_LENGTH(SQL_TEXT)),0) FROM performance_schema.prepared_statements_instances;
SELECT 'memory_instruments',COUNT(*),SUM(ENABLED='YES') FROM performance_schema.setup_instruments WHERE NAME LIKE 'memory/%';
"""


def sample(admin, observer):
    row = observer.system()
    wanted = ('MemTotal','MemAvailable','MemFree','Cached','Buffers','AnonPages','SReclaimable','SUnreclaim','PageTables','Dirty','Writeback','SwapTotal')
    row['memory_detail'] = {f[0].rstrip(':'): int(f[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if (f := line.split())[0].rstrip(':') in wanted}
    row['mysql_process_detail'] = {}
    for pid, proc in row['processes'].items():
        if proc['name'] != 'mysqld':
            continue
        fields = {}
        for line in Path('/proc', pid, 'status').read_text().splitlines():
            key, _, val = line.partition(':')
            if key in ('VmRSS','RssAnon','RssFile','RssShmem','VmSwap'):
                fields[key] = int(val.split()[0])*1024
        row['mysql_process_detail'][pid] = fields
    row['sql_start'] = time.time()
    row['mysql_memory'] = admin.mysql(SQL, 8).splitlines()
    row['sql_end'] = time.time()
    row['failures'] = []
    if row['memory']['MemAvailable'] < 256*1024**2:
        row['failures'].append('memory_low')
    if row['ssd_free'] < 8*1024**3:
        row['failures'].append('ssd_low')
    return row


def preserve(admin):
    target = Path('/opt/unit3d-dualstack/private/capacity-cpu-ram-v2.sql')
    assert not target.exists(), 'copia_ja_existe'
    assert admin.mysql(f'SELECT COUNT(*),SUM(state_version),SUM(uploaded) FROM {admin.DB}.peers') == '10000\t38646\t1932800', 'estado_v2_divergente'
    assert admin.mysql(f'SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM {admin.DB}.tracker_ownership WHERE id=1') == '0'
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with target.open('xb') as out:
        os.chmod(target, 0o600)
        r = subprocess.run(['docker','exec','unit3d-ds-mysql','sh','-c',
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --skip-lock-tables --set-gtid-purged=OFF '+admin.DB], stdout=out, stderr=subprocess.PIPE, timeout=90)
    assert r.returncode == 0 and target.stat().st_size > 0, 'copia_incompleta'
    print(json.dumps({'preserved_locally': True, 'bytes': target.stat().st_size,
                      'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'exported': False}))


def main(args):
    assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-data'
    os.umask(0o077)
    admin = module('memory_admin', 'capacity-admin.py')
    if args.preserve_previous:
        preserve(admin)
        return
    observer = module('memory_observer', 'capacity-observer.py')
    if args.once:
        print(json.dumps(sample(admin, observer)))
        return
    assert args.name and args.name.replace('-', '').isalnum()
    folder = Path('/mnt/unit3d-archive/results/capacity')/args.name
    folder.mkdir(parents=True, exist_ok=True)
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    with (folder/'memory.jsonl').open('x') as out:
        while not stopped:
            began = time.monotonic()
            try:
                row = sample(admin, observer)
            except Exception as exc:
                row = {'at': time.time(), 'failures': [type(exc).__name__]}
            out.write(json.dumps(row)+'\n'); out.flush()
            temp = folder/'memory.partial'; temp.write_text(json.dumps(row))
            os.replace(temp, folder/'memory.json')
            if row['failures']:
                break
            time.sleep(max(0, 5-(time.monotonic()-began)))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('name', nargs='?')
    p.add_argument('--once', action='store_true')
    p.add_argument('--preserve-previous', action='store_true')
    main(p.parse_args())
