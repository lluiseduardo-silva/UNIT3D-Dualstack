#!/usr/bin/env python3
"""Observa I/O por dispositivo e cadeia de locks, sem texto SQL privado."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import time

DB='unit3d_dualstack_probe_20261009'
p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('--seconds',type=int,required=True);p.add_argument('--interval',type=float,default=1)
p.add_argument('--database',choices=(DB,'unit3d_dualstack_recovery_test'),default=DB)
args=p.parse_args();DB=args.database;host=socket.gethostname()
assert host in ('proxmox','unit3d-ds-data') and os.geteuid()==0
assert args.name.replace('-','').isalnum() and 1<=args.seconds<=240 and .2<=args.interval<=2
os.umask(0o077)
base=Path('/storage_pool/unit3d-dualstack/supervisor') if host=='proxmox' else Path('/mnt/unit3d-archive/results')
folder=base/'lease-probe'/args.name;folder.mkdir(parents=True,exist_ok=True)
path=folder/('host.jsonl' if host=='proxmox' else 'data.jsonl');assert not path.exists()
if host=='unit3d-ds-data':
    spec=importlib.util.spec_from_file_location('a','/usr/local/sbin/unit3d-archive-binlogs.py')
    a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)


def system():
    disks={}
    for line in Path('/proc/diskstats').read_text().splitlines():
        fields=line.split();name=fields[2]
        if name.startswith(('nvme','sd','vd','dm-')):
            disks[name]={'device':fields[0]+':'+fields[1],'stat':list(map(int,fields[3:]))}
    pressure={k:Path('/proc/pressure/'+k).read_text().strip() for k in ('io','cpu','memory')}
    groups={}
    if host=='proxmox':
        for pattern in ('lxc/*/io.stat','lxc/*/ns/io.stat','qemu.slice/*.scope/io.stat'):
            for file in Path('/sys/fs/cgroup').glob(pattern):
                try:groups[str(file.relative_to('/sys/fs/cgroup'))]=file.read_text().strip()
                except FileNotFoundError:pass
    memory={x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith(('MemAvailable:','SwapFree:'))}
    free=os.statvfs('/');archive=os.statvfs(folder)
    return {'at':time.time(),'disks':disks,'pressure':pressure,'groups':groups,'memory':memory,
            'cpu':list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:])),
            'ssd_free':free.f_bavail*free.f_frsize,'archive_free':archive.f_bavail*archive.f_frsize}


def database():
    sql=f"""SELECT 'counts',SUM(state_version),SUM(uploaded) FROM {DB}.peers;
SELECT 'lease',COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0),TIMESTAMPDIFF(MICROSECOND,UTC_TIMESTAMP(3),lease_expires_at) FROM {DB}.tracker_ownership WHERE id=1;
SELECT 'lock',r.OBJECT_NAME,r.LOCK_MODE,b.OBJECT_NAME,b.LOCK_MODE,rt.PROCESSLIST_ID,bt.PROCESSLIST_ID
FROM performance_schema.data_lock_waits w JOIN performance_schema.data_locks r ON r.ENGINE_LOCK_ID=w.REQUESTING_ENGINE_LOCK_ID AND r.ENGINE=w.ENGINE
JOIN performance_schema.data_locks b ON b.ENGINE_LOCK_ID=w.BLOCKING_ENGINE_LOCK_ID AND b.ENGINE=w.ENGINE
LEFT JOIN performance_schema.threads rt ON rt.THREAD_ID=r.THREAD_ID LEFT JOIN performance_schema.threads bt ON bt.THREAD_ID=b.THREAD_ID
WHERE r.OBJECT_SCHEMA='{DB}';
SHOW GLOBAL STATUS WHERE Variable_name IN ('Innodb_data_pending_fsyncs','Innodb_data_pending_writes','Innodb_log_waits','Innodb_os_log_written','Innodb_buffer_pool_wait_free','Innodb_row_lock_waits','Innodb_row_lock_time','Innodb_row_lock_time_max','Threads_running','Innodb_redo_log_current_lsn','Innodb_redo_log_checkpoint_lsn');
SELECT EVENT_NAME,COUNT_STAR,SUM_TIMER_WAIT,MAX_TIMER_WAIT FROM performance_schema.file_summary_by_event_name WHERE EVENT_NAME LIKE 'wait/io/file/innodb/%' OR EVENT_NAME LIKE 'wait/io/file/sql/binlog%';
SELECT 'statement',t.PROCESSLIST_ID,s.EVENT_NAME,s.TIMER_WAIT,s.LOCK_TIME,CASE WHEN s.SQL_TEXT LIKE '%tracker_ownership%' THEN 'ownership' ELSE 'other_or_prepared' END FROM performance_schema.events_statements_current s JOIN performance_schema.threads t USING(THREAD_ID) WHERE t.PROCESSLIST_DB='{DB}' AND t.PROCESSLIST_COMMAND<>'Sleep';"""
    started=time.time();rows=a.mysql(sql,timeout=10)
    return {'started_at':started,'ended_at':time.time(),'rows':rows}


started=time.monotonic();count=0
with path.open('x') as output:
    while time.monotonic()-started<args.seconds:
        began=time.monotonic();row=system()
        if host=='unit3d-ds-data':row['mysql']=database()
        row['ended_at']=time.time();output.write(json.dumps(row)+'\n');output.flush();count+=1
        assert row['ssd_free']>8*1024**3 and row['archive_free']>20*1024**3 and row['memory']['MemAvailable']>512*1024**2,'limite_de_seguranca'
        time.sleep(max(0,args.interval-(time.monotonic()-began)))
print(json.dumps({'host':host,'samples':count,'path':str(path)}))
