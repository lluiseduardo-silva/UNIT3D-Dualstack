#!/usr/bin/env python3
"""Resume as séries públicas de capacidade; sem extrapolar IOPS de outro hardware."""
import argparse
import json
from pathlib import Path
import statistics


def process(rows,name):
    series=[]
    for r in rows:
        ps=[p for p in r['processes'].values() if p['name']==name]
        if ps:series.append((r['at'],sum(p['cpu_ticks'] for p in ps),sum(p['rss'] for p in ps),sum(p.get('pss',0) for p in ps)))
    if len(series)<2:return None
    dt=series[-1][0]-series[0][0]
    return {'cpu_one_core_percent':(series[-1][1]-series[0][1])/dt/rows[0]['clk_tck']*100,
            'rss_median_mib':statistics.median(x[2] for x in series)/2**20,'rss_max_mib':max(x[2] for x in series)/2**20,
            'pss_median_mib':statistics.median(x[3] for x in series)/2**20 if any(x[3] for x in series) else None}


def mysql(row):
    result={}
    for line in row.get('mysql',[]):
        f=line.split('\t')
        if len(f)==2:
            try:result[f[0]]=float(f[1])
            except ValueError:pass
        elif f[0]=='persisted':result.update(versions=int(f[1]),credit=int(f[2]))
    return result


def mysql_waits(rows):
    def parse(row):
        return {f[0]:list(map(int,f[1:])) for line in row.get('mysql',[]) if (f:=line.split('\t'))[0].startswith(('wait/io/file/','statement/sql/'))}
    first,last=parse(rows[0]),parse(rows[-1]);values={}
    for key,a in first.items():
        if key not in last:continue
        delta=[b-v for v,b in zip(a,last[key])]
        if min(delta)<0:continue
        values[key]={'count':delta[0],'wait_seconds':delta[1]/1e12,
                     'average_wait_ms':delta[1]/1e9/delta[0] if delta[0] else None}
        if key.startswith('wait/'):
            values[key].update(read_operations=delta[2],read_bytes=delta[3],write_operations=delta[4],write_bytes=delta[5])
        else:values[key]['lock_seconds']=delta[2]/1e12
    return values


def disk_summary(a,b,dt):
    d=[y-x for x,y in zip(a,b)]
    return {'read_iops':d[0]/dt,'write_iops':d[4]/dt,'read_mib_s':d[2]*512/dt/2**20,
        'write_mib_s':d[6]*512/dt/2**20,'read_await_ms':d[3]/d[0] if d[0] else 0,
        'write_await_ms':d[7]/d[4] if d[4] else 0,'average_queue':d[10]/1000/dt,'busy_percent':d[9]/10/dt,
        'flush_iops':d[15]/dt if len(d)>16 else None,'flush_await_ms':d[16]/d[15] if len(d)>16 and d[15] else None}


def role_summary(rows,role):
    if len(rows)<2:return {'samples':len(rows)}
    first,last=rows[0],rows[-1];dt=last['at']-first['at']
    delta=[b-a for a,b in zip(first['cpu'],last['cpu'])];cpu_sum=sum(delta[:8])
    result={'samples':len(rows),'seconds_observed':dt,
        'cpu_busy_percent':100*(cpu_sum-delta[3]-delta[4])/cpu_sum,
        'cpu_iowait_percent':100*delta[4]/cpu_sum,'cpu_steal_percent':100*delta[7]/cpu_sum,
        'minimum_memory_available_mib':min(r['memory']['MemAvailable'] for r in rows)/2**20,
        'process':process(rows,{'tracker':'unit3d-announce','data':'mysqld','clients':'python3'}.get(role,''))}
    if role=='proxmox':
        result['physical_ssd']=disk_summary(first['disks']['nvme0n1'],last['disks']['nvme0n1'],dt)
    if role=='data':
        result['disk']=disk_summary(first['disks']['sda'],last['disks']['sda'],dt)
        result['mysql_waits']=mysql_waits(rows)
        m0,m1=mysql(first),mysql(last);diff={k:m1[k]-v for k,v in m0.items() if k in m1}
        result['mysql_deltas']=diff
        confirmed=diff.get('versions',0)/dt
        result['confirmed_per_second']=confirmed
        result['redo_mib_s']=diff.get('Innodb_os_log_written',0)/dt/2**20
        if confirmed>0:
            result['write_ops_per_1000_confirmed']=result['disk']['write_iops']/confirmed*1000
            result['redo_bytes_per_confirmed']=diff.get('Innodb_os_log_written',0)/diff['versions']
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('series');args=p.parse_args()
    folder=args.root/'supervisor/capacity'/args.series
    output={'series':args.series,'status':json.loads((folder/'status.json').read_text()),'trials':[],
            'limits':['taxa confirmada e IOPS pertencem ao perfil observado','latência e fila do disco são médias por janela, não percentis de fsync','não estima ganho com SSD mais rápido','CPU do gerador soma processos presentes; reinícios invalidam esse delta']}
    for path in sorted(folder.glob('*-result.json')):
        result=json.loads(path.read_text());name=result['name'];roles={}
        for role in ('tracker','data','clients','proxmox'):
            file=(args.root/'supervisor/capacity' if role=='proxmox' else args.root/role/'results/capacity')/name/(role+'-observer.jsonl')
            rows=[json.loads(line) for line in file.read_text().splitlines()]
            measured=[r for r in rows if result['measured_at']<=r['at']<=result['finish_epoch']]
            roles[role]=role_summary(measured,role)
        output['trials'].append({'result':result,'resources':roles})
    (folder/'summary.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps({'series':args.series,'trials':len(output['trials']),'path':str(folder/'summary.json')}))


if __name__=='__main__':main()
