#!/usr/bin/env python3
"""Fases HTTP por torrent, com sentinelas e contabilizacao por usuario/torrent."""
import argparse
import asyncio
import collections
import gzip
import heapq
import ipaddress
import itertools
import json
import math
import os
import resource
import socket
import time
import urllib.parse

from density_common import BASE, bdecode, connect, percentiles, snapshot


def check_identities(lanes):
    expected = {(p['user_id'], p['torrent_id']): p['observed'] for p in lanes}
    user_totals = collections.Counter()
    for (user, _), value in expected.items():
        user_totals[user] += value
    with connect() as db, db.cursor() as c:
        c.execute('SELECT p.user_id,p.torrent_id,p.uploaded,h.actual_uploaded,h.uploaded AS credited FROM peers p JOIN history h USING(user_id,torrent_id) WHERE p.user_id>=20000')
        peers = c.fetchall()
        c.execute('SELECT id,uploaded FROM users WHERE id>=20000')
        users = c.fetchall()
        c.execute('SELECT COUNT(*) AS n FROM peer_ips WHERE user_id>=20000')
        endpoints = int(c.fetchone()['n'])
    assert len(peers) == len(expected) and endpoints == 2*len(expected), 'identity_or_endpoint_count'
    bad = sum(any(int(p[k]) != expected[(p['user_id'], p['torrent_id'])]
                  for k in ['uploaded', 'actual_uploaded', 'credited']) for p in peers)
    bad_users = sum(int(u['uploaded']) != user_totals[u['id']] for u in users)
    assert bad == bad_users == 0, 'accounting_by_peer_or_user'
    return dict(peers=len(peers), users=len(users), endpoints=endpoints, mismatches=bad+bad_users)


