#!/usr/bin/env python3
"""Carga aberta e limitada, com origens reais e evidencia sem credenciais."""
import argparse
import array
import asyncio
import collections
import gzip
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import socket
import time
import urllib.parse

from baseline import bdecode

BASE = Path('/opt/unit3d-dualstack')
spec = importlib.util.spec_from_file_location('fixture', BASE/'benchmark-fixture.py')
fixture_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)


def snapshot():
    with fixture_module.connect() as db, db.cursor() as cursor:
        result = {}
        for table, clause, columns in [
            ('peers', 'user_id>=20000', 'COUNT(*) AS n,SUM(uploaded) AS uploaded,SUM(state_version) AS versions'),
            ('history', 'user_id>=20000', 'COUNT(*) AS n,SUM(actual_uploaded) AS actual_uploaded,SUM(uploaded) AS uploaded'),
            ('users', 'id>=20000', 'COUNT(*) AS n,SUM(uploaded) AS uploaded'),
            ('peer_ips', 'user_id>=20000', 'COUNT(*) AS n'),
            ('failed_jobs', '1=1', 'COUNT(*) AS n'),
        ]:
            cursor.execute('SELECT '+columns+' FROM '+table+' WHERE '+clause)
            result[table] = {k: int(v or 0) for k, v in cursor.fetchone().items()}
        cursor.execute('SELECT VERSION() AS version,@@transaction_isolation AS isolation')
        result['database'] = cursor.fetchone()
        cursor.execute("SELECT NAME,COUNT FROM information_schema.INNODB_METRICS WHERE NAME IN ('lock_deadlocks','lock_timeouts')")
        result['locks'] = {r['NAME']: r['COUNT'] for r in cursor.fetchall()}
    return result


def percentiles(values):
    ordered = sorted(values)
    return {name: ordered[min(len(ordered)-1, math.ceil(len(ordered)*q)-1)] if ordered else None
            for name, q in [('p50', .5), ('p95', .95), ('p99', .99), ('max', 1)]}


