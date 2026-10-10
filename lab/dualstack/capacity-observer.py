#!/usr/bin/env python3
"""Telemetria agregada de capacidade, sem textos SQL, URLs ou parâmetros privados."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import importlib.util

def load_admin():
    spec=importlib.util.spec_from_file_location('capacity_admin',Path(__file__).with_name('capacity-admin.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def system():
    p=Path('/proc')
    row={'at':time.time(),'cpu':list(map(int,(p/'stat').read_text().splitlines()[0].split()[1:])),
         'cpu_count':os.cpu_count(),'clk_tck':os.sysconf('SC_CLK_TCK'),
         'memory':{line.split(':')[0]:int(line.split()[1])*1024 for line in (p/'meminfo').read_text().splitlines() if line.startswith(('MemAvailable:','MemTotal:','SwapFree:'))},
         'pressure':{x:(p/'pressure'/x).read_text().strip() for x in ('cpu','memory','io')},
         'disks':{},'processes':{}}
    for line in (p/'diskstats').read_text().splitlines():
        f=line.split()
        if f[2] in ('sda','nvme0n1') or f[2].startswith('dm-'):row['disks'][f[2]]=list(map(int,f[3:]))
    for path in p.glob('[0-9]*'):
        try:
            name=(path/'comm').read_text().strip()
            if name not in ('mysqld','unit3d-announce','python3'):continue
            s=(path/'stat').read_text().rsplit(')',1)[1].split()
            v={'name':name,'cpu_ticks':int(s[11])+int(s[12]),'rss':int(s[21])*os.sysconf('SC_PAGE_SIZE'),'major_faults':int(s[9])}
            if name!='python3':
                v['pss']=next(int(line.split()[1])*1024 for line in (path/'smaps_rollup').read_text().splitlines() if line.startswith('Pss:'))
                v['threads']={t.name:sum(map(int,(t/'stat').read_text().rsplit(')',1)[1].split()[11:13])) for t in (path/'task').iterdir()}
            row['processes'][path.name]=v
        except (OSError,ValueError):pass
    v=os.statvfs('/');row['ssd_free']=v.f_bavail*v.f_frsize
    if socket.gethostname()=='proxmox':
        row['guest_io']={}
        for group in Path('/sys/fs/cgroup/qemu.slice').glob('*.scope'):
            try:row['guest_io'][group.name]=(group/'io.stat').read_text().splitlines()
            except OSError:pass
    return row


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('name');args=parser.parse_args()
    assert args.name.replace('-','').isalnum() and os.geteuid()==0
    role=socket.gethostname().removeprefix('unit3d-ds-')
    assert role in ('tracker','data','clients','proxmox')
    folder=(Path('/storage_pool/unit3d-dualstack/supervisor') if role=='proxmox' else Path('/mnt/unit3d-archive/results'))/'capacity'/args.name
    folder.mkdir(parents=True,exist_ok=True)
    stop=False
    def stopped(*_):
        global stop
        stop=True
    signal.signal(signal.SIGTERM,stopped)
    admin=load_admin() if role=='data' else None
    with (folder/(role+'-observer.jsonl')).open('x') as out:
        while not stop:
            began=time.monotonic();row=system();row['role']=role
            try:
                if admin:
                    row['sql_start']=time.time()
                    row['mysql']=admin.mysql(f"""SELECT 'persisted',SUM(state_version),SUM(uploaded) FROM {admin.DB}.peers;
SHOW GLOBAL STATUS WHERE Variable_name IN ('Innodb_buffer_pool_read_requests','Innodb_buffer_pool_reads','Innodb_buffer_pool_pages_dirty','Innodb_buffer_pool_wait_free','Innodb_data_reads','Innodb_data_writes','Innodb_data_fsyncs','Innodb_os_log_written','Innodb_log_waits','Innodb_redo_log_current_lsn','Innodb_redo_log_checkpoint_lsn','Innodb_row_lock_waits','Innodb_row_lock_time','Threads_running');
SELECT EVENT_NAME,COUNT_STAR,SUM_TIMER_WAIT,COUNT_READ,SUM_NUMBER_OF_BYTES_READ,COUNT_WRITE,SUM_NUMBER_OF_BYTES_WRITE FROM performance_schema.file_summary_by_event_name WHERE EVENT_NAME LIKE 'wait/io/file/innodb/%' OR EVENT_NAME LIKE 'wait/io/file/sql/binlog%';
SELECT EVENT_NAME,COUNT_STAR,SUM_TIMER_WAIT,SUM_LOCK_TIME FROM performance_schema.events_statements_summary_global_by_event_name WHERE EVENT_NAME IN ('statement/sql/insert','statement/sql/update','statement/sql/delete','statement/sql/commit');
""",8).splitlines()
                    row['sql_end']=time.time()
                row['failures']=[]
                if row['memory']['MemAvailable']<256*1024**2:row['failures'].append('memory_low')
                if row['ssd_free']<(8 if role=='data' else 2)*1024**3:row['failures'].append('ssd_low')
            except Exception as e:row['failures']=[type(e).__name__]
            out.write(json.dumps(row)+'\n');out.flush()
            temp=folder/(role+'-observer.partial');temp.write_text(json.dumps(row));os.replace(temp,folder/(role+'-observer.json'))
            if row['failures']:break
            time.sleep(max(0,2-(time.monotonic()-began)))
