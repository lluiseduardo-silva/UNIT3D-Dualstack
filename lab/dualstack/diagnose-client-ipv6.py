#!/usr/bin/env python3
"""Isola o bind IPv6 do libtorrent 2.0.10; nao executa a matriz funcional."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time

BASE = Path('/opt/unit3d-dualstack')
sys.path.insert(0, str(BASE))
spec = importlib.util.spec_from_file_location('real_clients', BASE/'real-clients.py')
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)


def main():
    bt.check(os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients',
             'Exige root na VM clientes do laboratorio')
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('variant', choices=['original', 'unbound', 'explicit'])
    args = parser.parse_args()
    fixture = json.loads((BASE/'fixture.json').read_text())
    manifest = json.loads((bt.ROOT/'manifest.json').read_text())
    case = next(c for c in manifest['cases'] if c['label'] == 'transmission-qbit-v6')
    folder = bt.ROOT/('diagnosis-'+args.variant+'-'+time.strftime('%Y%m%dT%H%M%S'))
    folder.mkdir()

    def clean(value):
        text = str(value)
        for user in fixture['users']:
            text = text.replace(user['passkey'], 'REDACTED')
        return re.sub(r'https?://[^\s<>\"]+', '[URL]', text)

    def inspect(client):
        digest = case['info_hash']
        prefs = client.rpc('app/preferences')
        return {
            'status': client.status(),
            'preferences': {key: prefs.get(key) for key in [
                'current_network_interface', 'current_interface_address',
                'ip_filter_enabled', 'banned_IPs', 'proxy_type',
                'bittorrent_protocol', 'encryption', 'listen_port']},
            'trackers': [{key: clean(value) if isinstance(value, str) else value
                          for key, value in tracker.items() if key != 'url'}
                         for tracker in client.rpc('torrents/trackers?hash='+digest)],
            'peers': client.rpc('sync/torrentPeers?hash='+digest),
        }

    # Probe separado, identificado pelo peer_id. Nao adiciona peers ao cliente,
    # nao anuncia e nao solicita pecas. Nunca representa transferencia aprovada.
    probe = '''import json, socket, sys, time
digest = bytes.fromhex(sys.argv[1])
with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
    sock.settimeout(3)
    sock.bind(('fd42:756e:6974:92::41', 0))
    sock.connect(('fd42:756e:6974:92::40', 6881))
    sock.sendall(b'\\x13BitTorrent protocol'+b'\\0'*8+digest+b'-DSDIAG-'+b'0'*12)
    response = b''
    while len(response) < 68:
        part = sock.recv(68-len(response))
        if not part: break
        response += part
    print(json.dumps({'at': time.time(), 'diagnostic_only': True,
        'tcp_connected': True,
        'bittorrent_handshake': len(response) == 68 and response[28:48] == digest,
        'remote_peer_id': response[48:68].hex()}))
'''
    clients = []
    trace = trace_handle = None
    result = {'variant': args.variant, 'diagnostic_only': True, 'samples': []}
    try:
        for role, kind in [('seed', 'transmission'), ('down', 'qbit')]:
            clients.append(bt.Client(kind, role, 'ipv6', folder))
        seed, down = clients
        seed.start()
        seed.add(bt.metainfo(case['label']), fixture['users'][0]['passkey'])
        for _ in range(80):
            state = bt.snapshot(case['torrent_id'])
            if any(peer['active'] and peer['seeder'] for peer in state['peers']):
                break
            time.sleep(0.25)
        else:
            raise AssertionError('Seeder nao registrado')
        down.start()
        binding = {'current_network_interface': '' if args.variant == 'unbound' else 'bt0',
                   'current_interface_address': down.ipv6 if args.variant == 'explicit' else ''}
        down.rpc('app/setPreferences', {'json': json.dumps(binding)})
        trace_handle = (folder/'strace-private.log').open('w')
        trace = subprocess.Popen([
            'strace', '-f', '-p', str(down.process.pid), '-e',
            'trace=socket,bind,connect,getsockopt,setsockopt',
            '-o', str(folder/'network.trace')], stdout=trace_handle, stderr=trace_handle)
        time.sleep(0.3)
        bt.check(trace.poll() is None, 'strace nao iniciou')
        down.add(bt.metainfo(case['label']), fixture['users'][1]['passkey'])
        started = time.monotonic()
        probed = False
        while time.monotonic()-started < 60:
            status = down.status()
            if not result['samples'] or time.monotonic()-started > result['samples'][-1]['elapsed']+10:
                sample = {'elapsed': round(time.monotonic()-started, 2), **inspect(down)}
                result['samples'].append(sample)
                print(json.dumps({'variant': args.variant, 'elapsed': sample['elapsed'],
                                  'status': status}), flush=True)
            if time.monotonic()-started > 20 and not probed:
                result['network'] = {c.role: {'routes': c.exec('ip', '-6', 'route'),
                                             'listeners': c.exec('ss', '-lnt')} for c in clients}
                result['manual_handshake'] = json.loads(down.exec('python3', '-c', probe, case['info_hash']))
                probed = True
            if status['progress'] >= 1:
                result['sha256'] = hashlib.sha256((down.data/'dualstack.bin').read_bytes()).hexdigest()
                result['elapsed'] = time.monotonic()-started
                bt.check(result['sha256'] == manifest['sha256'], 'SHA256 divergente')
                break
            time.sleep(0.5)
        result['last'] = inspect(down)
        result['transmission'] = seed.rpc('torrent-get', {
            'fields': ['status', 'error', 'percentDone', 'peersConnected', 'rateUpload', 'leftUntilDone']})
    finally:
        if trace:
            if trace.poll() is None:
                trace.send_signal(signal.SIGINT)
                trace.wait(timeout=5)
            trace_handle.close()
        for client in reversed(clients):
            client.close()
        for client in clients:
            pcap = client.folder/'private.pcap'
            if pcap.exists():
                wire = bt.capture_report(pcap, fixture)
                wire['piece_packets'] = len(wire.pop('pieces'))
                result[client.role+'_wire'] = wire
        trace_path = folder/'network.trace'
        if trace_path.exists():
            # Somente syscalls de rede: nunca incluir send/recv/read/write.
            result['network_calls'] = [line for line in trace_path.read_text().splitlines()
                                       if re.search(r'\b(socket|bind|connect|setsockopt)\(', line)]
        payload = json.dumps(result, indent=2)
        bt.check(all(user['passkey'] not in payload for user in fixture['users']), 'Saida privada recusada')
        (folder/'diagnostic.json').write_text(payload+'\n')
        print(json.dumps({'diagnostic': str(folder/'diagnostic.json'),
                          'sha256': result.get('sha256')}), flush=True)
    if args.variant == 'original':
        bt.check(not result.get('sha256') and result['last']['status']['downloaded'] == 0,
                 'Controle negativo nao reproduziu a falha')
        bt.check(any('EINVAL' in line and 'sa_family=AF_INET,' in line
                     for line in result['network_calls']), 'Bind IPv4 incorreto nao observado')
        bt.check(result['manual_handshake']['bittorrent_handshake'], 'Transmission nao respondeu ao probe')
    else:
        bt.check(result.get('sha256') == manifest['sha256'], 'Controle positivo nao transferiu')


if __name__ == '__main__':
    main()
