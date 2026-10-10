#!/usr/bin/env python3
"""Consolida as evidências públicas; não confunde I/O agregado com causalidade."""
import collections
import argparse
import json
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--directory',default='lease-probe',choices=('lease-probe','lease-recovery'))
ROOT=Path(__file__).parent/'results'/p.parse_args().directory


def read(path):
    return [json.loads(x) for x in path.read_text(encoding='utf-8-sig').splitlines() if x.strip()]


def percentile(values,p):
    return sorted(values)[min(len(values)-1,int((len(values)-1)*p))] if values else None


def disk_summary(rows):
    result={}
    for a,b in zip(rows,rows[1:]):
        dt=b['at']-a['at']
        for name,d in b['disks'].items():
            if name not in a['disks']:continue
            x=d['stat'];y=a['disks'][name]['stat']
            if len(x)<11 or any(v<w for v,w in zip(x[:8],y[:8])):continue
            data=result.setdefault(name,{'seconds':0,'read_bytes':0,'write_bytes':0,'reads':0,'writes':0,'flushes':0,'write_ms':0,'flush_ms':0,'busy_ms':0,'bad_time_intervals':0,'write_await_ms_samples':[],'flush_await_ms_samples':[]})
            data['seconds']+=dt;data['read_bytes']+=(x[2]-y[2])*512;data['write_bytes']+=(x[6]-y[6])*512
            data['reads']+=x[0]-y[0];data['writes']+=x[4]-y[4]
            # Contadores do host já tiveram saltos próximos do uptime; sinalizar.
            if 0<=x[7]-y[7]<=dt*1000*256 and 0<=x[9]-y[9]<=dt*1000*1.5:
                data['write_ms']+=x[7]-y[7];data['busy_ms']+=x[9]-y[9]
                if x[4]>y[4]:data['write_await_ms_samples'].append((x[7]-y[7])/(x[4]-y[4]))
            else:data['bad_time_intervals']+=1
            if len(x)>16 and 0<=x[16]-y[16]<=dt*1000*256:
                data['flushes']+=x[15]-y[15];data['flush_ms']+=x[16]-y[16]
                if x[15]>y[15]:data['flush_await_ms_samples'].append((x[16]-y[16])/(x[15]-y[15]))
    for data in result.values():
        data['write_mib_s']=data['write_bytes']/2**20/data['seconds'];data['write_iops']=data['writes']/data['seconds']
        data['read_iops']=data['reads']/data['seconds'];data['flush_ops_s']=data['flushes']/data['seconds']
        data['write_await_ms']=data['write_ms']/data['writes'] if data['writes'] and not data['bad_time_intervals'] else None
        data['busy_percent']=data['busy_ms']/data['seconds']/10 if not data['bad_time_intervals'] else None
        data['flush_await_ms']=data['flush_ms']/data['flushes'] if data['flushes'] else None
        for field in ('write_await_ms_samples','flush_await_ms_samples'):
            values=data.pop(field);data[field.replace('_samples','_interval_p99')]=percentile(values,.99)
            data[field.replace('_samples','_interval_max')]=max(values) if values else None
    return result


def groups(row):
    result={}
    for name,body in row['groups'].items():
        if '/ns/' in name:continue  # Pais já incluem os filhos.
        for line in body.splitlines():
            device,*fields=line.split();result[name+' '+device]={k:int(v) for k,v in (f.split('=') for f in fields)}
    return result


def pressure_summary(rows):
    result={}
    if len(rows)<2:return result
    def values(row,resource):
        return {line.split()[0]:{k:float(v) for k,v in (s.split('=') for s in line.split()[1:])}
                for line in row['pressure'][resource].splitlines()}
    dt=rows[-1]['at']-rows[0]['at']
    for resource in ('io','cpu','memory'):
        first,last=values(rows[0],resource),values(rows[-1],resource)
        result[resource]={kind:{'stall_percent':(last[kind]['total']-first[kind]['total'])/dt/10000,
            'avg10_max':max(values(r,resource)[kind]['avg10'] for r in rows)} for kind in first}
    return result


