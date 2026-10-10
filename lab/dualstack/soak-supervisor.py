#!/usr/bin/env python3
"""Supervisor Proxmox: independe de SSH e interrompe carga antes de esgotar recursos."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

from soak_guard import GIB
from soak_diagnostics import record_drain

HOST=Path('/storage_pool/unit3d-dualstack')
BASE='/opt/unit3d-dualstack'
parser=argparse.ArgumentParser();parser.add_argument('plan');args=parser.parse_args()
assert socket.gethostname()=='proxmox' and os.geteuid()==0
os.umask(0o077)
lock=open('/run/lock/unit3d-soak-supervisor.lock','w')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
plan=json.loads(Path(args.plan).read_text());name=plan['name']
variant=plan.get('comparison_variant','candidate')
assert variant in ('candidate','original')
comparison='comparison_variant' in plan
assert all(c.isalnum() or c=='-' for c in name)
folder=HOST/'supervisor'/name;folder.mkdir(parents=True,exist_ok=False)
stop=False


def signal_stop(*_):
    global stop
    stop=True


signal.signal(signal.SIGTERM,signal_stop)


def guest(vm,command,timeout=30):
    result=subprocess.run(['qm','guest','exec',str(vm),'--timeout','1','--',*command],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,'guest_exec_failed'
    value=json.loads(result.stdout)
    end=time.monotonic()+timeout
    while not value.get('exited'):
        assert time.monotonic()<end,'guest_command_timeout'
        time.sleep(.3)
        result=subprocess.run(['qm','guest','exec-status',str(vm),str(value['pid'])],capture_output=True,text=True,timeout=10)
        assert result.returncode==0,'guest_status_failed'
        previous=value;value=json.loads(result.stdout)
        if not value.get('exited'):value['pid']=previous['pid']
    assert value.get('exitcode')==0,'guest_command_failed'
    return value.get('out-data','')


def unit(vm,label,command,seconds=22500):
    guest(vm,['systemd-run','--quiet','--unit='+label,'--property=RuntimeMaxSec='+str(seconds),
              '--property=TimeoutStopSec=120','--property=KillMode=control-group',
              '--property=WorkingDirectory='+BASE+'/lab',*command])


def write(data):
    data['updated_at']=time.time()
    temp=folder/'status.partial';temp.write_text(json.dumps(data)+'\n');os.replace(temp,folder/'status.json')


def thin_free():
    raw=json.loads(subprocess.check_output(['lvs','--reportformat','json','--units','b','--nosuffix','-o','lv_name,lv_size,data_percent','pve/data'],text=True,timeout=5))
    row=raw['report'][0]['lv'][0]
    return int(float(row['lv_size'])*(1-float(row['data_percent'])/100))


units=[];reason=None;result='failed';last_seen={};last_progress={};lag_since=None;injected=False;last_trim=0;copy_number=-1;copy_pending=None
started=time.monotonic()
status={'name':name,'status':'starting','started_at':time.time(),'plan':plan}
try:
    for vm in (120,121,122):
        guest(vm,['python3',BASE+'/lab/archive-preflight.py'])
    if 'copy_modes' in plan:
        assert plan['seconds']<=600
        guest(121,['systemctl','stop','unit3d-binlog-archive.timer','unit3d-binlog-archive.service'],180)
    for vm,role in [(120,'tracker'),(121,'data')]:
        label='unit3d-soak-observer-'+name
        unit(vm,label,['python3',BASE+'/lab/soak-observer.py',name]);units.append((vm,label))
    load_unit='unit3d-soak-load-'+name
    runner='rust-comparison-load.py' if comparison else 'soak-load.py'
    unit(122,load_unit,['python3',BASE+'/lab/'+runner,BASE+'/soak/'+name+'.json'],plan['seconds']+300)
    units.append((122,load_unit))
    client=HOST/'clients/results/soak'/name
    deadline=time.monotonic()+20
    while not (client/'progress.json').exists():
        assert time.monotonic()<deadline,'load_start_timeout'
        time.sleep(.5)
    label='unit3d-soak-observer-'+name
    unit(122,label,['python3',BASE+'/lab/soak-observer.py',name]);units.append((122,label))
    first_progress=json.loads((client/'progress.json').read_text())
    load_start=time.time()-first_progress['elapsed_seconds']
    status.update(status='running',load_started_at=load_start,expected_end_at=load_start+plan['seconds'])
    with (folder/'monitor.jsonl').open('x') as log:
        while True:
            assert not stop,'supervisor_stopped'
            assert time.monotonic()-started < plan['seconds']+240,'supervisor_deadline'
            samples={}
            for role in ('tracker','data','clients'):
                path=HOST/role/'results/soak'/name/'observer.json'
                if not path.exists():
                    assert time.monotonic()-started<30,'observer_missing_'+role
                    continue
                sample=json.loads(path.read_text())
                if last_progress.get(role)!=sample['sequence']:
                    last_seen[role]=time.monotonic();last_progress[role]=sample['sequence']
                assert time.monotonic()-last_seen[role]<30,'observer_stale_'+role
                assert not sample['failures'],'guard_'+role+'_'+','.join(sample['failures'])
                samples[role]=sample
            progress=json.loads((client/'progress.json').read_text())
            request=client/'copy-request.json'
            if request.exists():
                req=json.loads(request.read_text())
                assert 'copy_modes' in plan and 0<=req['number']<len(plan['copy_modes'])
                copy_folder=HOST/'data/results/soak'/name
                ready=copy_pending is None or (copy_folder/('copy-finished-'+str(copy_pending)+'.json')).exists()
                if req['number']>copy_number and ready:
                    copy_number=req['number']
                    if req['enabled']:
                        label='unit3d-soak-copy-'+name+'-'+str(copy_number)
                        unit(121,label,['python3',BASE+'/lab/soak-copy-probe.py',name,str(copy_number)],120)
                        copy_pending=copy_number
                    (client/'copy-ack.partial').write_text(json.dumps({'number':copy_number})+'\n')
                    os.replace(client/'copy-ack.partial',client/'copy-ack.json')
            if plan.get('inject_observer_failure_at') and not injected and progress['elapsed_seconds']>=plan['inject_observer_failure_at']:
                assert plan['seconds']<=180,'fault_injection_requires_short_run'
                guest(122,['systemctl','stop','unit3d-soak-observer-'+name],15)
                injected=True
            if last_progress.get('load')!=progress['sequence']:
                last_seen['load']=time.monotonic();last_progress['load']=progress['sequence']
            assert time.monotonic()-last_seen['load']<30,'load_heartbeat_stale'
            assert progress['errors']==0,'load_errors'
            free=thin_free();assert free>=8*GIB,'thin_pool_low'
            if free<16*GIB and time.monotonic()-last_trim>300:
                # Reclaim only discarded blocks in VM 121, before the 8 GiB stop.
                guest(121,['fstrim','--minimum','1048576','/'],60)
                last_trim=time.monotonic()
                log.write(json.dumps({'at':time.time(),'action':'trim_data_vm','thin_free_before':free})+'\n')
            if comparison and variant=='original':
                # 100 bytes por announce; inclui atraso de até 5 s do observador.
                # Não interpretar state_version, que não existe no protocolo original.
                lag=max(0,(progress['expected_upload']-samples.get('data',{}).get('persisted_upload',progress['expected_upload']))//100)
            else:
                lag=max(0,progress['accepted']-samples.get('data',{}).get('persisted_versions',progress['accepted']))
            # A 5 s observer can lag by 40k at 8k/s; require an additional full window.
            if lag>80000:
                lag_since=lag_since or time.monotonic()
                assert time.monotonic()-lag_since<30,'persistence_backlog'
            else:lag_since=None
            event={'at':time.time(),'progress':progress,'thin_free':free,'observed_persistence_lag':lag}
            log.write(json.dumps(event)+'\n');log.flush()
            status.update(progress=progress,thin_free=free,observed_persistence_lag=lag)
            write(status)
            final=client/'final.json'
            if final.exists():
                final=json.loads(final.read_text())
                assert final['status']=='passed','load_final_'+str(final.get('reason'))
                status['load_result']=final;result='passed';break
            time.sleep(5)
except Exception as error:
    reason=str(error) if isinstance(error,AssertionError) else type(error).__name__
finally:
    status.update(status='draining',reason=reason);write(status)
    if 'copy_modes' in plan:
        # Restore maintenance even if the synthetic copy later fails or times out.
        try:guest(121,['systemctl','start','unit3d-binlog-archive.timer'],15)
        except Exception:reason=reason or 'archive_timer_restore_failed';result='failed'
    # Stop input first, then observers and tracker; do not remove any guest data.
    status['cleanup']=[]
    for vm,label in sorted(units,key=lambda pair:0 if 'soak-load' in pair[1] else 1):
        try:
            guest(vm,['python3',BASE+'/lab/soak-stop-unit.py',label],150)
            status['cleanup'].append({'vm':vm,'unit':label,'status':'stopped_or_already_inactive'})
        except Exception:
            reason=reason or 'unit_stop_failed';result='failed'
            status['cleanup'].append({'vm':vm,'unit':label,'status':'stop_failed'})
    try:
        guest(120,['bash',BASE+'/lab/benchmark-backend.sh','stop','rust',variant],220)
        record_drain(status)
    except Exception as error:
        record_drain(status,error)
        reason=reason or 'tracker_drain_failed';result='failed'
    write(status)
    try:guest(122,['python3',BASE+'/lab/soak-setup-client.py','remove'],30)
    except Exception:reason=reason or 'alias_cleanup_failed';result='failed'
    if 'copy_modes' in plan:
        try:
            if copy_pending is not None:
                deadline=time.monotonic()+120
                while not (HOST/'data/results/soak'/name/('copy-finished-'+str(copy_pending)+'.json')).exists():
                    assert time.monotonic()<deadline,'copy_finish_timeout'
                    time.sleep(1)
        except Exception:reason=reason or 'archive_restore_failed';result='failed'
        try:guest(121,['systemctl','start','unit3d-binlog-archive.timer','unit3d-binlog-archive.service'],180)
        except Exception:reason=reason or 'archive_restore_failed';result='failed'
    status.update(status=result,reason=reason,finished_at=time.time(),elapsed_seconds=time.monotonic()-started)
    write(status)
raise SystemExit(0 if result=='passed' else 1)