async def phase(spec, fixture, initial, accepted_before, folder):
    lanes = fixture['lanes']
    by_torrent = collections.defaultdict(list)
    eligible = {}
    for p in lanes:
        if p['seeder']:
            by_torrent[p['torrent_slot']].extend([(p, 4), (p, 6)])
        else:
            for f in [4, 6]:
                endpoint = ipaddress.ip_address(p['ipv'+str(f)]).packed+p['port'].to_bytes(2, 'big')
                eligible[(p['torrent_slot'], f, endpoint)] = p['user_id']
    groups = {}
    used = set()
    for name, cfg in spec['groups'].items():
        assert not used.intersection(cfg['torrents']), 'Grupos sobrepostos'
        used.update(cfg['torrents'])
        # Intercalar torrents desde o primeiro request: concatenar swarms grandes
        # poderia encerrar uma fase antes de sequer atingir os ultimos torrents.
        slots = [s for row in itertools.zip_longest(*(by_torrent[t] for t in cfg['torrents']))
                 for s in row if s is not None]
        assert slots and 0 < cfg['rate'] <= 2000
        groups[name] = dict(config=cfg, slots=slots, accepted=0, completed_in_window=0, measured_accepted=0,
                            samples=[], errors=collections.Counter(), dropped=0,
                            offered_by_torrent=collections.Counter(), accepted_by_torrent=collections.Counter())
    assert sum(g['config']['rate'] for g in groups.values()) <= 2000
    start = time.monotonic()+.2
    measured = start+spec['warmup']
    finish = measured+spec['seconds']
    epoch = time.time()+start-time.monotonic()
    cpu_start = resource.getrusage(resource.RUSAGE_SELF)
    queues = [asyncio.Queue(maxsize=128) for _ in range(72)]

    async def worker(index):
        connections = {}

        async def send(p, family, counter):
            if family not in connections:
                target = '172.29.92.10' if family == 4 else 'fd42:756e:6974:92::10'
                connections[family] = await asyncio.open_connection(target, 8080,
                    family=socket.AF_INET if family == 4 else socket.AF_INET6,
                    local_addr=(p['ipv'+str(family)], 0))
            reader, writer = connections[family]
            query = urllib.parse.urlencode(dict(info_hash=bytes.fromhex(p['info_hash']), peer_id=bytes.fromhex(p['peer_id']),
                port=p['port'], uploaded=counter, downloaded=0, left=0, event='completed', compact=1, numwant=10),
                quote_via=urllib.parse.quote)
            path = '/announce/'+p['passkey']+'?'+query
            writer.write(('GET '+path+' HTTP/1.1\r\nHost: tracker.lab\r\nUser-Agent: libtorrent/2.0.10\r\nConnection: keep-alive\r\n\r\n').encode())
            await writer.drain()
            head = await reader.readuntil(b'\r\n\r\n')
            status = int(head.split(b' ', 2)[1])
            headers = {r.split(b':', 1)[0].lower(): r.split(b':', 1)[1].strip() for r in head.split(b'\r\n')[1:] if b':' in r}
            if b'content-length' in headers:
                body = await reader.readexactly(int(headers[b'content-length']))
            else:
                assert headers.get(b'transfer-encoding') == b'chunked', 'framing'
                chunks = []
                while True:
                    length = int((await reader.readline()).split(b';', 1)[0], 16)
                    if not length:
                        assert await reader.readline() == b'\r\n'
                        break
                    chunks.append(await reader.readexactly(length))
                    assert await reader.readexactly(2) == b'\r\n'
                body = b''.join(chunks)
            received = time.monotonic()
            if headers.get(b'connection') == b'close':
                writer.close()
                connections.pop(family)
            assert status == 200, 'http_status'
            decoded = bdecode(body)
            assert b'failure reason' not in decoded and b'warning message' not in decoded, 'tracker_response'
            size = fixture['sizes'][p['torrent_slot']]
            assert decoded[b'complete'] == size*4//5 and decoded[b'incomplete'] == size//5, 'counts'
            v4, v6 = decoded.get(b'peers', b''), decoded.get(b'peers6', b'')
            assert len(v4) == 60 and len(v6) == 180, 'payload_size'
            selected = []
            for family, compact, width in [(4, v4, 6), (6, v6, 18)]:
                ids = {eligible[(p['torrent_slot'], family, compact[o:o+width])] for o in range(0, len(compact), width)}
                assert len(ids) == 10, 'duplicate_endpoint'
                selected.append(ids)
            assert selected[0] == selected[1], 'unpaired_endpoints'
            p['observed'] = max(p['observed'], counter)
            return received, len(body)

        try:
            while True:
                item = await queues[index].get()
                if item is None:
                    break
                group, p, family, counter, scheduled = item
                g = groups[group]
                began = time.monotonic()
                received, size, ok = None, 0, False
                try:
                    received, size = await asyncio.wait_for(send(p, family, counter), 5)
                    ok = True
                except Exception as error:
                    reason = str(error) if isinstance(error, AssertionError) else type(error).__name__
                    g['errors'][reason or type(error).__name__] += 1
                    pair = connections.pop(family, None)
                    if pair:
                        pair[1].close()
                ended = time.monotonic()
                g['accepted'] += int(ok)
                g['accepted_by_torrent'][p['torrent_slot']] += int(ok)
                g['completed_in_window'] += int(ok and measured <= received < finish)
                if scheduled >= measured:
                    g['measured_accepted'] += int(ok)
                    g['samples'].append([scheduled-start, began-start, (received-start) if received else None, ended-start, size, ok])
        finally:
            for _, writer in connections.values():
                writer.close()

    tasks = [asyncio.create_task(worker(i)) for i in range(72)]
    report = dict(name=spec['name'], spec=spec, started_at_epoch=epoch,
                  measured_at_epoch=epoch+spec['warmup'], sizes=fixture['sizes'], users=fixture['users'])
    try:
        schedule = [(start, name, 0) for name in groups]
        heapq.heapify(schedule)
        while schedule:
            scheduled, name, seq = heapq.heappop(schedule)
            g = groups[name]
            if seq >= math.floor((spec['warmup']+spec['seconds'])*g['config']['rate']):
                continue
            await asyncio.sleep(max(0, scheduled-time.monotonic()))
            p, family = g['slots'][seq % len(g['slots'])]
            g['offered_by_torrent'][p['torrent_slot']] += 1
            p['sent'] += 1
            counter = ((p['sent']+1)//2)*100
            try:
                queues[p['user_slot'] % 72].put_nowait((name, p, family, counter, scheduled))
            except asyncio.QueueFull:
                g['dropped'] += 1
            heapq.heappush(schedule, (start+(seq+1)/g['config']['rate'], name, seq+1))
        for q in queues:
            await q.put(None)
        await asyncio.gather(*tasks)
        accepted = sum(g['accepted'] for g in groups.values())
        expected = sum(p['observed'] for p in lanes)
        drain = time.monotonic()
        while True:
            after = await asyncio.to_thread(snapshot)
            if (after['peers']['versions']-initial['peers']['versions'] == accepted_before+accepted
                and all(after[t]['uploaded'] == expected for t in ['peers', 'history', 'users'])):
                break
            assert time.monotonic()-drain < 90, 'drain_timeout'
            await asyncio.sleep(.25)
        report.update(after=after, expected_upload=expected, drain_seconds=time.monotonic()-drain,
                      accepted=accepted, cumulative_accepted=accepted_before+accepted,
                      identities=await asyncio.to_thread(check_identities, lanes))
        assert after['locks'] == initial['locks'] and after['failed_jobs'] == initial['failed_jobs'], 'database_errors'
        assert not any(g['errors'] or g['dropped'] for g in groups.values()), 'load_errors_or_drops'
        for g in groups.values():
            assert set(g['accepted_by_torrent']) == set(g['config']['torrents']), 'unreached_torrent'
            assert g['accepted_by_torrent'] == g['offered_by_torrent'], 'unaccepted_torrent_requests'
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=type(error).__name__)
        if isinstance(error, AssertionError):
            report['reason'] = str(error)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        report['groups'] = {}
        raw = {}
        for name, g in groups.items():
            samples = g['samples']
            good = [r for r in samples if r[5]]
            report['groups'][name] = dict(rate=g['config']['rate'], accepted=g['accepted'],
                measured_accepted=g['measured_accepted'], completed_in_window=g['completed_in_window'],
                completed_rps=g['completed_in_window']/spec['seconds'], errors=dict(g['errors']), dropped=g['dropped'],
                offered_by_torrent=dict(g['offered_by_torrent']), accepted_by_torrent=dict(g['accepted_by_torrent']),
                response_read_ms=percentiles([(r[2]-r[1])*1000 for r in good]),
                latency_ms=percentiles([(r[3]-r[1])*1000 for r in good]),
                queue_wait_ms=percentiles([(r[1]-r[0])*1000 for r in samples]),
                end_to_end_ms=percentiles([(r[3]-r[0])*1000 for r in samples]),
                validation_ms=percentiles([(r[3]-r[2])*1000 for r in good]),
                payload_bytes=percentiles([r[4] for r in good]))
            raw[name] = samples
        report['finished_at_epoch'] = time.time()
        cpu_end = resource.getrusage(resource.RUSAGE_SELF)
        report['generator_cpu_percent'] = 100*((cpu_end.ru_utime-cpu_start.ru_utime)+(cpu_end.ru_stime-cpu_start.ru_stime))/(time.monotonic()-(start-.2))
        report['generator_peak_rss_kib'] = cpu_end.ru_maxrss
        (folder/(spec['name']+'.json')).write_text(json.dumps(report, indent=2)+'\n')
        with gzip.open(folder/(spec['name']+'-samples.json.gz'), 'wt') as output:
            json.dump(dict(columns=['scheduled_seconds','began_seconds','received_seconds','ended_seconds','payload_bytes','accepted'], groups=raw), output)
        print(json.dumps({k: v for k, v in report.items() if k != 'after'}), flush=True)
    assert report['status'] == 'passed', 'Fase interrompida; dados preservados'
    return report['accepted']