def mysql_summary(rows):
    result={'status_delta':{},'file_waits':{},'persisted_per_second':[]}
    if len(rows)<2:return result
    snapshots=[{v[0]:v[1:] for v in row['mysql']['rows'] if v[0] not in ('lock','statement')} for row in rows]
    first,last=snapshots[0],snapshots[-1]
    for key,value in first.items():
        if key.startswith('Innodb_') and len(value)==1:
            result['status_delta'][key]=int(last[key][0])-int(value[0])
        elif key.startswith('wait/io/file/'):
            count=int(last[key][0])-int(value[0]);wait=int(last[key][1])-int(value[1])
            result['file_waits'][key]={'operations':count,'seconds_total':wait/1e12,
                'mean_ms':wait/count/1e9 if count else None,
                'server_lifetime_max_before_ms':int(value[2])/1e9,
                'server_lifetime_max_after_ms':int(last[key][2])/1e9}
    result['checkpoint_age_max_bytes']=max(int(x['Innodb_redo_log_current_lsn'][0])-int(x['Innodb_redo_log_checkpoint_lsn'][0]) for x in snapshots)
    result['threads_running_max']=max(int(x['Threads_running'][0]) for x in snapshots)
    result['lease_remaining_min_seconds']=min(int(x['lease'][1])/1e6 for x in snapshots)
    for a,b,x,y in zip(rows,rows[1:],snapshots,snapshots[1:]):
        # Cadência SQL amostrada, não a duração de cada commit nem backlog interno.
        dt=b['mysql']['started_at']-a['mysql']['started_at']
        result['persisted_per_second'].append({'at':b['mysql']['started_at'],'rate':(int(y['counts'][0])-int(x['counts'][0]))/dt})
    return result


reports=[]
for file in sorted(ROOT.glob('*-client.json')):
    load=json.loads(file.read_text(encoding='utf-8-sig'));name=load['name']
    data=read(ROOT/(name+'-data.jsonl'));host=read(ROOT/(name+'-host.jsonl'))
    locks=collections.Counter();intervals=collections.defaultdict(list)
    for row in data:
        for value in row['mysql']['rows']:
            if value[0]=='lock':
                key=tuple(value[1:]);locks[key]+=1;intervals[key].append(row['mysql']['started_at'])
    period=[x for x in data if load['started_at']<=x['at']<=load['ended_at']]
    host_period=[x for x in host if load['started_at']<=x['at']<=load['ended_at']]
    report={'name':name,'load':load,'lock_chains':[{'request_table':k[0],'request_mode':k[1],'block_table':k[2],'block_mode':k[3],
        'waiting_connection':k[4],'blocking_connection':k[5],'samples':n,'first_at':min(intervals[k]),'last_at':max(intervals[k])} for k,n in locks.items()],
        'data_disks':disk_summary(period),'host_disks':disk_summary(host_period),'other_cgroups':{},
        'data_pressure':pressure_summary(period),'host_pressure':pressure_summary(host_period),
        'mysql':mysql_summary(period)}
    if len(host_period)>1:
        first,last=host_period[0],host_period[-1];g0,g1=groups(first),groups(last);dt=last['at']-first['at']
        for key,value in g1.items():
            if key not in g0:continue
            changes={k:value[k]-g0[key].get(k,0) for k in ('rbytes','wbytes','rios','wios')}
            if changes['rbytes'] or changes['wbytes']:
                report['other_cgroups'][key]={**changes,'write_mib_s':changes['wbytes']/dt/2**20,'read_mib_s':changes['rbytes']/dt/2**20}
    report['mysql_observer_seconds_max']=max(x['mysql']['ended_at']-x['mysql']['started_at'] for x in data)
    progress=ROOT/(name+'-progress.jsonl')
    if progress.exists():
        samples=read(progress)
        rates=[(b['accepted']-a['accepted'])/(b['at']-a['at'])
               for a,b in zip(samples,samples[10:]) if a['elapsed']>1]
        report['throughput_10_sample_intervals']={'min':min(rates) if rates else None,
            'max':max(rates) if rates else None,'count':len(rates)}
    lifecycle=ROOT/(name+'-lifecycle.jsonl')
    if lifecycle.exists():report['lifecycle']=read(lifecycle)
    reports.append(report)
target=ROOT/'analysis.json';target.write_text(json.dumps(reports,indent=2)+'\n')
for r in reports:
    print(json.dumps({'name':r['name'],'accepted':r['load']['accepted'],'drained':r['load']['drained'],'lock_chains':r['lock_chains'],
        'data_io':{k:v for k,v in r['data_disks'].items() if k in ('sda','vda')},
        'nvme_io':{k:v for k,v in r['host_disks'].items() if k=='nvme0n1'},'observer_max_seconds':r['mysql_observer_seconds_max']}))
