#!/usr/bin/env python3
"""Diagnóstico limitado de memória, reutilizando auditoria e proteções calibradas."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import threading
import time

spec = importlib.util.spec_from_file_location('series', Path(__file__).with_name('capacity-series.py'))
s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s)


def main(args, *, preserve_previous=True, metadata=None):
    assert os.geteuid() == 0 and args.name.replace('-', '').isalnum()
    lock = open('/run/lock/unit3d-soak-supervisor.lock', 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    folder = s.ROOT/'supervisor/capacity'/args.name
    folder.mkdir(parents=True, exist_ok=False)
    originals = {str(vm): {k: s.config(vm)[k] for k in ('name','cores','memory','balloon','scsi0')} for vm in (120,121)}
    s.atomic(folder/'resources-before.json', originals)
    if metadata is not None:
        s.atomic(folder/'variant.json', metadata)
    state = {'name': args.name, 'status': 'running', 'started_at': time.time(), 'mode': args.mode, 'results': [], 'stage': 'prepare'}
    s.atomic(folder/'status.json', state)
    unit = 'unit3d-cap-memory-'+args.name
    probe = s.ROOT/'data/results/capacity'/args.name/'memory.json'
    stop_watch = threading.Event(); faults = []; watch = None; probe_started = False
    def probe_check():
        while not stop_watch.wait(1):
            try:
                row = s.read(probe)
                assert time.time()-row['at'] < 20, 'memory_probe_stale'
                assert not row.get('failures'), 'memory_probe_failed'
            except Exception as exc:
                faults.append(str(exc) if isinstance(exc, AssertionError) else type(exc).__name__)
                s.stop = True
                break
    def event(phase, trial=None):
        with (folder/'events.jsonl').open('a') as out:
            out.write(json.dumps({'at': time.time(), 'phase': phase, 'trial': trial})+'\n')
    def idle(seconds):
        for _ in range(seconds):
            assert not s.stop, 'cancelled_or_memory_probe'
            time.sleep(1)
    try:
        assert not s.guest(120,['docker','ps','--format','{{.Names}}']).strip(), 'tracker_ativo'
        if args.mode == 'calibration' and preserve_previous:
            proof=json.loads(s.guest(121,['python3',s.LAB+'/capacity-memory-probe.py','--preserve-previous'],100))
            s.atomic(folder/'previous-state-preserved.json', proof)
        s.resize(120,4,8192); s.resize(121,1,4096)
        s.atomic(folder/'database1ram4-resources.json', s.effective_resources())
        state.update(stage='probe_calibration', resources={'tracker':[4,8192],'data':[1,4096]})
        s.atomic(folder/'status.json',state)
        row=json.loads(s.guest(121,['python3',s.LAB+'/capacity-memory-probe.py','--once'],15))
        assert not row['failures'] and row['sql_end']-row['sql_start'] < 2, 'instrumento_sql'
        assert any(x.startswith('prepared_aggregate\t') for x in row['mysql_memory']), 'instrumento_incompleto'
        s.atomic(folder/'probe-before.json',row)
        s.guest(121,['systemd-run','--quiet','--unit='+unit,'--property=RuntimeMaxSec=2700',
                     'python3',s.LAB+'/capacity-memory-probe.py',args.name])
        probe_started=True
        deadline=time.monotonic()+15
        while not probe.exists():
            assert time.monotonic()<deadline, 'probe_start_timeout'
            time.sleep(.5)
        watch=threading.Thread(target=probe_check,daemon=True); watch.start()
        event('before_trials'); idle(10)
        stages=[('calibration',1000,30,10)] if args.mode=='calibration' else [
            (str(rate),rate,60,20) for rate in (500,1000,2000,4000,6000,5000,5500)] + [
            ('confirm-1',5500,300,30),('confirm-2',5500,300,30)]
        for label,rate,seconds,warmup in stages:
            name=args.name+'-'+label
            state.update(stage='trial',trial=name,rate=rate); s.atomic(folder/'status.json',state)
            assert not faults and not s.stop, 'memory_probe'
            event('before_reset_and_start', name)
            result=s.trial(name,rate,seconds,warmup,folder)
            event('after_tracker_stop', name)
            state['results'].append({'trial':name,'rate':rate,'accepted':result['accepted'],
                                    'accounting_passed':result['accounting_passed'],'stable':result['stable'],
                                    'reason':result['supervisor_reason']})
            s.atomic(folder/'status.json',state)
            assert result['status']=='passed' and not result['errors'] and not result['supervisor_reason'], 'rodada_interrompida'
            if args.mode=='calibration':
                assert result['stable'], 'calibracao_instavel'
            # O objetivo é alocação, não declarar teto; uma tendência pequena é registrada.
            idle(10)
        event('idle_after_trials'); idle(30)
        state.update(status='completed',stage='restore')
    except Exception as exc:
        state.update(status='failed',error=type(exc).__name__,
                     reason=str(exc) if isinstance(exc,AssertionError) else 'diagnostico_local')
    finally:
        # Registrar antes do reboot que apagará as alocações e os contadores voláteis.
        try:
            row=json.loads(s.guest(121,['python3',s.LAB+'/capacity-memory-probe.py','--once'],15))
            s.atomic(folder/'probe-before-restore.json',row)
        except Exception as exc:
            state['snapshot_error']=type(exc).__name__
            state['status']='failed'
        stop_watch.set()
        if watch: watch.join(timeout=3)
        state['probe_failures']=faults
        if faults: state['status']='failed'
        if probe_started:
            try: s.guest(121,['systemctl','stop',unit],20)
            except Exception as exc:
                state['probe_stop_error']=type(exc).__name__
                state['status']='failed'
        try:
            s.guest(120,['python3',s.LAB+'/capacity-admin.py','tracker','stop'],200)
            for vm in (120,121): s.resize(vm,int(originals[str(vm)]['cores']),int(originals[str(vm)]['memory']))
            s.atomic(folder/'resources-after.json',s.effective_resources())
            state['resources_restored']=True
        except Exception as exc:
            state.update(resources_restored=False,restore_error=type(exc).__name__,status='failed')
        state['finished_at']=time.time(); s.atomic(folder/'status.json',state)
        print(json.dumps(state))


if __name__=='__main__':
    def stopped(*_): s.stop=True
    signal.signal(signal.SIGTERM,stopped)
    p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('--mode',choices=['calibration','diagnostic'],required=True)
    main(p.parse_args())
