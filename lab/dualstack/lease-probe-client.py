#!/usr/bin/env python3
"""Carga limitada em banco novo; não exporta passkeys nem amostras privadas."""
import argparse
import asyncio
import collections
import json
import math
import os
from pathlib import Path
import random
import socket
import sys
import time
import urllib.parse

import pymysql

BASE=Path('/opt/unit3d-dualstack')
sys.path.insert(0,str(BASE))
sys.path.insert(0,str(BASE/'lab'))
from baseline import bdecode
from soak_metrics import Metrics

DB='unit3d_dualstack_probe_20261009'


def connect():
    values=dict(line.split('=',1) for line in (BASE/'database.env').read_text().splitlines())
    return pymysql.connect(host='172.29.92.20',user=values['MYSQL_USER'],password=values['MYSQL_PASSWORD'],
        database=DB,autocommit=True,connect_timeout=5,read_timeout=15,write_timeout=15,
        cursorclass=pymysql.cursors.DictCursor)


def snapshot(expected=None):
    with connect() as db,db.cursor() as c:
        c.execute('SELECT DATABASE() AS name');assert c.fetchone()['name']==DB
        c.execute('SELECT user_id,torrent_id,HEX(peer_id) AS peer_id,state_version,uploaded FROM peers')
        peers=c.fetchall()
        checks={}
        for table,fields in [('peers','COUNT(*) AS n,SUM(uploaded) AS credit,SUM(state_version) AS versions'),
                             ('history','COUNT(*) AS n,SUM(uploaded) AS credit,SUM(actual_uploaded) AS actual'),
                             ('users','COUNT(*) AS n,SUM(uploaded) AS credit'),('peer_ips','COUNT(*) AS n')]:
            c.execute('SELECT '+fields+' FROM '+table)
            checks[table]={k:int(v or 0) for k,v in c.fetchone().items()}
        if expected is not None:
            checks['mismatches']=sum(int(p['uploaded'])!=expected.get((p['user_id'],p['torrent_id'],p['peer_id']),0) for p in peers)
        return checks


