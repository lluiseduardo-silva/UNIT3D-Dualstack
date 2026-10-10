#!/usr/bin/env python3
"""Carga limitada de HTTP real; nunca imprime URLs, passkeys ou credenciais.

36 peers em dois torrents, alternancia IPv4/IPv6 e completed repetido para
exercitar deduplicacao sem desativar o intervalo de announces no PHP.
O perfil mede hotspots e interferencia de reembolso, nao popula 54 mil peers.
"""
import argparse
import asyncio
import collections
import json
import math
from pathlib import Path
import socket
import time
import urllib.parse

import pymysql


async def main(args):
    fixture = json.loads(Path(args.fixture).read_text())
    credentials = dict(line.split('=', 1) for line in Path(args.database_env).read_text().splitlines())

    def connect():
        return pymysql.connect(host='172.29.92.20', user=credentials['MYSQL_USER'], password=credentials['MYSQL_PASSWORD'],
            database='unit3d_dualstack_journal_test', autocommit=True, connect_timeout=3, read_timeout=5,
            cursorclass=pymysql.cursors.DictCursor)

    def snapshot():
        with connect() as db, db.cursor() as cursor:
            cursor.execute('SELECT DATABASE() AS name,@@transaction_isolation AS isolation,@@innodb_lock_wait_timeout AS timeout')
            environment = cursor.fetchone()
            assert environment['name'] == 'unit3d_dualstack_journal_test'
            cursor.execute('SELECT id,uploaded,downloaded FROM users WHERE id BETWEEN 12001 AND 12006 ORDER BY id')
            users = cursor.fetchall()
            cursor.execute('SELECT user_id,torrent_id,HEX(peer_id) AS peer,uploaded,downloaded,state_version FROM peers')
            peers = cursor.fetchall()
            cursor.execute('SELECT user_id,SUM(refunded_download) AS refunded FROM history GROUP BY user_id')
            refunds = {r['user_id']: int(r['refunded']) for r in cursor.fetchall()}
            cursor.execute('SELECT COUNT(*) AS count FROM peer_ips')
            endpoints = cursor.fetchone()['count']
            cursor.execute("SELECT NAME,COUNT FROM information_schema.INNODB_METRICS WHERE NAME IN ('lock_deadlocks','lock_timeouts','lock_row_lock_waits','lock_row_lock_time')")
            metrics = {r['NAME']: r['COUNT'] for r in cursor.fetchall()}
        return dict(environment=environment, users=users, peers=peers, refunds=refunds, endpoints=endpoints, metrics=metrics)

    before = await asyncio.to_thread(snapshot)
    existing = {(r['user_id'], r['torrent_id'], r['peer'].lower()): r for r in before['peers']}
    lanes = []
    for user in fixture['users']:
        for torrent in fixture['torrents']:
            for slot in range(3):
                peer = ('-qB4500-' + f"{user['id']:06d}{torrent['id'] % 10000:04d}{slot:02d}").encode()
                assert len(peer) == 20
                old = existing.get((user['id'], torrent['id'], peer.hex()), {})
                lanes.append(dict(user=user, torrent=torrent, peer=peer, uploaded=int(old.get('uploaded', 0)),
                    downloaded=int(old.get('downloaded', 0)), connections={}))
    accepted = 0
    measured_accepted = 0
    errors = collections.Counter()
    latencies = []
    skipped = 0
    persistence = []

    async def send(lane, family, increment):
        nonlocal accepted
        try:
            if family not in lane['connections']:
                host = '172.29.92.10' if family == 4 else 'fd42:756e:6974:92::10'
                number = 30 if args.source_offset < 0 else 100 + args.source_offset + lanes.index(lane)
                source = '172.29.92.' + str(number) if family == 4 else 'fd42:756e:6974:92::' + str(number)
                lane['connections'][family] = await asyncio.wait_for(asyncio.open_connection(host, 8080,
                    family=socket.AF_INET if family == 4 else socket.AF_INET6, local_addr=(source, 0)), 5)
            reader, writer = lane['connections'][family]
            query = urllib.parse.urlencode(dict(info_hash=bytes.fromhex(lane['torrent']['info_hash_hex']), peer_id=lane['peer'],
                port=6881, uploaded=lane['uploaded'] + increment, downloaded=lane['downloaded'] + increment,
                left=0, event='completed', numwant=0, compact=1), quote_via=urllib.parse.quote)
            path = '/announce/' + lane['user']['passkey'] + '?' + query
            writer.write(('GET ' + path + ' HTTP/1.1\r\nHost: tracker.lab\r\nUser-Agent: libtorrent/2.0.10\r\nConnection: keep-alive\r\n\r\n').encode())
            await writer.drain()
            header = await reader.readuntil(b'\r\n\r\n')
            status = int(header.split(b' ', 2)[1])
            fields = {line.split(b':', 1)[0].lower(): line.split(b':', 1)[1].strip() for line in header.split(b'\r\n')[1:] if b':' in line}
            if b'content-length' in fields:
                body = await reader.readexactly(int(fields[b'content-length']))
            elif fields.get(b'transfer-encoding') == b'chunked':
                chunks = []
                while True:
                    length = int((await reader.readline()).split(b';', 1)[0], 16)
                    if length == 0:
                        assert await reader.readline() == b'\r\n'
                        break
                    chunks.append(await reader.readexactly(length))
                    assert await reader.readexactly(2) == b'\r\n'
                body = b''.join(chunks)
            else:
                raise RuntimeError('framing')
            if fields.get(b'connection') == b'close':
                writer.close()
                del lane['connections'][family]
            if status != 200 or b'failure reason' in body:
                # No arbitrary response bodies in reports: those can reflect secrets.
                errors['http_' + str(status) if status != 200 else 'tracker_rejection'] += 1
                return False
            lane['uploaded'] += increment
            lane['downloaded'] += increment
            accepted += 1
            return True
        except (OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError, RuntimeError) as error:
            errors[type(error).__name__] += 1
            pair = lane['connections'].pop(family, None)
            if pair:
                pair[1].close()
            return False

    async def initialize(lane):
        for family in [4, 6]:
            assert await asyncio.wait_for(send(lane, family, 0), 5), 'Falha no preparo HTTP (ver contagem segura de erros)'

    report = dict(status='running', backend=args.backend, profile=args.profile, target_rps=args.rate,
        seconds=args.seconds, warmup_seconds=args.warmup, peers=36, endpoints=72, numwant=0,
        event='completed', source_offset=args.source_offset, real_source_addresses=2 if args.source_offset < 0 else 72, errors=errors)
    try:
        await asyncio.gather(*(initialize(lane) for lane in lanes))
        start = time.monotonic() + 0.1
        measured_start = start + args.warmup
        finish = measured_start + args.seconds
        period = len(lanes) / args.rate
        done = asyncio.Event()

        async def monitor():
            initial_versions = sum(int(r['state_version']) for r in before['peers'])
            while not done.is_set():
                state = await asyncio.to_thread(snapshot)
                persisted = sum(int(r['state_version']) for r in state['peers']) - initial_versions
                persistence.append(dict(at=round(time.monotonic() - start, 3),
                    accepted_not_yet_persisted=max(0, accepted - persisted)))
                await asyncio.sleep(0.5)

        async def worker(index, lane):
            nonlocal skipped, measured_accepted
            scheduled = start + index / args.rate
            family = 4
            while scheduled < finish:
                await asyncio.sleep(max(0, scheduled - time.monotonic()))
                now = time.monotonic()
                if now >= finish:
                    break
                if now - scheduled > period:
                    missed = math.floor((now - scheduled) / period)
                    if now >= measured_start:
                        skipped += missed
                    scheduled += missed * period
                sent = time.monotonic()
                success = False
                try:
                    success = await asyncio.wait_for(send(lane, family, 100), 5)
                except TimeoutError:
                    errors['timeout'] += 1
                if sent >= measured_start:
                    latencies.append((time.monotonic() - sent) * 1000)
                    measured_accepted += int(success)
                family = 10 - family
                scheduled += period

        monitoring = asyncio.create_task(monitor())
        await asyncio.gather(*(worker(i, lane) for i, lane in enumerate(lanes)))
        done.set()
        await monitoring
        drain_start = time.monotonic()
        expected = {(lane['user']['id'], lane['torrent']['id'], lane['peer'].hex()): lane['uploaded'] for lane in lanes}
        while True:
            after = await asyncio.to_thread(snapshot)
            if all(expected.get((r['user_id'], r['torrent_id'], r['peer'].lower())) == int(r['uploaded']) for r in after['peers']) and len(after['peers']) == 36:
                break
            if time.monotonic() - drain_start > 60:
                raise AssertionError('Persistencia nao drenou em 60 segundos')
            await asyncio.sleep(0.2)
        report['drain_seconds'] = time.monotonic() - drain_start
        report['before_metrics'] = before['metrics']
        report['after_metrics'] = after['metrics']
        report['persistence_samples'] = persistence
        report['observed_peak_pending'] = max(r['accepted_not_yet_persisted'] for r in persistence)
        report['pending_note'] = 'announces reconhecidos menos versoes persistidas, amostragem a cada 500 ms; nao e instrumentacao interna da fila'
        report['measured_requests'] = len(latencies)
        report['accepted_requests_including_warmup_and_setup'] = accepted
        report['successful_measured_requests'] = measured_accepted
        report['attempted_rps'] = len(latencies) / args.seconds
        report['achieved_rps'] = measured_accepted / args.seconds
        report['not_offered_due_to_client_concurrency_limit'] = skipped
        ordered = sorted(latencies)
        report['latency_ms'] = {name: ordered[min(len(ordered)-1, math.ceil(len(ordered)*q)-1)] for name, q in [('p50',.5),('p95',.95),('p99',.99)]}
        report['credits'] = after['users']
        report['refunds'] = after['refunds']
        for name in ['lock_deadlocks', 'lock_timeouts']:
            assert after['metrics'][name] == before['metrics'][name], name + ' aumentou'
        assert not errors, 'Ocorreram erros HTTP ou de protocolo'
        assert after['endpoints'] == 72
        for row in after['users']:
            expected_upload = sum(lane['uploaded'] for lane in lanes if lane['user']['id'] == row['id'])
            assert int(row['uploaded']) == expected_upload, 'Credito de upload divergente'
            assert int(row['downloaded']) == 1000000000 + expected_upload - after['refunds'][row['id']], 'Credito de download divergente'
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error_type'] = type(error).__name__
        if isinstance(error, AssertionError):
            report['reason'] = str(error)
    finally:
        for lane in lanes:
            for reader, writer in lane['connections'].values():
                writer.close()
        Path(args.output).write_text(json.dumps(report, indent=2, default=int) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ['persistence_samples', 'credits', 'refunds']}, default=int))
    return report['status'] == 'passed'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', default='/opt/unit3d-dualstack/fixture.json')
    parser.add_argument('--database-env', default='/opt/unit3d-dualstack/database.env')
    parser.add_argument('--output', required=True)
    parser.add_argument('--backend', choices=['php','rust'], required=True)
    parser.add_argument('--profile', choices=['without-refund','with-refund'], required=True)
    parser.add_argument('--rate', type=int, default=1000)
    parser.add_argument('--seconds', type=int, default=20)
    parser.add_argument('--warmup', type=int, default=5)
    parser.add_argument('--source-offset', type=int, choices=[-1, 0, 36], default=-1)
    args = parser.parse_args()
    assert 1 <= args.rate <= 5000 and 1 <= args.seconds <= 60 and 0 <= args.warmup <= 30
    raise SystemExit(0 if asyncio.run(main(args)) else 1)
