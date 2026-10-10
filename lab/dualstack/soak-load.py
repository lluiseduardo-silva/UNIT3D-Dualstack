#!/usr/bin/env python3
"""Carga prolongada com origens reais, auditoria por janela e coleta limitada."""
import argparse
import asyncio
import collections
import datetime
import ipaddress
import json
import os
from pathlib import Path
import random
import resource
import signal
import socket
import sys
import time
import urllib.parse

sys.path.insert(0,'/opt/unit3d-dualstack')
from density_common import BASE, bdecode, connect, snapshot
from soak_metrics import Metrics, Samples, RECORD
from soak_diagnostics import ResponseFailure

ROOT = Path('/mnt/unit3d-archive/results/soak')


def save(path, data):
    tmp = path.with_suffix('.partial')
    tmp.write_text(json.dumps(data, sort_keys=True)+'\n')
    os.replace(tmp, path)


def audit(lanes, missing6, elapsed):
    expected = {(p['user_id'], p['torrent_id']): p['observed'] for p in lanes}
    by_id = {(p['user_id'],p['torrent_id']):p for p in lanes}
    totals = collections.Counter()
    for (user, _), value in expected.items():
        totals[user] += value
    with connect() as db, db.cursor() as c:
        c.execute('SELECT p.user_id,p.torrent_id,p.uploaded,p.state_version,h.actual_uploaded,h.uploaded AS credited,h.seedtime FROM peers p JOIN history h USING(user_id,torrent_id) WHERE p.user_id>=20000')
        peers = c.fetchall()
        c.execute('SELECT id,uploaded,seedbonus FROM users WHERE id>=20000')
        users = c.fetchall()
        c.execute('SELECT COUNT(*) AS n FROM peer_ips WHERE user_id>=20000')
        endpoints = int(c.fetchone()['n'])
        c.execute('SELECT COUNT(*) AS n FROM (SELECT user_id,torrent_id,peer_id,COUNT(*) AS n FROM peer_ips WHERE user_id>=20000 GROUP BY user_id,torrent_id,peer_id HAVING n>2) s')
        assert c.fetchone()['n'] == 0, 'endpoint_limit'
        c.execute('SELECT id,seeders,leechers,seeders_ipv4,seeders_ipv6,leechers_ipv4,leechers_ipv6,times_completed FROM torrents WHERE id>=20000')
        torrents=c.fetchall()
        last_torrent=max(p['torrent_id'] for p in lanes)
        c.execute('SELECT user_id,family,INET6_NTOA(ip) AS ip,port FROM peer_ips WHERE torrent_id=%s AND user_id IN (20000,20001,20002)',(last_torrent,))
        control_endpoints=c.fetchall()
    assert len(peers) == len(expected) and endpoints == 2*len(expected)-int(missing6), 'identity_or_endpoint_count'
    assert all(all(int(p[k]) == expected[(p['user_id'],p['torrent_id'])] for k in ['uploaded','actual_uploaded','credited']) for p in peers), 'peer_credit_mismatch'
    assert all(int(u['uploaded']) == totals[u['id']] and float(u['seedbonus']) == 0 for u in users), 'user_credit_mismatch'
    assert all(0 <= int(p['seedtime']) <= elapsed+10 for p in peers), 'seedtime_bound'
    for row in peers:
        p=by_id[(row['user_id'],row['torrent_id'])]
        extra=int(row['state_version'])-p['accepted']
        assert extra==0 or (p.get('expiry_control') and elapsed>=p['expiry_ttl'] and extra==1),'peer_version_mismatch'
    for endpoint in control_endpoints:
        p=by_id[(endpoint['user_id'],last_torrent)]
        assert ipaddress.ip_address(endpoint['ip'])==ipaddress.ip_address(p['ipv'+str(endpoint['family'])]) and endpoint['port']==p['port'],'control_endpoint_mismatch'
    for t in torrents:
        members=[p for p in lanes if p['torrent_id']==t['id']]
        seeds=sum(p['seeder'] for p in members);leech=len(members)-seeds
        expected_counts={'seeders':seeds,'seeders_ipv4':seeds,'seeders_ipv6':seeds-int(missing6 and any(p.get('expiry_control') for p in members)),
                         'leechers':leech,'leechers_ipv4':leech,'leechers_ipv6':leech,'times_completed':0}
        assert all(int(t[k])==v for k,v in expected_counts.items()),'torrent_count_mismatch'
    return {'peers': len(peers), 'endpoints': endpoints, 'users': len(users), 'credit': sum(totals.values())}


