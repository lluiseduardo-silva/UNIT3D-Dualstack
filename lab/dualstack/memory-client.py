#!/usr/bin/env python3
"""Rotacao limitada de IPs reais; nao mede capacidade ou throughput maximo."""
import argparse
from collections import deque
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import time

spec = importlib.util.spec_from_file_location('network_client', Path(__file__).with_name('network-client.py'))
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)


def main():
    assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients'
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=['php', 'rust'], required=True)
    parser.add_argument('--batches', type=int, default=8)
    parser.add_argument('--batch-size', type=int, default=256)
    parser.add_argument('--idle-seconds', type=int, default=12)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert 1 <= args.batches <= 8 and 1 <= args.batch_size <= 256
    assert 12 <= args.idle_seconds <= 130
    assert not args.output.exists()
    client = network.Client()
    listeners = [network.Listener(4, 47000)]
    listeners += [network.Listener(6, 47000+i, '::') for i in range(16)]
    aliases = deque()
    owned = set()
    report = dict(backend=args.backend, status='running', maximum_request_rate=20,
        batches=[], started_at=time.time())

    def remove(address):
        subprocess.run(['ip','-6','addr','del',address+'/128','dev','eth1'],check=True,capture_output=True)
        owned.remove(address)

    try:
        before = client.state()
        reference = before['peer'][0]['uploaded'] if before['peer'] else 1000
        credit = before['user'][0]['uploaded']
        client.announce(4, 47000, reference)
        client.wait(lambda s: len(s['endpoints']) >= 1 and s['endpoints'][0]['port'] == 47000
            and s['endpoints'][0]['connectable'] == 1)
        report['before'] = client.state()
        deadline = time.monotonic()
        sequence = 0
        for batch in range(args.batches):
            for _ in range(args.batch_size):
                # Proxima request pelo menos 50 ms depois do inicio anterior.
                time.sleep(max(0, deadline-time.monotonic()))
                deadline = time.monotonic()+.05
                sequence += 1
                address = str(ipaddress.IPv6Address(f'fd42:756e:6974:92:d5:0:0:{sequence:x}'))
                subprocess.run(['ip','-6','addr','add',address+'/128','dev','eth1','nodad'],check=True,capture_output=True)
                owned.add(address)
                aliases.append((time.monotonic(),address))
                client.announce(6,47000+sequence%16,reference+sequence,source=address)
                while len(aliases) > 1 and time.monotonic()-aliases[0][0] > 1.5:
                    remove(aliases.popleft()[1])
            state = client.wait(lambda s: len(s['endpoints']) == 2
                and s['endpoints'][1]['ip'] == address and s['peer'][0]['uploaded'] == reference+sequence
                and s['user'][0]['uploaded'] == credit+sequence)
            assert len(state['peer']) == 1
            assert state['endpoints'][0]['ip'] == network.SOURCES[4]
            assert state['history'][0]['actual_uploaded'] == credit+sequence
            report['batches'].append(dict(batch=batch+1,rotations=sequence,at=time.time(),state=state))
            print(json.dumps(dict(batch=batch+1,rotations=sequence,at=time.time())),flush=True)
        # Deixa probes e writer terminarem, mantendo a ultima origem acessivel.
        client.wait(lambda s: len(s['endpoints']) == 2 and all(e['connectable'] == 1 for e in s['endpoints']))
        report['rotation_finished_at'] = time.time()
        time.sleep(args.idle_seconds)
        report['idle'] = client.state()
        client.announce(6,47000,reference+sequence)
        client.wait(lambda s: len(s['endpoints']) == 2 and s['endpoints'][1]['ip'] == network.SOURCES[6]
            and all(e['connectable'] == 1 for e in s['endpoints']))
        report['final'] = client.state()
        assert report['final']['user'][0]['uploaded'] == credit+sequence
        report.update(status='passed',rotations=sequence,finished_at=time.time())
    except Exception as error:
        report.update(status='failed',error_type=type(error).__name__,
            error=str(error) if isinstance(error,AssertionError) else 'Consultar diagnostico local')
        raise
    finally:
        for address in sorted(owned.copy()):
            remove(address)
        for listener in listeners:
            listener.close()
        report['aliases_remaining'] = len(owned)
        args.output.write_text(json.dumps(report,indent=2,default=str)+'\n')


if __name__ == '__main__':
    main()
