#!/usr/bin/env python3
"""Medir HTTP e confirmacoes separadamente, com deltas de intervalos alinhados."""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics

root=Path(__file__).parent/'results/throughput'
spec=importlib.util.spec_from_file_location('io_analysis',Path(__file__).with_name('analyze-benchmark-io.py'))
io=importlib.util.module_from_spec(spec)
spec.loader.exec_module(io)


def read(path):
    return [json.loads(line.removeprefix('DS_METRIC ')) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def analyze(series):
    records=read(root/(series+'-load.jsonl'))
    assert records[-1]['status']=='series_passed'
    metrics_path=root/(series+'-metrics.txt')
    metrics=read(metrics_path) if metrics_path.exists() else []
    resources=read(root/(series+'-unit3d-ds-tracker.jsonl'))
    observations={h:read(root/(series+'-'+h+'.jsonl')) for h in ['data','host']}
    results=[]
    for run in records[:-1]:
        start=run['measured_at_epoch']; end=start+run['spec']['seconds']
        selected=[r for r in metrics if start<=r['at']<=end]
        item=dict(name=run['name'],rate=sum(g['rate'] for g in run['groups'].values()),
                  accepted=run['accepted'],http_rps=sum(g['completed_rps'] for g in run['groups'].values()),
                  response_ms=run['groups']['target']['response_read_ms'],
                  generator_queue_ms=run['groups']['target']['queue_wait_ms'],
                  generator_cpu=run['generator_cpu_percent'],drain_seconds=run['drain_seconds'])
        if len(selected)>=2:
            first,last=selected[0],selected[-1]; duration=last['at']-first['at']
            item['writer']=dict(committed_rps=(last['committed']-first['committed'])/duration,
                backlog_first=first['backlog'],backlog_last=last['backlog'],
                backlog_peak=max(r['backlog'] for r in selected),
                backlog_per_second=(last['backlog']-first['backlog'])/duration,
                retries=last['retries']-first['retries'],observed_seconds=duration)
            spans={}
            for key,a in first['metrics'].items():
                b=last['metrics'][key]; n=b['count']-a['count']; ns=b['ns']-a['ns']
                spans[key]=dict(count=n, mean_us=ns/n/1000 if n else None, seconds_per_second=ns/duration/1e9)
            item['spans']=spans
            item['writer']['batch_mean']=(last['committed']-first['committed'])/spans['persist']['count'] if spans['persist']['count'] else None
        cpu=[float(c['CPUPerc'].rstrip('%')) for r in resources if start<=r['at']<=end for c in r['containers'] if c['Name']=='unit3d-ds-rust']
        item['rust_cpu_percent']=dict(mean=statistics.mean(cpu),max=max(cpu)) if cpu else None
        item['io']={}
        for host,rows in observations.items():
            window=[r for r in rows if start<=r['at']<=end]
            if len(window)<2: continue
            item['io'][host]=io.summarize(rows,start,end)
            a,b=window[0],window[-1]
            # Linux destes convidados usa USER_HZ=100, registrado no ambiente.
            item['io'][host]['process_cpu_percent']={p['name']:(p['cpu_ticks']-a.get('processes',{}).get(pid,p)['cpu_ticks'])/(b['at']-a['at']) for pid,p in b.get('processes',{}).items() if pid in a.get('processes',{})}
            threads=[]
            for pid,p in b.get('processes',{}).items():
                old_threads=a.get('processes',{}).get(pid,{}).get('threads',{})
                for tid,t in p.get('threads',{}).items():
                    if tid in old_threads:
                        threads.append(dict(name=t['name'],cpu_percent=(t['cpu_ticks']-old_threads[tid]['cpu_ticks'])/(b['at']-a['at'])))
            if threads:
                item['io'][host]['top_database_threads']=sorted(threads,key=lambda t:t['cpu_percent'],reverse=True)[:10]
            if 'mysql' in a and 'statements' in a['mysql']:
                old={s['event']:s for s in a['mysql']['statements']}
                item['io'][host]['statements']={s['event']:{k:s[k]-old[s['event']][k] for k in ['count','wait_ps','lock_ps']} for s in b['mysql']['statements']}
        results.append(item)
    output=dict(series=series,accepted=records[-1]['accepted'],phases=results)
    (root/(series+'-analysis.json')).write_text(json.dumps(output,indent=2)+'\n')
    for r in results:
        print(json.dumps(dict(series=series,phase=r['name'],http=round(r['http_rps'],1),p99=r['response_ms']['p99'],drain=round(r['drain_seconds'],2),writer=r.get('writer'),rust_cpu=r['rust_cpu_percent'])))


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('series',nargs='+')
    for series in parser.parse_args().series:
        assert series.startswith('density-throughput-') and all(c.isalnum() or c=='-' for c in series)
        analyze(series)
