#!/usr/bin/env python3
"""Supervisor independente no Proxmox; mantém evidências e restaura recursos."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from capacity_metrics import lag_trend

ROOT=Path('/storage_pool/unit3d-dualstack')
LAB='/opt/unit3d-dualstack/lab'
stop=False


def command(args,timeout=30):
    r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    assert r.returncode==0,'comando_falhou'
    return r.stdout


def guest(vm,argv,timeout=60):
    v=json.loads(command(['qm','guest','exec',str(vm),'--timeout','1','--',*argv],15));pid=v.get('pid');deadline=time.monotonic()+timeout
    while not v.get('exited'):
        assert time.monotonic()<deadline,'guest_timeout'
        time.sleep(.3);v=json.loads(command(['qm','guest','exec-status',str(vm),str(pid)],15))
    assert v.get('exitcode')==0,'guest_failed_'+str(vm)
    return v.get('out-data','')


def config(vm):
    raw=command(['qm','config',str(vm)])
    return dict(line.split(': ',1) for line in raw.splitlines() if ': ' in line)


def resize(vm,cores,memory):
    c=config(vm)
    assert c['name']=={120:'unit3d-ds-tracker',121:'unit3d-ds-data'}[vm] and 'dualstack' in c['tags']
    if int(c['cores'])==cores and int(c['memory'])==memory:return
    if vm==121:
        guest(vm,['systemctl','stop','unit3d-binlog-archive.timer','unit3d-binlog-archive.service'],120)
        guest(vm,['docker','stop','-t','120','unit3d-ds-mysql','unit3d-ds-redis'],150)
    assert not guest(vm,['docker','ps','--format','{{.Names}}']).strip(),'container_ativo_ao_redimensionar'
    command(['qm','shutdown',str(vm),'--timeout','120'],135)
    assert 'stopped' in command(['qm','status',str(vm)])
    command(['qm','set',str(vm),'--cores',str(cores),'--memory',str(memory),'--balloon','0'])
    command(['qm','start',str(vm)],60)
    deadline=time.monotonic()+150
    while True:
        try:
            guest(vm,['true'],5);break
        except Exception:
            assert time.monotonic()<deadline,'boot_timeout'
            time.sleep(2)
    assert int(guest(vm,['nproc']).strip())==cores,'cpu_profile'
    if vm==121:
        guest(vm,['docker','start','unit3d-ds-mysql','unit3d-ds-redis'])
        deadline=time.monotonic()+90
        while True:
            try:guest(vm,['python3',LAB+'/capacity-admin.py','data','status'],15);break
            except Exception:
                assert time.monotonic()<deadline,'mysql_readiness'
                time.sleep(2)
        guest(vm,['systemctl','start','unit3d-binlog-archive.timer'])


def atomic(path,value):
    temp=path.with_suffix('.partial');temp.write_text(json.dumps(value,indent=2)+'\n');os.replace(temp,path)


def read(path):
    return json.loads(path.read_text())


def read_jsonl(path):
    # O observador ainda pode estar anexando a última linha.
    return [json.loads(line) for line in path.read_text().rsplit('\n',1)[0].splitlines()]


def thin_free():
    row=json.loads(command(['lvs','--reportformat','json','--units','b','--nosuffix','-o','lv_name,lv_size,data_percent','pve/data']))['report'][0]['lv'][0]
    return float(row['lv_size'])*(1-float(row['data_percent'])/100)


def effective_resources():
    values={}
    for vm in (120,121,122):
        values[str(vm)]={'configured':{k:v for k,v in config(vm).items() if k in ('name','cores','sockets','memory','balloon','scsi0','cpu')},
                         'cpu_online':int(guest(vm,['nproc']).strip()),
                         'memory':guest(vm,['awk','/^MemTotal:|^MemAvailable:|^SwapTotal:/ {print}', '/proc/meminfo']).splitlines()}
    values['database']=json.loads(guest(121,['python3',LAB+'/capacity-admin.py','data','status']))
    return values


def trial(name,rate,seconds,warmup,folder):
    assert not stop,'cancelled'
    guest(121,['python3',LAB+'/capacity-admin.py','data','reset'],120)
    guest(120,['python3',LAB+'/capacity-admin.py','tracker','start'],150)
    units=[];host_observer=None;started=time.monotonic();limit_reason=None;lags=[];latest={}
    try:
        host_observer=subprocess.Popen(['python3',str(Path(__file__).with_name('capacity-observer.py')),name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for vm in (120,121,122):
            label='unit3d-cap-observer-'+name
            guest(vm,['systemd-run','--quiet','--unit='+label,'--property=RuntimeMaxSec='+str(seconds+warmup+150),
                      'python3',LAB+'/capacity-observer.py',name]);units.append((vm,label))
        label='unit3d-cap-load-'+name
        guest(122,['systemd-run','--quiet','--unit='+label,'--property=RuntimeMaxSec='+str(seconds+warmup+150),
                   'python3',LAB+'/capacity-load.py',name,'--rate',str(rate),'--seconds',str(seconds),'--warmup',str(warmup)])
        units.append((122,label))
        client=ROOT/'clients/results/capacity'/name
        with (folder/(name+'-monitor.jsonl')).open('x') as log:
            while not (client/'result.json').exists():
                assert time.monotonic()-started<seconds+warmup+140,'trial_timeout'
                reason='cancelled' if stop else None
                host_path=ROOT/'supervisor/capacity'/name/'proxmox-observer.json'
                if host_observer.poll() is not None:reason='observer_exited_host'
                elif host_path.exists():
                    host_sample=read(host_path)
                    if time.time()-host_sample['at']>20 or host_sample.get('failures'):reason='guard_host'
                for role in ('tracker','data','clients'):
                    path=ROOT/role/'results/capacity'/name/(role+'-observer.json')
                    if not path.exists():
                        if time.monotonic()-started>20:reason='observer_missing_'+role
                        continue
                    value=read(path);latest[role]=value
                    if time.time()-value['at']>20:reason='observer_stale_'+role
                    if value.get('failures'):reason='guard_'+role
                progress=read(client/'progress.json') if (client/'progress.json').exists() else None
                if progress and time.time()-progress['at']>10:reason='load_stale'
                data=latest.get('data',{})
                versions=next((int(line.split('\t')[1]) for line in data.get('mysql',[]) if line.startswith('persisted\t')),None)
                if progress and versions is not None:
                    lag=max(0,progress['accepted']-versions)
                    lags.append({'at':time.time(),'accepted':progress['accepted'],'persisted':versions,'lag':lag,'sql_at':data.get('sql_end')})
                    if lag>60000:reason='capacity_backlog'
                free=thin_free()
                if free<8*1024**3:reason='thin_low'
                s=os.statvfs(ROOT)
                if s.f_bavail*s.f_frsize<20*1024**3:reason='archive_low'
                log.write(json.dumps({'at':time.time(),'progress':progress,'lag':lags[-1] if lags else None,'thin_free':free})+'\n');log.flush()
                if reason and limit_reason is None:
                    limit_reason=reason;(client/'stop').touch()
                time.sleep(2)
        result=read(client/'result.json');result['supervisor_reason']=limit_reason
        assert result['accounting_passed'],'contabilidade'
        progress_rows=read_jsonl(client/'progress.jsonl')
        observer_rows=read_jsonl(ROOT/'data/results/capacity'/name/'data-observer.jsonl')
        trend=lag_trend(progress_rows,observer_rows,result['measured_at'],result['finish_epoch'],rate)
        result['aligned_lag_trend']=trend
        result['observed_lag_slope_per_second']=trend.get('slope_per_second')
        result['max_observed_lag']=max((x['lag'] for x in lags),default=0)
        result['stable']=result['status']=='passed' and result['completed_rps']>=rate*.99 and result['drain_seconds']<=30 and trend['sufficient_samples'] and not trend['growing'] and not limit_reason
        atomic(folder/(name+'-result.json'),result)
        assert limit_reason in (None,'capacity_backlog'), 'protecao_acionada_'+str(limit_reason)
        assert not result['errors'] or set(result['errors'])=={'generator_lag'},'erro_http'
        return result
    finally:
        if host_observer:
            host_observer.terminate();host_observer.wait(timeout=10)
        for vm,label in reversed(units):
            try:guest(vm,['systemctl','stop',label],30)
            except Exception:pass
        drain=json.loads(guest(120,['python3',LAB+'/capacity-admin.py','tracker','stop'],200))
        atomic(folder/(name+'-tracker-drain.json'),drain)


def main(args):
    assert os.geteuid()==0 and args.name.replace('-','').isalnum()
    lock=open('/run/lock/unit3d-soak-supervisor.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    folder=ROOT/'supervisor/capacity'/args.name;folder.mkdir(parents=True,exist_ok=False)
    originals={str(vm):{k:config(vm)[k] for k in ('name','cores','memory','balloon','scsi0')} for vm in (120,121)}
    atomic(folder/'resources-before.json',originals)
    state={'name':args.name,'status':'running','started_at':time.time(),'results':[],'mode':args.mode}
    atomic(folder/'status.json',state)
    profiles=[('reference',(4,8192),(4,8192))] if args.mode in ('smoke','alignment-smoke') else [('balanced1',(1,2048),(1,2048))] if args.mode=='resource-smoke' else [
        ('reference',(4,8192),(4,8192)),('tracker1',(1,2048),(4,8192)),('tracker2',(2,4096),(4,8192)),
        ('database1',(4,8192),(1,2048)),('database2',(4,8192),(2,4096)),
        ('database1ram4',(4,8192),(1,4096)),('database2ram2',(4,8192),(2,2048)),
        ('balanced1',(1,2048),(1,2048)),('balanced2',(2,4096),(2,4096))]
    try:
        for profile,tracker,data in profiles:
            assert not stop,'cancelled'
            state.update(profile=profile,stage='resources');atomic(folder/'status.json',state)
            resize(120,*tracker);resize(121,*data)
            atomic(folder/(profile+'-resources.json'),effective_resources())
            state['resources']={'tracker':tracker,'data':data};atomic(folder/'status.json',state)
            rates=[1000] if args.mode in ('smoke','resource-smoke','alignment-smoke') else [500,1000,2000,4000,6000,8000,10000,12000,16000]
            stable_rate=None;limited_rate=None
            for rate in rates:
                name=args.name+'-'+profile+'-'+str(rate)
                state.update(stage='ramp',trial=name,rate=rate);atomic(folder/'status.json',state)
                result=trial(name,rate,30 if args.mode in ('smoke','resource-smoke') else 60,2 if args.mode in ('smoke','resource-smoke') else 20,folder)
                state['results'].append({'trial':name,'profile':profile,'rate':rate,'stable':result['stable'],'rps':result['completed_rps'],'drain_seconds':result['drain_seconds'],'reason':result['supervisor_reason'],'errors':result['errors']})
                atomic(folder/'status.json',state)
                if not result['stable']:
                    limited_rate=rate;break
                stable_rate=rate
            if args.mode=='cpu-ram' and stable_rate and limited_rate:
                # Duas bisseções delimitam a fronteira; confirmações longas continuam obrigatórias.
                for refinement in range(2):
                    if limited_rate-stable_rate<=max(100,stable_rate*.125):break
                    rate=((stable_rate+limited_rate)//200)*100
                    name=args.name+'-'+profile+'-refine-'+str(rate)
                    state.update(stage='refinement',trial=name,rate=rate);atomic(folder/'status.json',state)
                    result=trial(name,rate,60,20,folder)
                    state['results'].append({'trial':name,'profile':profile,'rate':rate,'stable':result['stable'],'rps':result['completed_rps'],'refinement':True,'reason':result['supervisor_reason'],'errors':result['errors']})
                    atomic(folder/'status.json',state)
                    if result['stable']:stable_rate=rate
                    else:limited_rate=rate
            if args.mode=='cpu-ram' and stable_rate:
                for repeat in range(1,4):
                    name=args.name+'-'+profile+'-confirm-'+str(repeat)
                    state.update(stage='confirmation',trial=name,rate=stable_rate);atomic(folder/'status.json',state)
                    result=trial(name,stable_rate,300,30,folder)
                    state['results'].append({'trial':name,'profile':profile,'rate':stable_rate,'stable':result['stable'],'rps':result['completed_rps'],'confirmation':repeat})
                    atomic(folder/'status.json',state)
                    if not result['stable']:break
        state['status']='completed'
    except Exception as e:
        state.update(status='failed',error=type(e).__name__,reason=str(e) if isinstance(e,AssertionError) else 'diagnostico_local')
    finally:
        try:
            guest(120,['python3',LAB+'/capacity-admin.py','tracker','stop'],200)
            for vm in (120,121):resize(vm,int(originals[str(vm)]['cores']),int(originals[str(vm)]['memory']))
            guest(121,['docker','start','unit3d-ds-mysql','unit3d-ds-redis'])
            guest(121,['systemctl','start','unit3d-binlog-archive.timer'])
            state['resources_restored']=True
        except Exception as e:state.update(resources_restored=False,restore_error=type(e).__name__,status='failed')
        state['finished_at']=time.time();atomic(folder/'status.json',state)
        print(json.dumps(state))


if __name__=='__main__':
    def stopped(*_):
        global stop
        stop=True
    signal.signal(signal.SIGTERM,stopped)
    p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('--mode',choices=('smoke','resource-smoke','alignment-smoke','cpu-ram'),default='smoke')
    main(p.parse_args())