async def run(args):
    assert os.geteuid()==0 and socket.gethostname()=='unit3d-ds-clients'
    assert 1<=args.seconds<=180 and 1<=args.rate<=8000 and args.block in (0,1,9)
    assert args.block==0 or args.one_peer
    assert args.name.replace('-','').isalnum()
    folder=Path('/mnt/unit3d-archive/results/lease-probe')/args.name
    folder.mkdir(parents=True,exist_ok=False)
    os.umask(0o077)
    for target in ('172.29.92.10','fd42:756e:6974:92::10'):
        r,w=await asyncio.wait_for(asyncio.open_connection(target,8081),5);w.close();await w.wait_closed()
    before=await asyncio.to_thread(snapshot)
    assert before['peers']['n']==10000 and before['peers']['credit']==0 and before['peers']['versions']==0
    with connect() as db,db.cursor() as c:
        c.execute('SELECT p.user_id,p.torrent_id,p.peer_id,p.port,u.passkey,t.info_hash FROM peers p JOIN users u ON u.id=p.user_id JOIN torrents t ON t.id=p.torrent_id WHERE p.seeder=1 ORDER BY p.user_id,p.torrent_id')
        lanes=c.fetchall()
    if args.one_peer:lanes=lanes[:1]
    else:random.Random(9137).shuffle(lanes)
    for p in lanes:
        params=dict(info_hash=p['info_hash'],peer_id=p['peer_id'],port=p['port'],uploaded=0,downloaded=0,left=0,event='completed',compact=1,numwant=10)
        path='/announce/'+p['passkey']+'?'+urllib.parse.urlencode(params,quote_via=urllib.parse.quote)
        wire=('GET '+path+' HTTP/1.1\r\nHost: tracker.lab\r\nUser-Agent: libtorrent/2.0.10\r\nConnection: keep-alive\r\n\r\n').encode()
        assert wire.count(b'uploaded=0&')==1
        p['wire']=wire.split(b'uploaded=0&');p['calls']=0;p['expected']=0
    holder=None;release=None;blocker={}
    if args.block:
        holder=connect();holder.begin()
        with holder.cursor() as c:
            c.execute('SELECT CONNECTION_ID() AS id');blocker['connection']=c.fetchone()['id']
            c.execute('SELECT id FROM users WHERE id=%s FOR UPDATE',(lanes[0]['user_id'],));assert c.fetchone()
        blocker['acquired_at']=time.time()
        async def unblock():
            await asyncio.sleep(args.block)
            await asyncio.to_thread(holder.rollback)
            blocker['released_at']=time.time()
        release=asyncio.create_task(unblock())
    workers=1 if args.one_peer else 64
    assert len(lanes)>=workers
    start=time.monotonic()+.15
    metrics=Metrics();errors=collections.Counter();accepted=0;done=False;maximum_lag=0.
    public={'name':args.name,'rate':args.rate,'seconds':args.seconds,'block_seconds':args.block,'one_peer':args.one_peer,'started_at':time.time(),'before':before,'blocker':blocker}
    def progress():
        return {'at':time.time(),'accepted':accepted,'errors':dict(errors),'elapsed':max(0,time.monotonic()-start),'blocker':blocker}
    async def reporter():
        while not done:
            (folder/'progress.json').write_text(json.dumps(progress()))
            with (folder/'progress.jsonl').open('a') as f:f.write(json.dumps(progress())+'\n')
            await asyncio.sleep(1)
    async def worker(number):
        nonlocal accepted,maximum_lag
        peers=lanes[number::workers];connections={}
        total=int(args.rate*args.seconds)
        try:
            for index in range(number,total,workers):
                if errors:break
                local=index//workers
                p=peers[(local//2)%len(peers)];family=4 if local%2==0 else 6
                scheduled=start+index/args.rate
                await asyncio.sleep(max(0,scheduled-time.monotonic()))
                maximum_lag=max(maximum_lag,time.monotonic()-scheduled)
                if maximum_lag>1:raise RuntimeError('gerador_atrasado')
                if family not in connections:
                    target,source=('172.29.92.10','172.29.92.30') if family==4 else ('fd42:756e:6974:92::10','fd42:756e:6974:92::30')
                    connections[family]=await asyncio.wait_for(asyncio.open_connection(target,8081,local_addr=(source,0)),3)
                reader,writer=connections[family]
                counter=((p['calls']//2)+1)*100
                began=time.monotonic()
                writer.write(p['wire'][0]+b'uploaded='+str(counter).encode()+b'&'+p['wire'][1]);await writer.drain()
                header=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),3)
                fields={k.lower():v.strip() for line in header.split(b'\r\n')[1:] if b':' in line for k,v in [line.split(b':',1)]}
                assert header.startswith(b'HTTP/1.1 200 '),'http_status'
                length=int(fields[b'content-length']);assert length<=4096
                body=await asyncio.wait_for(reader.readexactly(length),3);received=time.monotonic()
                value=bdecode(body)
                assert b'failure reason' not in value and b'warning message' not in value,'tracker_response'
                assert len(value[b'peers'])%6==0 and len(value.get(b'peers6',b''))%18==0,'payload_format'
                assert len(value[b'peers'])+len(value.get(b'peers6',b''))<=240,'payload_limit'
                p['calls']+=1;p['expected']=counter;accepted+=1
                metrics.add(scheduled,began,received,time.monotonic())
        except Exception as error:
            label=str(error) if isinstance(error,(AssertionError,RuntimeError)) else type(error).__name__
            errors[label]+=1
        finally:
            for _,writer in connections.values():writer.close()
    task=asyncio.create_task(reporter())
    try:
        await asyncio.gather(*(worker(i) for i in range(workers)))
        if release:await release
    finally:
        if holder:holder.rollback();holder.close()
        done=True;await task
    expected={(p['user_id'],p['torrent_id'],p['peer_id'].hex().upper()):p['expected'] for p in lanes}
    expected_credit=sum(expected.values());drain_start=time.monotonic()
    while True:
        after=await asyncio.to_thread(snapshot,expected)
        drained=after['peers']['versions']==accepted and all(after[t]['credit']==expected_credit for t in ('peers','history','users')) and after['mismatches']==0
        if drained or errors or time.monotonic()-drain_start>30:break
        await asyncio.sleep(.2)
    public.update(accepted=accepted,errors=dict(errors),ended_at=time.time(),maximum_schedule_lag=maximum_lag,
        expected_credit=expected_credit,after=after,drained=drained,drain_seconds=time.monotonic()-drain_start,
        metrics=metrics.summary(),blocker=blocker,unpersisted_versions=accepted-after['peers']['versions'])
    (folder/'result.json').write_text(json.dumps(public,indent=2)+'\n')
    print(json.dumps(public),flush=True)
    if args.block==9 and not args.expect_recovery:
        assert errors and not drained and public['unpersisted_versions']>0,'falha_esperada_nao_reproduzida'
    else:
        assert not errors and drained and after['peer_ips']['n']==20000,'controle_reprovado'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('--rate',type=int,required=True)
    p.add_argument('--seconds',type=int,required=True);p.add_argument('--block',type=int,default=0);p.add_argument('--one-peer',action='store_true')
    p.add_argument('--database',choices=(DB,'unit3d_dualstack_recovery_test'),default=DB)
    p.add_argument('--expect-recovery',action='store_true')
    args=p.parse_args();DB=args.database
    try:asyncio.run(run(args))
    except Exception as error:
        print(json.dumps({'status':'failed','type':type(error).__name__,'reason':str(error) if isinstance(error,(AssertionError,RuntimeError)) else 'ver_log_local'}));raise SystemExit(1)