async def main(args):
    assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients'
    os.umask(0o077)
    plan = json.loads((BASE/args.plan).read_text())
    fixture = json.loads((BASE/'density-fixture.json').read_text())
    assert fixture['name'] == plan['name'] and fixture['sizes'] == plan['sizes']
    assert all(c.isalnum() or c == '-' for c in plan['name'])
    folder = BASE/'density-results'/plan['name']
    folder.mkdir(parents=True, exist_ok=False)
    initial = await asyncio.to_thread(snapshot)
    assert initial['peers']['n'] == fixture['peers'] and initial['peers']['uploaded'] == initial['peers']['versions'] == 0
    for p in fixture['lanes']:
        p.update(sent=0, observed=0)
    accepted = 0
    for spec in plan['phases']:
        assert 0 <= spec['warmup'] <= 60 and 1 <= spec['seconds'] <= 180
        assert all(c.isalnum() or c == '-' for c in spec['name'])
        accepted += await phase(spec, fixture, initial, accepted, folder)
    print(json.dumps(dict(status='series_passed', series=plan['name'], accepted=accepted, phases=len(plan['phases']))), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('plan')
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except Exception as error:
        print(json.dumps(dict(status='series_failed', error=type(error).__name__)), flush=True)
        raise SystemExit(1)