class Load:
    def __init__(self, plan):
        self.plan = plan
        self.folder = ROOT / plan['name']
        self.folder.mkdir(parents=True, exist_ok=False)
        self.fixture = json.loads((BASE/'density-fixture.json').read_text())
        assert self.fixture['name'] == plan['name'] and self.fixture['sizes'] == plan['sizes']
        self.lanes = self.fixture['lanes']
        for p in self.lanes:
            p.update(sent=0, observed=0, accepted=0)
            query = urllib.parse.urlencode(dict(info_hash=bytes.fromhex(p['info_hash']), peer_id=bytes.fromhex(p['peer_id']),
                port=p['port'], uploaded=0, downloaded=0, left=0, event='completed', compact=1, numwant=10), quote_via=urllib.parse.quote)
            wire=('GET /announce/'+p['passkey']+'?'+query+' HTTP/1.1\r\nHost: tracker.lab\r\nUser-Agent: libtorrent/2.0.10\r\nConnection: keep-alive\r\n\r\n').encode()
            assert wire.count(b'uploaded=0&') == 1
            p['wire'] = wire.split(b'uploaded=0&')
        self.controls = [p for p in self.lanes if p['torrent_slot'] == len(plan['sizes'])-1 and p['user_slot'] in (0,1,2)]
        assert len(self.controls) == 3
        self.controls[2].update(expiry_control=plan.get('natural_expiry',True),expiry_ttl=plan['ttl'])
        self.seeders = [p for p in self.lanes if p['seeder'] and p not in self.controls]
        random.Random(9137).shuffle(self.seeders)
        self.slots = [(p,f) for p in self.seeders for f in (4,6)]
        self.leechers = [p for p in self.lanes if not p['seeder']]
        self.eligible = {}
        for p in self.leechers:
            for f in (4,6):
                wire=ipaddress.ip_address(p['ipv'+str(f)]).packed+p['port'].to_bytes(2,'big')
                self.eligible[(p['torrent_slot'],f,wire)] = p['user_id']
        self.samples = Samples(self.folder/'samples')
        save(self.folder/'sample-format.json', {'struct':RECORD.format,'record_bytes':RECORD.size,
            'fields':['index','family','event_0_completed_1_started_2_stopped','uploaded','scheduled','began','received','ended','payload_bytes','ok'],
            'time_unit':'seconds since monotonic origin','histogram_error':'<=0.1% + 1 microsecond'})
        save(self.folder/'identities.json', [{'index':p['index'],'user_id':p['user_id'],'torrent_id':p['torrent_id'],'peer_id_hex':p['peer_id']} for p in self.lanes])
        self.origin = time.monotonic()
        self.created = datetime.datetime.fromisoformat(self.fixture['created_at']).replace(tzinfo=datetime.timezone.utc).timestamp()
        self.accepted = self.main_accepted = self.errors = self.sequence = 0
        self.stop = False
        self.expired = False
        self.expiry_checked = False
        self.restored = False
        self.missing6 = False
        self.expire_at = self.created + plan['ttl']
        self.connections = {}
        self.metrics = Metrics()
        self.progress_lock=asyncio.Lock()
        self.heartbeat_stop=False
        self.error_details=[]

    async def progress(self, status='running', **extra):
        async with self.progress_lock:
            self.sequence += 1
            data=dict(sequence=self.sequence,status=status,accepted=self.accepted,
                main_accepted=self.main_accepted,errors=self.errors,elapsed_seconds=time.monotonic()-self.origin,
                rss_peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                sample_queue=self.samples.queue.qsize(),sample_count=self.samples.count,
                error_details=self.error_details,**extra)
            # Metadata I/O must not stall the HTTP event loop either.
            await asyncio.to_thread(save,self.folder/'progress.json',data)

    async def announce(self, p, family, counter, pool, numwant=10, event='completed', complete=None):
        address = p['ipv'+str(family)]
        key = (address,family)
        if key not in pool:
            target = '172.29.92.10' if family == 4 else 'fd42:756e:6974:92::10'
            pool[key] = await asyncio.open_connection(target,8080,family=socket.AF_INET if family==4 else socket.AF_INET6,local_addr=(address,0))
        reader,writer = pool[key]
        if numwant == 10 and event == 'completed':
            wire=p['wire'][0]+b'uploaded='+str(counter).encode()+b'&'+p['wire'][1]
        else:
            query=urllib.parse.urlencode(dict(info_hash=bytes.fromhex(p['info_hash']),peer_id=bytes.fromhex(p['peer_id']),
                port=p['port'],uploaded=counter,downloaded=0,left=0 if p['seeder'] else 16777216,event=event,compact=1,numwant=numwant),quote_via=urllib.parse.quote)
            wire=('GET /announce/'+p['passkey']+'?'+query+' HTTP/1.1\r\nHost: tracker.lab\r\nUser-Agent: libtorrent/2.0.10\r\nConnection: keep-alive\r\n\r\n').encode()
        writer.write(wire)
        await writer.drain()
        head=await reader.readuntil(b'\r\n\r\n')
        status=int(head.split(b' ',2)[1])
        headers={r.split(b':',1)[0].lower():r.split(b':',1)[1].strip() for r in head.split(b'\r\n')[1:] if b':' in r}
        if b'content-length' in headers:
            body=await reader.readexactly(int(headers[b'content-length']))
        else:
            assert headers.get(b'transfer-encoding') == b'chunked','framing'
            chunks=[]
            while True:
                length=int((await reader.readline()).split(b';',1)[0],16)
                if not length:
                    assert await reader.readline()==b'\r\n'
                    break
                chunks.append(await reader.readexactly(length))
                assert await reader.readexactly(2)==b'\r\n'
            body=b''.join(chunks)
        received=time.monotonic()
        if headers.get(b'connection')==b'close':
            writer.close();pool.pop(key)
        try:result=bdecode(body)
        except Exception:raise ResponseFailure(status,body) from None
        if status!=200 or not isinstance(result,dict) or b'failure reason' in result or b'warning message' in result:
            raise ResponseFailure(status,body,result)
        self.validate_response(p,result,numwant,complete)
        self.accepted+=1
        p['accepted']+=1
        p['observed']=max(p['observed'],counter)
        return received,len(body)

    def validate_response(self,p,result,numwant,complete):
        size=self.fixture['sizes'][p['torrent_slot']]
        assert result[b'complete']==(size*4//5 if complete is None else complete) and result[b'incomplete']==size//5,'counts'
        v4,v6=result.get(b'peers',b''),result.get(b'peers6',b'')
        assert len(v4)==6*numwant and len(v6)==18*numwant,'payload_size'
        if numwant:
            ids=[]
            for f,compact,width in [(4,v4,6),(6,v6,18)]:
                selected={self.eligible[(p['torrent_slot'],f,compact[o:o+width])] for o in range(0,len(compact),width)}
                assert len(selected)==numwant,'duplicate_endpoint'
                ids.append(selected)
            assert ids[0]==ids[1],'unpaired_endpoints'

    async def control(self,p,f,event='completed',complete=None):
        start=time.monotonic()
        received,size=await asyncio.wait_for(self.announce(p,f,0,self.connections,0,event,complete),5)
        self.samples.add(p['index'],f,{'completed':0,'started':1,'stopped':2}[event],0,
                         start-self.origin,start-self.origin,received-self.origin,time.monotonic()-self.origin,size,True)

    async def maintenance(self,number):
        # Refresh resident leechers with their actual left=16 MiB and no traffic credit.
        batches=[[p for p in self.leechers if p['user_slot']%72==i] for i in range(72)]
        async def refresh(batch):
            for p in batch:
                await self.control(p,4)
                await self.control(p,6)
        await asyncio.gather(*(refresh(batch) for batch in batches))
        rotate,session,expire=self.controls
        if self.plan.get('churn',True):
            old=rotate['ipv6']
            rotate['ipv6']='fd42:756e:6974:92::'+format(0xa000+number%32,'x')
            await self.control(rotate,6)
            # Close old TCP connections; changing IP must not grow the pool.
            pair=self.connections.pop((old,6),None)
            if pair:pair[1].close()
            await self.control(rotate,4)
            await self.control(session,4,'stopped')
            await self.control(session,6,'stopped',self.fixture['sizes'][-1]*4//5-1)
            await self.control(session,4,'started')
            await self.control(session,6,'started')
        else:
            for p in (rotate,session):
                for f in (4,6):await self.control(p,f)
        await self.control(expire,4)
        if not self.plan.get('natural_expiry',True):
            await self.control(expire,6)
        elif time.time()>self.expire_at+70 and not self.restored:
            with connect() as db,db.cursor() as c:
                c.execute('SELECT family FROM peer_ips WHERE user_id=%s AND torrent_id=%s',(expire['user_id'],expire['torrent_id']))
                assert [r['family'] for r in c.fetchall()]==[4],'ipv6_not_expired_independently'
            self.expiry_checked=True
            await self.control(expire,6)
            self.restored=True
        elif self.restored:
            await self.control(expire,6)

    async def window(self,seconds,number):
        metrics=Metrics()
        queues=[asyncio.Queue(maxsize=128) for _ in range(72)]
        pools=[{} for _ in range(72)]
        start=time.monotonic()+.1
        finish=start+seconds
        completed=0
        before=self.main_accepted
        async def worker(index):
            nonlocal completed
            while True:
                item=await queues[index].get()
                try:
                    if item is None:return
                    p,f,counter,scheduled=item
                    began=time.monotonic()
                    received,size=await asyncio.wait_for(self.announce(p,f,counter,pools[index]),5)
                    ended=time.monotonic()
                    self.main_accepted+=1
                    completed+=int(received<finish)
                    metrics.add(scheduled,began,received,ended)
                    self.samples.add(p['index'],f,0,counter,scheduled-self.origin,began-self.origin,received-self.origin,ended-self.origin,size,True)
                except Exception as error:
                    self.record_error(error,family=f if item is not None else None)
                    self.errors+=1;self.stop=True
                    raise
                finally:queues[index].task_done()
        tasks=[asyncio.create_task(worker(i)) for i in range(72)]
        try:
            for i in range(int(seconds*self.plan['rate'])):
                if self.stop:break
                if any(t.done() for t in tasks):
                    await asyncio.gather(*(t for t in tasks if t.done()))
                scheduled=start+i/self.plan['rate']
                await asyncio.sleep(max(0,scheduled-time.monotonic()))
                p,f=self.slots[i%len(self.slots)]
                p['sent']+=1
                counter=self.counter(p)
                queues[p['user_slot']%72].put_nowait((p,f,counter,scheduled))
            for q in queues:await asyncio.wait_for(q.put(None),10)
            await asyncio.wait_for(asyncio.gather(*tasks),15)
        finally:
            for t in tasks:
                if not t.done():t.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            for pool in pools:
                for _,writer in pool.values():writer.close()
        elapsed=time.monotonic()-start
        report={'window':number,'at':time.time(),'seconds':seconds,'elapsed':elapsed,'accepted':self.main_accepted-before,
                'completed_rps':completed/seconds,'metrics':metrics.summary(),'errors':self.errors}
        with (self.folder/'windows.jsonl').open('a') as f:f.write(json.dumps(report)+'\n')
        if not self.stop:
            assert report['completed_rps']>=self.plan['rate']*.95,'window_throughput'
        return report

    def counter(self,p):
        return ((p['sent']+1)//2)*100

    async def heartbeat(self):
        while not self.heartbeat_stop:
            await self.progress()
            await asyncio.sleep(2)

    def record_error(self,error,**context):
        if len(self.error_details)<16:
            self.error_details.append(dict(elapsed_seconds=time.monotonic()-self.origin,
                error_type=type(error).__name__,**getattr(error,'public',{}),**context))

    async def inject_write_pause(self):
        fault=self.plan['write_pause']
        assert self.plan['seconds']<=300 and fault=={'at':30,'seconds':4}
        await asyncio.sleep(max(0,self.origin+fault['at']-time.monotonic()))
        def block():
            with connect() as db,db.cursor() as cursor:
                cursor.execute('SELECT id FROM users WHERE id=20000 FOR UPDATE')
                assert cursor.fetchone()['id']==20000
                acquired=time.monotonic()
                data={'status':'locked','at':time.time(),'seconds':fault['seconds']}
                save(self.folder/'write-pause.json',data)
                time.sleep(fault['seconds'])
                db.commit()
                data.update(status='released',released_at=time.time(),held_seconds=time.monotonic()-acquired)
                save(self.folder/'write-pause.json',data)
        await asyncio.to_thread(block)

    async def copy_gate(self,number):
        save(self.folder/'copy-request.json',{'number':number,'enabled':self.plan['copy_modes'][number]})
        deadline=time.monotonic()+120
        while True:
            ack=self.folder/'copy-ack.json'
            if ack.exists() and json.loads(ack.read_text())['number']==number:return
            assert not self.stop and time.monotonic()<deadline,'copy_gate_timeout'
            await asyncio.sleep(.1)

    async def run(self):
        initial=await asyncio.to_thread(snapshot)
        assert initial['peers']['n']==len(self.lanes) and initial['peers']['versions']==0 and initial['peers']['uploaded']==0
        heartbeat=asyncio.create_task(self.heartbeat())
        injection=asyncio.create_task(self.inject_write_pause()) if 'write_pause' in self.plan else None
        deadline=self.origin+self.plan['seconds']
        status='failed';reason=None;number=0;last_audit=None
        try:
            while time.monotonic()<deadline and not self.stop:
                if injection and injection.done():await injection
                await self.maintenance(number)
                if 'copy_modes' in self.plan:await self.copy_gate(number)
                remaining=deadline-time.monotonic()
                if remaining<1:
                    if remaining>0:await asyncio.sleep(remaining)
                    break
                await self.window(min(self.plan['window_seconds'],remaining),number)
                # Confirm data while no new announces are offered.
                expected=sum(p['observed'] for p in self.lanes)
                drained=time.monotonic()
                while True:
                    state=await asyncio.to_thread(snapshot)
                    if all(state[t]['uploaded']==expected for t in ['peers','history','users']) and state['peers']['versions']>=self.accepted:
                        break
                    assert time.monotonic()-drained<30,'persistence_drain_timeout'
                    await asyncio.sleep(.25)
                assert state['locks']==initial['locks'] and state['failed_jobs']==initial['failed_jobs'],'database_errors'
                self.missing6=state['peer_ips']['n']==2*len(self.lanes)-1
                last_audit=await asyncio.to_thread(audit,self.lanes,self.missing6,time.time()-self.created)
                if self.missing6:
                    assert self.plan.get('natural_expiry',True) and not self.restored and time.time()>=self.expire_at-2,'unexpected_expiry'
                elif self.plan.get('natural_expiry',True) and not self.restored:
                    assert time.time()<self.expire_at+65,'expiry_cleanup_late'
                await asyncio.to_thread(self.samples.segment)
                await self.progress(audit=last_audit,window=number,drain_seconds=time.monotonic()-drained)
                number+=1
                if 'copy_modes' in self.plan and number==len(self.plan['copy_modes']):break
            assert not self.stop,'load_stopped_by_supervisor'
            if injection:await injection
            if self.plan.get('natural_expiry',True) and self.plan['seconds']>=self.plan['ttl']+100:
                assert self.expiry_checked and self.restored,'expiry_not_exercised'
            status='passed'
        except Exception as error:
            self.record_error(error,phase='run')
            reason=str(error) if isinstance(error,AssertionError) else type(error).__name__
        finally:
            if injection:
                if not injection.done():injection.cancel()
                await asyncio.gather(injection,return_exceptions=True)
            self.heartbeat_stop=True
            await asyncio.gather(heartbeat,return_exceptions=True)
            for _,writer in self.connections.values():writer.close()
            try:await asyncio.to_thread(self.samples.close)
            except Exception:status='failed';reason='sample_writer_failed'
            final={'status':status,'reason':reason,'accepted':self.accepted,'main_accepted':self.main_accepted,'errors':self.errors,
                   'windows':number,'elapsed_seconds':time.monotonic()-self.origin,'audit':last_audit,
                   'expiry_checked':self.expiry_checked,'restored':self.restored,'sample_count':self.samples.count,
                   'sample_queue_peak':self.samples.peak_queue,'rss_peak_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
            final['error_details']=self.error_details
            save(self.folder/'final.json',final)
            await self.progress(status,reason=reason)
        return status=='passed'


async def main(plan):
    load=Load(plan)
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,lambda:setattr(load,'stop',True))
    return await load.run()


if __name__=='__main__':
    assert os.geteuid()==0 and socket.gethostname()=='unit3d-ds-clients'
    os.umask(0o077)
    parser=argparse.ArgumentParser();parser.add_argument('plan');args=parser.parse_args()
    plan=json.loads(Path(args.plan).read_text())
    assert 1<=plan['seconds']<=21600 and 1<=plan['window_seconds']<=60 and 1<=plan['rate']<=8000
    assert all(c.isalnum() or c=='-' for c in plan['name'])
    raise SystemExit(0 if asyncio.run(main(plan)) else 1)
