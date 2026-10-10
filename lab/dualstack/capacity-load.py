#!/usr/bin/env python3
"""Carga de capacidade em quatro processos; crédito auditado por identidade."""
import argparse
import asyncio
import collections
import importlib.util
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import socket
import sys
import time
import urllib.parse

BASE=Path('/opt/unit3d-dualstack')
sys.path[:0]=[str(BASE),str(BASE/'lab')]
from baseline import bdecode
from soak_metrics import Metrics, Histogram
import pymysql
DB='unit3d_dualstack_capacity_20261010'


def connect():
    values=dict(line.split('=',1) for line in (BASE/'database.env').read_text().splitlines())
    return pymysql.connect(host='172.29.92.20',user=values['MYSQL_USER'],password=values['MYSQL_PASSWORD'],database=DB,
        autocommit=True,connect_timeout=5,read_timeout=20,write_timeout=20,cursorclass=pymysql.cursors.DictCursor)


def audit(expected=None):
    with connect() as db,db.cursor() as c:
        c.execute('SELECT DATABASE() AS name');assert c.fetchone()['name']==DB
        c.execute('SELECT user_id,torrent_id,HEX(peer_id) AS peer_id,uploaded,state_version FROM peers');peers=c.fetchall()
        c.execute('SELECT user_id,torrent_id,uploaded,actual_uploaded FROM history');history=c.fetchall()
        c.execute('SELECT id,uploaded FROM users');users=c.fetchall()
        c.execute('SELECT COUNT(*) AS n,SUM(family=4) AS v4,SUM(family=6) AS v6,SUM(OCTET_LENGTH(ip)<>IF(family=4,4,16)) AS invalid FROM peer_ips');ips=c.fetchone()
        c.execute('SELECT COUNT(*) AS n FROM (SELECT user_id,torrent_id,peer_id FROM peer_ips GROUP BY user_id,torrent_id,peer_id HAVING COUNT(*)>2) x');over=c.fetchone()['n']
        c.execute('SELECT COUNT(*) AS n FROM torrents WHERE id IN (SELECT torrent_id FROM peers) AND (seeders<>200 OR leechers<>50 OR seeders_ipv4<>200 OR seeders_ipv6<>200 OR leechers_ipv4<>50 OR leechers_ipv6<>50)');counts_bad=c.fetchone()['n']
    result={'peers':len(peers),'versions':sum(int(p['state_version']) for p in peers),'credit':sum(int(p['uploaded']) for p in peers),
            'history_credit':sum(int(h['uploaded']) for h in history),'actual_credit':sum(int(h['actual_uploaded']) for h in history),
            'user_credit':sum(int(u['uploaded']) for u in users),'endpoints':{k:int(v or 0) for k,v in ips.items()},'over_limit':int(over),'bad_torrent_counts':int(counts_bad)}
    if expected is not None:
        by_history=collections.Counter();by_user=collections.Counter()
        for (u,t,_),value in expected.items():by_history[u,t]+=value;by_user[u]+=value
        result['mismatches']=sum(int(p['uploaded'])!=expected.get((p['user_id'],p['torrent_id'],p['peer_id']),0) for p in peers)
        result['mismatches']+=sum(any(int(h[k])!=by_history[h['user_id'],h['torrent_id']] for k in ('uploaded','actual_uploaded')) for h in history)
        result['mismatches']+=sum(int(u['uploaded'])!=by_user[u['id']] for u in users)
    return result


