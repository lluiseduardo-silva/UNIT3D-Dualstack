#!/usr/bin/env python3
"""Três baselines originais; cada reset exige sucesso e evidências da anterior."""
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

BASE='/opt/unit3d-dualstack'
HOST=Path('/storage_pool/unit3d-dualstack')
SCRIPTS=Path('/root/unit3d-soak')
NAME='rust-original-formal-v1'
RUNS=['rust-original-formal-r'+str(i)+'-v1' for i in (1,2,3)]
assert os.geteuid()==0 and socket.gethostname()=='proxmox'
os.umask(0o077)
lock=open('/run/lock/unit3d-comparison-series.lock','w')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
folder=HOST/'supervisor'/NAME;folder.mkdir(exist_ok=False)
status={'name':NAME,'status':'preparing','started_at':time.time(),'completed':[]}
stop=False;child=None;preparing=False


def stopped(*_):
    global stop
    stop=True
    if child and child.poll() is None:child.terminate()


signal.signal(signal.SIGTERM,stopped)


def save():
    status['updated_at']=time.time()
    p=folder/'status.partial';p.write_text(json.dumps(status)+'\n');os.replace(p,folder/'status.json')


def guest(vm,command,timeout=180):
    r=subprocess.run(['qm','guest','exec',str(vm),'--timeout','1','--',*command],capture_output=True,text=True,timeout=15)
    assert r.returncode==0,'guest_exec_failed'
    value=json.loads(r.stdout);deadline=time.monotonic()+timeout
    while not value.get('exited'):
        assert time.monotonic()<deadline,'guest_deadline'
        time.sleep(.5)
        pid=value['pid']
        r=subprocess.run(['qm','guest','exec-status',str(vm),str(pid)],capture_output=True,text=True,timeout=15)
        assert r.returncode==0,'guest_status_failed'
        value=json.loads(r.stdout);value.setdefault('pid',pid)
    with (folder/'setup.log').open('a') as log:
        log.write(value.get('out-data',''));log.write(value.get('err-data',''))
    assert value.get('exitcode')==0,'guest_command_failed_vm_'+str(vm)


def check_previous(name):
    previous=json.loads((HOST/'supervisor'/name/'status.json').read_text())
    assert previous['status']=='passed' and previous['tracker_drain']['status']=='passed','previous_run_failed'
    proof=subprocess.run(['python3',str(SCRIPTS/'verify-soak-samples.py'),name],capture_output=True,text=True,timeout=180)
    assert proof.returncode==0,'previous_samples_failed'
    evidence=json.loads(proof.stdout)
    (folder/(name+'-integrity.json')).write_text(json.dumps(evidence)+'\n')
    guest(122,['python3',BASE+'/lab/audit-rust-comparison-samples.py',name],240)
    return evidence


try:
    check_previous('rust-original-calibration-v2')
    for name in RUNS:
        assert not stop,'series_stopped'
        status.update(status='preparing',current=name);save()
        assert not (HOST/'supervisor'/name).exists(),'run_already_exists'
        for vm in (120,121,122):guest(vm,['python3',BASE+'/lab/archive-preflight.py'])
        guest(120,['bash','-c','test -z "$(docker ps -q)" && ! docker inspect unit3d-ds-rust >/dev/null 2>&1'])
        preparing=True
        guest(120,['docker','run','--rm','--network','host','-e','DB_DATABASE=unit3d_dualstack_journal_test',
            '-v',BASE+'/repos/UNIT3D:/app','-v',BASE+'/lab:/lab:ro','unit3d-ds-php:baseline','php','/lab/initialize-journal-test.php'])
        guest(122,['install','-m','600',BASE+'/soak/'+name+'.json',BASE+'/'+name+'.json'])
        guest(122,['python3',BASE+'/density-fixture.py',name+'.json'])
        guest(122,['python3',BASE+'/lab/rust-comparison-fixture.py',name])
        guest(122,['python3',BASE+'/lab/soak-setup-client.py','add'])
        guest(120,['python3',BASE+'/lab/soak-backend.py',BASE+'/soak/'+name+'.json'],330)
        guest(122,['python3',BASE+'/benchmark-readiness.py'])
        guest(120,['python3',BASE+'/lab/rust-comparison-provenance.py',name])
        assert not stop,'series_stopped'
        with (folder/(name+'-supervisor.log')).open('x') as log:
            child=subprocess.Popen(['python3',str(SCRIPTS/'soak-supervisor.py'),str(SCRIPTS/(name+'.json'))],stdout=log,stderr=subprocess.STDOUT)
            preparing=False
            status.update(status='running',current=name);save()
            code=child.wait(timeout=1800)
        assert code==0,'run_failed_'+name
        proof=check_previous(name)
        # Os JSONs públicos e as amostras permanecem no arquivo; a fixture privada
        # foi preservada antes da carga. Não exportar dump de banco nem passkeys.
        status['completed'].append(proof);save()
    status.update(status='passed',current=None)
except Exception as error:
    status.update(status='failed',reason=str(error) if isinstance(error,AssertionError) else type(error).__name__)
    if child and child.poll() is None:
        child.terminate()
        try:child.wait(timeout=300)
        except subprocess.TimeoutExpired:status['supervisor_shutdown']='unconfirmed'
    if preparing:
        try:
            guest(120,['bash',BASE+'/lab/benchmark-backend.sh','stop','rust','original'],240)
            guest(122,['bash','-c','if test -e '+BASE+'/soak-aliases.json; then python3 '+BASE+'/lab/soak-setup-client.py remove; fi'])
        except Exception:status['preparation_cleanup']='failed_preserve_evidence'
finally:
    status['finished_at']=time.time();save()
raise SystemExit(0 if status['status']=='passed' else 1)
