#!/usr/bin/env python3
"""Par de carga IPv4: mesmo transporte/contador, auditoria própria de cada backend."""
import argparse
import asyncio
import collections
import gzip
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import random
import signal
import socket
import time

spec=importlib.util.spec_from_file_location('soak_load',Path(__file__).with_name('soak-load.py'))
soak=importlib.util.module_from_spec(spec);spec.loader.exec_module(soak)


class Comparison(soak.Load):
    @staticmethod
    def phases(plan):
        assert plan['seconds']==plan['warmup']+plan['measurement']
        assert 0<plan['warmup']<=300
        if plan.get('prolonged',False):
            assert 0<plan['measurement']<=21600 and 1<=plan['window_seconds']<=300
            phases=[]
            for label in ('warmup','measurement'):
                remaining=plan[label]
                while remaining:
                    seconds=min(remaining,plan['window_seconds'])
                    phases.append((label,seconds));remaining-=seconds
            return phases
        assert 0<plan['measurement']<=900
        return [('warmup',plan['warmup']),('measurement',plan['measurement'])]

    def __init__(self,plan):
        assert plan['comparison_variant'] in ('original','candidate')
        self.phases(plan)
        assert plan['ttl']==7200 and 0<plan['rate']<=8000
        super().__init__(plan)
        if plan.get('prolonged',False):
            path=self.folder/'sample-format.json'
            metadata=json.loads(path.read_text())
            metadata['fields'][2]='event_0_completed_1_started_2_stopped_3_empty'
            soak.save(path,metadata)
        assert self.fixture['dual_percent']==0
        self.seeders=[p for p in self.lanes if p['seeder']]
        random.Random(9137).shuffle(self.seeders)
        self.slots=[(p,4) for p in self.seeders]
        self.mapped_ipv4_responses=0

    async def progress(self,status='running',**extra):
        await super().progress(status,expected_upload=sum(p['observed'] for p in self.lanes),**extra)

    def counter(self,p):
        return p['sent']*100

    def replay_sample(self,index,family,event,upload,ok):
        assert family==4 and ok and 0<=index<len(self.lanes),'sample_identity'
        p=self.lanes[index]
        assert p['index']==index,'sample_index'
        if event==3:
            assert self.plan.get('prolonged',False) and not p['seeder'] and upload==p['observed']==0,'sample_refresh'
        else:
            assert event==0 and p['seeder'] and upload==p['observed']+100,'sample_counter_sequence'
        p['observed']=upload;p['accepted']+=1

    async def refresh_leechers(self):
        # Sem evento, tráfego ou lista: mantém o left real e o TTL original.
        # Só acontece entre janelas; não concorre com a carga medida.
        batches=[[p for p in self.leechers if p['user_slot']%72==i] for i in range(72)]
        async def refresh(batch):
            for p in batch:
                assert not self.stop,'load_stopped'
                start=time.monotonic()
                received,size=await asyncio.wait_for(self.announce(p,4,0,self.connections,0,event=''),5)
                self.samples.add(p['index'],4,3,0,start-self.origin,start-self.origin,
                    received-self.origin,time.monotonic()-self.origin,size,True)
        await asyncio.gather(*(refresh(batch) for batch in batches))

    def stored_address(self,raw):
        address=ipaddress.ip_address(raw)
        # O socket :: da tag original persiste IPv4 mapeado em 16 bytes.
        # O candidato deve continuar usando a forma canônica de quatro bytes.
        if self.plan['comparison_variant']=='original' and isinstance(address,ipaddress.IPv6Address):
            return address.ipv4_mapped or address
        return address

    def validate_response(self,p,result,numwant,complete):
        size=self.fixture['sizes'][p['torrent_slot']]
        assert result[b'complete']==size*4//5 and result[b'incomplete']==size//5,'counts'
        v4,v6=result.get(b'peers',b''),result.get(b'peers6',b'')
        assert len(v4)%6==0 and len(v6)%18==0 and len(v4)//6+len(v6)//18==numwant,'single_family_payload'
        ids={self.eligible[(p['torrent_slot'],4,v4[o:o+6])] for o in range(0,len(v4),6)}
        if v6:
            # O original ouvindo :: devolve IPv4 mapeado em peers6. Conferir a
            # origem IPv4 exata, sem aceitar IPv6 nativo nem relaxar o candidato.
            assert self.plan['comparison_variant']=='original','unexpected_ipv6_payload'
            for o in range(0,len(v6),18):
                mapped=ipaddress.IPv6Address(v6[o:o+16]).ipv4_mapped
                assert mapped is not None,'native_ipv6_in_ipv4_profile'
                ids.add(self.eligible[(p['torrent_slot'],4,mapped.packed+v6[o+16:o+18])])
            self.mapped_ipv4_responses=getattr(self,'mapped_ipv4_responses',0)+1
        assert len(ids)==numwant,'duplicate_endpoint'

    def audit(self):
        lanes={(p['user_id'],p['torrent_id']):p for p in self.lanes}
        totals=collections.Counter()
        for p in self.lanes:totals[p['user_id']]+=p['observed']
        with soak.connect() as db,db.cursor() as c:
            c.execute('SELECT p.user_id,p.torrent_id,HEX(p.peer_id) AS peer_id,p.ip,p.port,p.uploaded,p.state_version,p.active,p.seeder,h.actual_uploaded,h.uploaded AS credited FROM peers p JOIN history h USING(user_id,torrent_id) WHERE p.user_id>=20000')
            rows=c.fetchall()
            c.execute('SELECT id,uploaded,seedbonus FROM users WHERE id>=20000');users=c.fetchall()
            c.execute('SELECT id,seeders,leechers,times_completed FROM torrents WHERE id>=20000');torrents=c.fetchall()
            c.execute('SELECT COUNT(*) AS n FROM peer_ips WHERE user_id>=20000');endpoints=int(c.fetchone()['n'])
        assert len(rows)==len(lanes),'peer_count'
        # Snapshot público por identidade fica no ZFS para revisão após o próximo
        # reset. Não inclui passkeys, URLs, tokens ou fixtures de autenticação.
        evidence=dict(peers=[dict(r,ip=r['ip'].hex()) for r in rows],users=users,torrents=torrents)
        raw=gzip.compress(json.dumps(evidence,default=str,sort_keys=True).encode(),mtime=0)
        path=self.folder/'accounting-rows.json.gz';path.write_bytes(raw)
        soak.save(self.folder/'accounting-proof.json',dict(file=path.name,sha256=hashlib.sha256(raw).hexdigest(),
            bytes=len(raw),rows=len(rows),database='unit3d_dualstack_journal_test'))
        for row in rows:
            p=lanes[(row['user_id'],row['torrent_id'])]
            assert row['peer_id'].lower()==p['peer_id'],'peer_identity'
            assert self.stored_address(row['ip'])==ipaddress.ip_address(p['ipv4']) and row['port']==p['port'],'legacy_endpoint'
            assert row['active'] and bool(row['seeder'])==p['seeder'],'peer_state'
            assert all(int(row[k])==p['observed'] for k in ('uploaded','actual_uploaded','credited')),'individual_credit'
            assert int(row['state_version'])==(p['accepted'] if self.plan['comparison_variant']=='candidate' else 0),'individual_version'
        assert len(users)==len(totals) and all(int(u['uploaded'])==totals[u['id']] and float(u['seedbonus'])==0 for u in users),'user_credit'
        assert endpoints==len(lanes),'fixture_endpoint_count'
        assert len(torrents)==len(self.fixture['sizes']),'torrent_count'
        for t in torrents:
            size=self.fixture['sizes'][t['id']-20000]
            assert t['seeders']==size*4//5 and t['leechers']==size//5 and t['times_completed']==0,'torrent_totals'
        return dict(peers=len(rows),users=len(users),credit=sum(totals.values()),mismatches=0,
                    peer_ips_role='maintained' if self.plan['comparison_variant']=='candidate' else 'static_compatibility_fixture')

    async def run(self):
        initial=await asyncio.to_thread(soak.snapshot)
        assert initial['peers']['uploaded']==initial['peers']['versions']==0
        assert initial['peers']['n']==len(self.lanes)
        heartbeat=asyncio.create_task(self.heartbeat())
        status='failed';reason=None;reports=[];last_audit=None
        try:
            # O perfil curto preserva duas janelas. O prolongado renova leechers
            # entre janelas limitadas, sem SQL no gerador durante a carga.
            for label,seconds in self.phases(self.plan):
                assert not self.stop,'load_stopped'
                if self.plan.get('prolonged',False):await self.refresh_leechers()
                await self.progress(phase=label)
                report=await self.window(seconds,len(reports))
                report['phase']=label;reports.append(report)
                await asyncio.to_thread(self.samples.segment)
            expected=sum(p['observed'] for p in self.lanes)
            drained=time.monotonic()
            while True:
                state=await asyncio.to_thread(soak.snapshot)
                credits=all(state[t]['uploaded']==expected for t in ('peers','history','users'))
                versions=self.plan['comparison_variant']=='original' or state['peers']['versions']==self.accepted
                if credits and versions:break
                assert not self.stop and time.monotonic()-drained<90,'accounting_drain_timeout'
                await asyncio.sleep(.25)
            drain_seconds=time.monotonic()-drained
            assert state['locks']==initial['locks'] and state['failed_jobs']==initial['failed_jobs'],'database_errors'
            last_audit=await asyncio.to_thread(self.audit)
            assert not self.stop and self.errors==0,'load_failed'
            status='passed'
        except Exception as error:
            self.record_error(error,phase='comparison')
            reason=str(error) if isinstance(error,AssertionError) else type(error).__name__
        finally:
            self.heartbeat_stop=True
            await asyncio.gather(heartbeat,return_exceptions=True)
            for _,writer in self.connections.values():writer.close()
            try:await asyncio.to_thread(self.samples.close)
            except Exception:status='failed';reason='sample_writer_failed'
            final=dict(status=status,reason=reason,variant=self.plan['comparison_variant'],accepted=self.accepted,
                main_accepted=self.main_accepted,maintenance_accepted=self.accepted-self.main_accepted,
                mapped_ipv4_responses=self.mapped_ipv4_responses,
                errors=self.errors,error_details=self.error_details,audit=last_audit,phases=reports,
                elapsed_seconds=time.monotonic()-self.origin,sample_count=self.samples.count,
                sample_queue_peak=self.samples.peak_queue,source_families=[4],numwant=10,
                drain_seconds=drain_seconds if 'drain_seconds' in locals() else None)
            soak.save(self.folder/'final.json',final)
            await self.progress(status,reason=reason)
        return status=='passed'


async def main(plan):
    load=Comparison(plan)
    for sig in (signal.SIGTERM,signal.SIGINT):asyncio.get_running_loop().add_signal_handler(sig,lambda:setattr(load,'stop',True))
    return await load.run()


if __name__=='__main__':
    assert os.geteuid()==0 and socket.gethostname()=='unit3d-ds-clients'
    os.umask(0o077)
    parser=argparse.ArgumentParser();parser.add_argument('plan');args=parser.parse_args()
    plan=json.loads(Path(args.plan).read_text())
    assert all(c.isalnum() or c=='-' for c in plan['name'])
    raise SystemExit(0 if asyncio.run(main(plan)) else 1)