async def main(args):
    assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients'
    os.umask(0o077)
    # Nao iniciar uma janela inteira se a preparacao do backend falhou.
    for target in ['172.29.92.10', 'fd42:756e:6974:92::10']:
        _, probe = await asyncio.wait_for(asyncio.open_connection(target, 8080), 3)
        probe.close()
        await probe.wait_closed()
    fixture = json.loads((BASE/'benchmark-fixture.json').read_text())
    eligible = {family: {} for family in [4, 6]}
    for lane in fixture['lanes']:
        if not lane['seeder']:
            for family in [4]+([6] if lane['dual'] else []):
                endpoint = ipaddress.ip_address(lane['ipv'+str(family)]).packed+lane['port'].to_bytes(2, 'big')
                eligible[family][endpoint] = lane
    lanes = [dict(lane, observed=0) for lane in fixture['lanes'] if lane['seeder']]
    # Seeders atualizam contadores; leechers residentes garantem listas reais.
    # completed repetido exercita atualizacao sem depender do intervalo normal.
    slots = [(lane, 4) for lane in lanes]+[(lane, 6) for lane in lanes if lane['dual']]
    rate = args.rate * (len(slots)/len(lanes) if args.load == 'same-population' else 1)
    if args.backend == 'php' and args.variant != 'candidate':
        positions = collections.defaultdict(list)
        for index, (lane, _) in enumerate(slots):
            positions[lane['index']].append(index)
        minimum_gap = min(min(b-a for a, b in zip(pos, pos[1:]+[pos[0]+len(slots)])) for pos in positions.values())
        assert minimum_gap/rate > 31, 'A carga excede o intervalo de deduplicacao de 30s do PHP original'
    before = await asyncio.to_thread(snapshot)
    assert before['peers']['n'] == fixture['peers'] and before['peers']['uploaded'] == 0, 'Exige fixture limpa'
    report = {k: v for k, v in vars(args).items()}
    report.update(status='running', population={k: v for k, v in fixture.items() if k != 'lanes'},
                  effective_rate=rate, traffic='seeders completed; resident leechers; increment 100 per logical round',
                  source_addresses=144, before=before)
    errors = collections.Counter()
    latency, end_to_end, payloads = array.array('d'), array.array('d'), array.array('I')
    response_read, validation = array.array('d'), array.array('d')
    queues = [asyncio.Queue(maxsize=128) for _ in range(72)]
    accepted = measured_accepted = dropped = 0
    samples = []
    stop = asyncio.Event()
    start = time.monotonic()+.2
    measured = start+args.warmup
    finish = measured+args.seconds
    report['started_at_epoch'] = time.time()+start-time.monotonic()
    report['measured_at_epoch'] = report['started_at_epoch']+args.warmup

    async def worker(index):
        nonlocal accepted, measured_accepted
        connections = {}

        async def send(lane, family, counter):
            if family not in connections:
                target = '172.29.92.10' if family == 4 else 'fd42:756e:6974:92::10'
                connections[family] = await asyncio.open_connection(target, 8080,
                    family=socket.AF_INET if family == 4 else socket.AF_INET6,
                    local_addr=(lane['ipv'+str(family)], 0))
            reader, writer = connections[family]
            query = urllib.parse.urlencode(dict(info_hash=bytes.fromhex(lane['info_hash']),
                peer_id=bytes.fromhex(lane['peer_id']), port=lane['port'], uploaded=counter,
                downloaded=0, left=0, event='completed', numwant=args.numwant, compact=1), quote_via=urllib.parse.quote)
            path = '/announce/'+lane['passkey']+'?'+query
            writer.write(('GET '+path+' HTTP/1.1\r\nHost: tracker.lab\r\nUser-Agent: libtorrent/2.0.10\r\nConnection: keep-alive\r\n\r\n').encode())
            await writer.drain()
            head = await reader.readuntil(b'\r\n\r\n')
            status = int(head.split(b' ', 2)[1])
            headers = {line.split(b':', 1)[0].lower(): line.split(b':', 1)[1].strip()
                       for line in head.split(b'\r\n')[1:] if b':' in line}
            if b'content-length' in headers:
                body = await reader.readexactly(int(headers[b'content-length']))
            elif headers.get(b'transfer-encoding') == b'chunked':
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
                raise ValueError('framing')
            received_at = time.monotonic()
            if headers.get(b'connection') == b'close':
                writer.close()
                connections.pop(family)
            if status != 200:
                errors['http_'+str(status)] += 1
                return False, len(body), received_at
            decoded = bdecode(body)
            if b'failure reason' in decoded:
                errors['tracker_rejection'] += 1
                return False, len(body), received_at
            v4, v6 = decoded.get(b'peers', b''), decoded.get(b'peers6', b'')
            assert len(v4) % 6 == 0 and len(v6) % 18 == 0
            assert len(v4)+len(v6) <= 24*min(args.numwant, 25)
            per_torrent = 10 if fixture['distribution'] == 'distributed' else fixture['peers']
            expected_peers = min(args.numwant, per_torrent//5)
            assert b'warning message' not in decoded, 'unexpected_warning'
            assert len(v4)//6 == expected_peers, 'ipv4_list_truncated'
            selected = {}
            for family, compact, size in [(4, v4, 6), (6, v6, 18)]:
                selected[family] = set()
                for offset in range(0, len(compact), size):
                    endpoint = eligible[family][compact[offset:offset+size]]
                    assert endpoint['torrent_id'] == lane['torrent_id'], 'wrong_swarm_endpoint'
                    assert endpoint['index'] not in selected[family], 'duplicate_endpoint'
                    selected[family].add(endpoint['index'])
            if args.variant == 'candidate':
                assert decoded[b'complete'] == per_torrent*4//5 and decoded[b'incomplete'] == per_torrent//5
                expected_v6 = {index for index in selected[4] if fixture['lanes'][index]['dual']}
                assert selected[6] == expected_v6, 'dualstack_path_missing_or_unpaired'
            lane['observed'] = max(lane['observed'], counter)
            return True, len(body), received_at

        try:
            while True:
                task = await queues[index].get()
                if task is None:
                    break
                lane, family, counter, scheduled = task
                began = time.monotonic()
                ok, size = False, 0
                received_at = None
                try:
                    ok, size, received_at = await asyncio.wait_for(send(lane, family, counter), 5)
                except Exception as error:
                    errors[type(error).__name__] += 1
                    pair = connections.pop(family, None)
                    if pair:
                        pair[1].close()
                ended = time.monotonic()
                accepted += int(ok)
                if scheduled >= measured:
                    measured_accepted += int(ok)
                    latency.append((ended-began)*1000)
                    end_to_end.append((ended-scheduled)*1000)
                    payloads.append(size)
                    if received_at is not None:
                        response_read.append((received_at-began)*1000)
                        validation.append((ended-received_at)*1000)
        finally:
            for _, writer in connections.values():
                writer.close()

    async def monitor():
        if args.monitor_interval == 0:
            await stop.wait()
            return
        while not stop.is_set():
            snapshot_started = time.monotonic()
            state = await asyncio.to_thread(snapshot)
            snapshot_seconds = time.monotonic()-snapshot_started
            expected = sum(lane['observed'] for lane in lanes)
            samples.append(dict(at=time.monotonic()-start, accepted=accepted,
                                pending_bytes=max(0, expected-state['peers']['uploaded']),
                                snapshot_seconds=snapshot_seconds, state=state))
            try:
                await asyncio.wait_for(stop.wait(), args.monitor_interval)
            except TimeoutError:
                pass

    workers = [asyncio.create_task(worker(i)) for i in range(72)]
    monitoring = asyncio.create_task(monitor())
    try:
        for seq in range(math.floor((args.warmup+args.seconds)*rate)):
            scheduled = start+seq/rate
            await asyncio.sleep(max(0, scheduled-time.monotonic()))
            lane, family = slots[seq % len(slots)]
            try:
                queues[lane['index'] % 72].put_nowait((lane, family, (seq//len(slots)+1)*100, scheduled))
            except asyncio.QueueFull:
                dropped += 1
        for queue in queues:
            await queue.put(None)
        await asyncio.gather(*workers)
        stop.set()
        await monitoring
        expected = sum(lane['observed'] for lane in lanes)
        drain_start = time.monotonic()
        while True:
            after = await asyncio.to_thread(snapshot)
            credits_confirmed = all(after[t]['uploaded'] == expected for t in ['peers', 'history', 'users'])
            # A segunda familia pode atualizar somente endpoint/versao. Saldo
            # correto nao prova drenagem dessas transicoes com delta zero.
            versions_confirmed = args.variant != 'candidate' or (
                after['peers']['versions']-before['peers']['versions'] == accepted)
            if credits_confirmed and versions_confirmed:
                break
            if time.monotonic()-drain_start > 90:
                raise AssertionError('accounting_drain_timeout')
            await asyncio.sleep(1)
        report.update(after=after, expected_upload=expected, drain_seconds=time.monotonic()-drain_start,
                      transition_versions_confirmed=versions_confirmed if args.variant == 'candidate' else None)
        expected_users = {lane['user_id']: lane['observed'] for lane in lanes}
        with fixture_module.connect() as db, db.cursor() as cursor:
            cursor.execute('SELECT p.user_id,p.uploaded AS reference,h.actual_uploaded,h.uploaded AS history,u.uploaded AS balance FROM peers p JOIN history h USING(user_id,torrent_id) JOIN users u ON u.id=p.user_id WHERE p.user_id>=20000 ORDER BY p.user_id')
            rows = cursor.fetchall()
        mismatches = [row for row in rows if any(int(row[field]) != expected_users.get(row['user_id'], 0)
                     for field in ['reference', 'actual_uploaded', 'history', 'balance'])]
        report['identity_check'] = {'rows': len(rows), 'mismatch_count': len(mismatches), 'examples': mismatches[:20]}
        assert len(rows) == fixture['peers'] and not mismatches, 'per_identity_accounting'
        assert after['history']['actual_uploaded'] == expected, 'history_actual_upload'
        assert after['failed_jobs']['n'] == before['failed_jobs']['n'], 'failed_jobs'
        assert not errors and dropped == 0, 'request_errors_or_generator_backlog'
        assert after['locks'] == before['locks'], 'new_deadlocks_or_timeouts'
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=type(error).__name__)
        if isinstance(error, AssertionError):
            report['reason'] = str(error)
        report['after'] = await asyncio.to_thread(snapshot)
    finally:
        stop.set()
        for worker_task in workers:
            if not worker_task.done():
                worker_task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        await monitoring
        report.update(accepted=accepted, measured_accepted=measured_accepted, measured_requests=len(latency),
            achieved_rps=measured_accepted/args.seconds, errors=errors, generator_dropped=dropped,
            latency_ms=percentiles(latency), end_to_end_ms=percentiles(end_to_end),
            response_read_ms=percentiles(response_read), validation_ms=percentiles(validation),
            payload_bytes=percentiles(payloads), samples=samples)
        folder = BASE/'benchmarks'
        folder.mkdir(exist_ok=True)
        label=args.backend+'-'+args.variant+'-'+time.strftime('%Y%m%dT%H%M%S')
        path=folder/(label+'.json')
        path.write_text(json.dumps(report, indent=2)+'\n')
        with gzip.open(folder/(label+'-samples.json.gz'), 'wt') as raw:
            json.dump({'latency_ms': list(latency), 'end_to_end_ms': list(end_to_end), 'payload_bytes': list(payloads),
                       'response_read_ms': list(response_read), 'validation_ms': list(validation)}, raw)
        print(json.dumps({k: v for k, v in report.items() if k not in ['samples', 'before', 'after']} | {'result': str(path)}))
    return report['status'] == 'passed'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=['php', 'rust'], required=True)
    parser.add_argument('--variant', choices=['original', 'legacy-fixed', 'candidate'], required=True)
    parser.add_argument('--rate', type=float, required=True)
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--warmup', type=int, default=30)
    parser.add_argument('--numwant', type=int, default=25)
    parser.add_argument('--monitor-interval', type=float, default=5,
                        help='Segundos entre snapshots SQL; zero desativa somente o observador periodico')
    parser.add_argument('--load', choices=['same-requests', 'same-population'], default='same-requests')
    args = parser.parse_args()
    assert 0 < args.rate <= 10000 and 1 <= args.seconds <= 21600 and 0 <= args.warmup <= 300 and 0 <= args.numwant <= 25
    assert 0 <= args.monitor_interval <= 60
    try:
        succeeded = asyncio.run(main(args))
    except Exception as error:
        print(json.dumps({'status': 'preflight_failed', 'error': type(error).__name__}))
        succeeded = False
    raise SystemExit(0 if succeeded else 1)
