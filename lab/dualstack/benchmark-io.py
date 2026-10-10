#!/usr/bin/env python3
"""Metricas de I/O por dispositivo; captura somente contadores publicos."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time


def system():
    devices = {}
    for path in Path('/sys/block').iterdir():
        if path.name.startswith(('sd', 'vd', 'nvme')):
            devices[path.name] = [int(v) for v in (path/'stat').read_text().split()]
    pressure = {line.split()[0]: {k: float(v) for k, v in (field.split('=') for field in line.split()[1:])}
                for line in Path('/proc/pressure/io').read_text().splitlines()}
    processes = {}
    for path in Path('/proc').glob('[0-9]*'):
        try:
            name=(path/'comm').read_text().strip()
            if name not in ['mysqld', 'redis-server']:
                continue
            stat=(path/'stat').read_text().rsplit(')',1)[1].split()
            processes[path.name]=dict(name=name, cpu_ticks=int(stat[11])+int(stat[12]), rss_pages=int(stat[21]))
            if name == 'mysqld':
                threads={}
                for task in (path/'task').iterdir():
                    try:
                        fields=(task/'stat').read_text().rsplit(')',1)[1].split()
                        threads[task.name]=dict(name=(task/'comm').read_text().strip(),cpu_ticks=int(fields[11])+int(fields[12]))
                    except (FileNotFoundError, ProcessLookupError):
                        pass
                processes[path.name]['threads']=threads
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    filesystem=os.statvfs('/')
    return dict(at=time.time(), diskstats=devices, io_pressure=pressure, processes=processes,
                filesystem_free_bytes=filesystem.f_bavail*filesystem.f_frsize,
                cpu_ticks=[int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:]])


def database():
    # O shell expande somente a variavel ja presente no container. Nenhum segredo
    # e passado em argv nem impresso. Contadores, sem SQL de usuarios ou caminhos.
    sql = """SHOW GLOBAL STATUS WHERE Variable_name IN
      ('Innodb_data_fsyncs','Innodb_data_pending_fsyncs','Innodb_data_pending_reads',
       'Innodb_data_pending_writes','Innodb_log_waits','Innodb_log_write_requests',
       'Innodb_log_writes','Innodb_os_log_written','Innodb_buffer_pool_wait_free',
       'Innodb_buffer_pool_read_requests','Innodb_buffer_pool_reads','Threads_running',
       'Innodb_row_lock_waits','Innodb_row_lock_time','Innodb_deadlocks');
      SELECT EVENT_NAME,COUNT_STAR,SUM_TIMER_WAIT,COUNT_READ,SUM_TIMER_READ,
        COUNT_WRITE,SUM_TIMER_WRITE,COUNT_MISC,SUM_TIMER_MISC
      FROM performance_schema.file_summary_by_event_name
      WHERE EVENT_NAME LIKE 'wait/io/file/innodb/%' OR EVENT_NAME LIKE 'wait/io/file/sql/binlog%';
      SELECT EVENT_NAME,COUNT_STAR,SUM_TIMER_WAIT,SUM_LOCK_TIME
      FROM performance_schema.events_statements_summary_global_by_event_name
      WHERE EVENT_NAME IN ('statement/sql/select','statement/sql/update',
        'statement/sql/insert','statement/sql/delete','statement/sql/commit',
        'statement/com/Execute','statement/com/Prepare');"""
    result = subprocess.run(['docker', 'exec', '-i', 'unit3d-ds-mysql', 'sh', '-c',
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --skip-column-names'],
        input=sql, text=True, capture_output=True, timeout=10)
    if result.returncode:
        return dict(error='mysql_observer_failed', code=result.returncode)
    rows = [line.split('\t') for line in result.stdout.splitlines()]
    return dict(status={row[0]: int(row[1]) for row in rows if len(row) == 2},
                statements=[dict(event=row[0],count=int(row[1]),wait_ps=int(row[2]),lock_ps=int(row[3])) for row in rows if len(row)==4],
                file_waits=[dict(zip(['event', 'count', 'wait_ps', 'reads', 'read_ps',
                    'writes', 'write_ps', 'misc', 'misc_ps'], [row[0]]+[int(v) for v in row[1:]]))
                    for row in rows if len(row) == 9])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, required=True)
    parser.add_argument('--mysql', action='store_true')
    parser.add_argument('--stop-file', type=Path)
    args = parser.parse_args()
    assert not args.stop_file or (args.stop_file.parent == Path('/tmp') and args.stop_file.name.startswith('density-throughput-') and args.stop_file.suffix == '.stop')
    assert 1 <= args.seconds <= 22000
    host = socket.gethostname()
    assert host in ['proxmox', 'unit3d-ds-data', 'unit3d-ds-tracker']
    assert not args.mysql or host == 'unit3d-ds-data'
    started = time.monotonic()
    while time.monotonic()-started < args.seconds:
        if args.stop_file and args.stop_file.exists():
            break
        sample = system()
        sample['host'] = host
        if args.mysql:
            sample['mysql'] = database()
        print(json.dumps(sample), flush=True)
        time.sleep(min(2, max(0, args.seconds-(time.monotonic()-started))))