def child(number,lanes,rate,warmup,seconds,start,stop,counts,credits,results):
    async def run():
        metrics=Metrics();errors=collections.Counter();completed=0;max_lag=0.;offered=0
        total=int((warmup+seconds)*rate);workers=32;finish=start+warmup+seconds
        for p in lanes:
            query=urllib.parse.urlencode(dict(info_hash=p['info_hash'],peer_id=p['peer_id'],port=p['port'],uploaded=0,downloaded=0,left=0,event='completed',compact=1,numwant=10),quote_via=urllib.parse.quote)
            wire=('GET /announce/'+p['passkey']+'?'+query+' HTTP/1.1\r\nHost: tracker.lab\r\nUser-Agent: libtorrent/2.0.10\r\nConnection: keep-alive\r\n\r\n').encode()
            assert wire.count(b'uploaded=0&')==1
            p['wire']=wire.split(b'uploaded=0&');p['calls']=0;p['expected']=0
        async def worker(wid):
            nonlocal completed,max_lag,offered
            peers=lanes[wid::workers];conns={}
            try:
                for index in range(wid,total,workers):
                    if stop.is_set():break
                    scheduled=start+index/rate
                    await asyncio.sleep(max(0,scheduled-time.monotonic()))
                    if stop.is_set():break
                    began=time.monotonic();lag=began-scheduled;max_lag=max(max_lag,lag)
                    if lag>1:raise RuntimeError('generator_lag')
                    local=index//workers;p=peers[(local//2)%len(peers)];family=4 if local%2==0 else 6
                    if family not in conns:
                        dst,src=('172.29.92.10','172.29.92.30') if family==4 else ('fd42:756e:6974:92::10','fd42:756e:6974:92::30')
                        conns[family]=await asyncio.wait_for(asyncio.open_connection(dst,8081,local_addr=(src,0)),3)
                    reader,writer=conns[family];counter=((p['calls']//2)+1)*100;offered+=1
                    writer.write(p['wire'][0]+b'uploaded='+str(counter).encode()+b'&'+p['wire'][1]);await writer.drain()
                    header=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),3)
                    assert header.startswith(b'HTTP/1.1 200 '),'http_status'
                    h={k.lower():v.strip() for line in header.split(b'\r\n')[1:] if b':' in line for k,v in [line.split(b':',1)]}
                    size=int(h[b'content-length']);assert size<=4096,'payload_limit'
                    body=await asyncio.wait_for(reader.readexactly(size),3);received=time.monotonic();value=bdecode(body)
                    assert b'failure reason' not in value and b'warning message' not in value,'tracker_response'
                    assert value[b'complete']==200 and value[b'incomplete']==50,'torrent_counts'
                    assert len(value.get(b'peers',b''))==60 and len(value.get(b'peers6',b''))==180,'payload_size'
                    old=p['expected'];p['calls']+=1;p['expected']=counter
                    counts[number]+=1;credits[number]+=counter-old
                    if start+warmup<=received<finish:completed+=1
                    if scheduled>=start+warmup:metrics.add(scheduled,began,received,time.monotonic())
            except Exception as e:
                label=str(e) if isinstance(e,(AssertionError,RuntimeError)) else type(e).__name__
                errors[label]+=1;stop.set()
            finally:
                for _,writer in conns.values():writer.close()
        await asyncio.gather(*(worker(i) for i in range(workers)))
        results.put({'number':number,'errors':dict(errors),'offered':offered,'completed':completed,'max_lag':max_lag,
                     'expected':{(p['user_id'],p['torrent_id'],p['peer_id'].hex().upper()):p['expected'] for p in lanes},
                     'histograms':{k:(list(h.bins),h.n,h.maximum) for k,h in metrics.histograms.items()}})
    try:asyncio.run(run())
    except Exception as e:
        stop.set();results.put({'number':number,'fatal':type(e).__name__})


