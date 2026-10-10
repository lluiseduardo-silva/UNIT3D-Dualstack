#!/usr/bin/env python3
"""Observador local sem credenciais nos resultados; heartbeat monotônico."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

from soak_guard import failures

ROOT=Path('/mnt/unit3d-archive/results/soak')
parser=argparse.ArgumentParser();parser.add_argument('name');args=parser.parse_args()
role=socket.gethostname().removeprefix('unit3d-ds-')
assert role in ('tracker','data','clients') and os.geteuid()==0 and all(c.isalnum() or c=='-' for c in args.name)
os.umask(0o077)
folder=ROOT/args.name
plan=json.loads((Path('/opt/unit3d-dualstack/soak')/(args.name+'.json')).read_text())
# Client folder is owned/created by the load; avoid racing its exclusive creation.
if role!='clients':folder.mkdir(parents=True,exist_ok=False)
assert folder.is_dir()
if role=='tracker' and 'comparison_variant' in plan:
    provenance=Path('/opt/unit3d-dualstack/comparison-provenance')/(args.name+'.json')
    if provenance.exists():(folder/'provenance.json').write_text(provenance.read_text())
stop=False


def stopped(*_):
    global stop
    stop=True


signal.signal(signal.SIGTERM,stopped)
if role=='data':
    spec=importlib.util.spec_from_file_location('archive','/usr/local/sbin/unit3d-archive-binlogs.py')
    archive=importlib.util.module_from_spec(spec);spec.loader.exec_module(archive)
    paused='copy_modes' in plan
    assert not paused or plan['seconds']<=600


def inspect(name):
    data=subprocess.run(['docker','inspect',name,'--format','{{json .State}}'],capture_output=True,text=True,timeout=5)
    assert data.returncode==0,'container_missing'
    return json.loads(data.stdout)


def sample():
    mount=subprocess.run(['findmnt','-n','-o','SOURCE,FSTYPE','--mountpoint','/mnt/unit3d-archive'],capture_output=True,text=True,timeout=5)
    assert mount.returncode==0 and mount.stdout.split()==['unit3d-ds-'+role,'virtiofs'],'archive_mount'
    memory={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemAvailable:','SwapFree:'))}
    ssd=os.statvfs('/');zfs=os.statvfs(ROOT)
    result={'role':role,'at':time.time(),'ssd_free':ssd.f_bavail*ssd.f_frsize,'archive_free':zfs.f_bavail*zfs.f_frsize,
            'memory_available':memory['MemAvailable'],'swap_free':memory['SwapFree'],'processes':{}}
    for p in Path('/proc').glob('[0-9]*'):
        try:
            comm=(p/'comm').read_text().strip()
            if comm not in ('unit3d-announce','mysqld','redis-server','python3'):continue
            stat=(p/'stat').read_text().rsplit(')',1)[1].split()
            rollup=(p/'smaps_rollup').read_text()
            pss=int(next(l.split()[1] for l in rollup.splitlines() if l.startswith('Pss:')))*1024
            result['processes'][p.name]={'name':comm,'rss':int(stat[21])*os.sysconf('SC_PAGE_SIZE'),'pss':pss,'cpu_ticks':int(stat[11])+int(stat[12])}
        except (FileNotFoundError,ProcessLookupError,PermissionError,StopIteration):pass
    if role=='data':
        state=json.loads((Path('/mnt/unit3d-archive')/'archive-status.json').read_text())
        logs=archive.inventory()
        sql=archive.mysql('SELECT SUM(state_version),SUM(uploaded) FROM unit3d_dualstack_journal_test.peers WHERE user_id>=20000; SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM unit3d_dualstack_journal_test.tracker_ownership WHERE id=1;')
        mysql=inspect('unit3d-ds-mysql')
        result.update(archive_age=time.time()-state['time'],closed_binlog_bytes=sum(n for _,n in logs[:-1]),
            archive_timer_active=subprocess.run(['systemctl','is-active','--quiet','unit3d-binlog-archive.timer']).returncode==0,
            archive_failed=subprocess.run(['systemctl','is-failed','--quiet','unit3d-binlog-archive.service']).returncode==0,
            mysql_restarts=int(subprocess.check_output(['docker','inspect','unit3d-ds-mysql','--format','{{.RestartCount}}'],text=True)),
            persisted_versions=int(sql[0][0] or 0),persisted_upload=int(sql[0][1] or 0),owner_live=sql[1][0]=='1',mysql_running=mysql['Running'])
        result['archive_paused_for_comparison']=paused
        result['owner_lease_required']=plan.get('comparison_variant')!='original'
        assert result['mysql_running'],'mysql_stopped'
    elif role=='tracker':
        result['tracker_running']=inspect('unit3d-ds-rust')['Running']
    result['failures']=failures(result)
    return result


seq=0
with (folder/'observer.jsonl').open('x') as output:
    while not stop:
        try:
            result=sample()
            seq+=1;result['sequence']=seq
            output.write(json.dumps(result)+'\n');output.flush()
            tmp=folder/'observer.partial';tmp.write_text(json.dumps(result)+'\n');os.replace(tmp,folder/'observer.json')
            if result['failures']:break
        except Exception as error:
            # Preserve failure on local SSD if the archive itself is unavailable.
            Path('/run/unit3d-soak-observer-error').write_text(type(error).__name__+'\n')
            raise
        time.sleep(5)