def main(args):
    assert socket.gethostname()=='unit3d-ds-clients' and os.geteuid()==0
    assert args.name.replace('-','').isalnum() and 100<=args.rate<=40000 and args.rate%4==0
    assert 0<=args.warmup<=300 and 5<=args.seconds<=900
    folder=Path('/mnt/unit3d-archive/results/capacity')/args.name;folder.mkdir(parents=True,exist_ok=True)
    assert not (folder/'result.json').exists() and not (folder/'progress.json').exists()
    before=audit();assert before['peers']==10000 and before['versions']==before['credit']==0 and before['endpoints']['n']==20000,'fixture'
    with connect() as db,db.cursor() as c:
        c.execute('SELECT p.user_id,p.torrent_id,p.peer_id,p.port,u.passkey,t.info_hash FROM peers p JOIN users u ON u.id=p.user_id JOIN torrents t ON t.id=p.torrent_id WHERE p.seeder=1 ORDER BY p.user_id,p.torrent_id')
        lanes=c.fetchall()
    random.Random(9137).shuffle(lanes)
    ctx=mp.get_context('fork');stop=ctx.Event();counts=ctx.Array('Q',4,lock=False);credits=ctx.Array('Q',4,lock=False);results=ctx.Queue()
    start=time.monotonic()+2;epoch=time.time()+start-time.monotonic()
    children=[ctx.Process(target=child,args=(i,lanes[i::4],args.rate//4,args.warmup,args.seconds,start,stop,counts,credits,results)) for i in range(4)]
    for p in children:p.start()
    result_rows=[];reason=None
    with (folder/'progress.jsonl').open('x') as log:
        while len(result_rows)<4:
            if (folder/'stop').exists():reason='supervisor_stop';stop.set()
            row={'at':time.time(),'start_epoch':epoch,'elapsed':time.monotonic()-start,'accepted':sum(counts),'expected_credit':sum(credits),'rate':args.rate,'warmup':args.warmup,'seconds':args.seconds}
            log.write(json.dumps(row)+'\n');log.flush()
            temp=folder/'progress.partial';temp.write_text(json.dumps(row));os.replace(temp,folder/'progress.json')
            try:result_rows.append(results.get(timeout=1))
            except Exception:
                if time.monotonic()>start+args.warmup+args.seconds+20:
                    reason='worker_timeout';stop.set();break
                if any(p.exitcode not in (None,0) for p in children):reason='worker_exit';stop.set();break
    for p in children:
        p.join(5)
        if p.is_alive():p.terminate();p.join();reason='worker_timeout'
    assert len(result_rows)==4 and not any('fatal' in r for r in result_rows),'worker_failed'
    expected={k:v for r in result_rows for k,v in r['expected'].items()};errors=collections.Counter()
    metrics=Metrics()
    for r in result_rows:
        errors.update(r['errors'])
        for k,(bins,n,maximum) in r['histograms'].items():
            h=metrics.histograms[k];h.n+=n;h.maximum=max(h.maximum,maximum)
            for i,value in enumerate(bins):h.bins[i]+=value
    accepted=sum(counts);credit=sum(expected.values());drain=time.monotonic()
    while True:
        after=audit(expected)
        drained=after['versions']==accepted and after['mismatches']==0 and all(after[k]==credit for k in ('credit','history_credit','actual_credit','user_credit'))
        if drained or time.monotonic()-drain>90:break
        time.sleep(.5)
    correct=drained and after['endpoints']=={'n':20000,'v4':10000,'v6':10000,'invalid':0} and after['over_limit']==after['bad_torrent_counts']==0
    data={'name':args.name,'start_epoch':epoch,'measured_at':epoch+args.warmup,'finish_epoch':epoch+args.warmup+args.seconds,
          'rate':args.rate,'seconds':args.seconds,'warmup':args.warmup,'accepted':accepted,'expected_credit':credit,
          'completed_rps':sum(r['completed'] for r in result_rows)/args.seconds,'errors':dict(errors),'stop_reason':reason,
          'max_generator_lag':max(r['max_lag'] for r in result_rows),'metrics':metrics.summary(),'after':after,
          'drained':drained,'drain_seconds':time.monotonic()-drain,'accounting_passed':correct,
          'status':'passed' if correct and not errors and not reason else 'limited' if correct else 'failed'}
    (folder/'result.json').write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(data))
    assert correct,'accounting_failed'


if __name__=='__main__':
    os.umask(0o077)
    p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('--rate',type=int,required=True);p.add_argument('--seconds',type=int,required=True);p.add_argument('--warmup',type=int,default=20)
    try:main(p.parse_args())
    except Exception as e:
        print(json.dumps({'status':'failed','type':type(e).__name__,'reason':str(e) if isinstance(e,AssertionError) else 'diagnostico_local'}));raise SystemExit(1)
