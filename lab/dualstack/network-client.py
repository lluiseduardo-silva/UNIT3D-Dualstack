#!/usr/bin/env python3
"""TLS/proxy/probes reais; exporta apenas evidencias sem credenciais."""
import argparse
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import threading
import time
import urllib.parse

from density_common import BASE, bdecode, connect

SOURCES = {4: '172.29.92.30', 6: 'fd42:756e:6974:92::30'}
TARGETS = {4: '172.29.92.10', 6: 'fd42:756e:6974:92::10'}


class Listener:
    def __init__(self, family, port, source=None):
        self.count = 0
        self.done = threading.Event()
        self.socket = socket.socket(socket.AF_INET if family == 4 else socket.AF_INET6)
        if family == 6:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((source or SOURCES[family], port))
        self.socket.listen(128)
        self.socket.settimeout(.1)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.done.is_set():
            try:
                client, _ = self.socket.accept()
                self.count += 1
                client.close()
            except socket.timeout:
                continue
            except OSError:
                break

    def close(self):
        self.done.set()
        self.socket.close()
        self.thread.join(.5)


class Client:
    def __init__(self):
        self.fixture = json.loads((BASE/'fixture.json').read_text())
        self.ca = BASE/'network-ca.crt'

    def announce(self, family=4, port=46881, uploaded=1000, observer=False,
                 version=ssl.TLSVersion.TLSv1_3, source=None, event='completed'):
        context = ssl.create_default_context(cafile=str(self.ca))
        context.minimum_version = context.maximum_version = version
        connection = http.client.HTTPSConnection(TARGETS[family], 8443, context=context,
            timeout=5, source_address=(source or SOURCES[family], 0))
        params = dict(info_hash=bytes.fromhex(self.fixture['torrents'][0]['info_hash_hex']),
            peer_id=b'-DS9200-000000000002' if observer else b'-DS9200-000000000001',
            port=port, uploaded=0 if observer else uploaded, downloaded=0, left=100 if observer else 0,
            event=event, compact=1, numwant=1 if observer else 0,
            ip='192.0.2.99', ipv4='127.0.0.1', ipv6='2001:db8::bad')
        try:
            connection.connect()
            negotiated = connection.sock.version()
            cipher = connection.sock.cipher()[0]
            query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
            connection.request('GET', '/announce/'+self.fixture['users'][1 if observer else 0]['passkey']+'?'+query,
                headers={'User-Agent': 'libtorrent/2.0.10', 'X-Real-IP': '2001:db8::bad',
                         'X-Forwarded-For': '192.0.2.99, 127.0.0.1', 'Forwarded': 'for=192.0.2.99'})
            response = connection.getresponse()
            result = bdecode(response.read())
            reason = result.get(b'failure reason', b'').decode('utf-8', errors='replace')
            for user in self.fixture['users']:
                reason = reason.replace(user['passkey'], '[redacted]')
            assert response.status == 200 and not reason, 'announce_rejected: '+reason[:256]
            return dict(tls=negotiated, cipher=cipher, family=family, complete=result[b'complete'],
                incomplete=result[b'incomplete'], peers_bytes=len(result.get(b'peers', b'')),
                peers6_bytes=len(result.get(b'peers6', b'')), warning=b'warning message' in result)
        finally:
            connection.close()

    def state(self):
        with connect() as db, db.cursor() as c:
            result = {}
            for key, query in {
                'endpoints': 'SELECT family,INET6_NTOA(ip) AS ip,port,connectable,revision FROM peer_ips WHERE user_id=12001 ORDER BY family',
                'peer': 'SELECT uploaded,state_version,connectable FROM peers WHERE user_id=12001',
                'user': 'SELECT uploaded FROM users WHERE id=12001',
                'history': 'SELECT uploaded,actual_uploaded FROM history WHERE user_id=12001',
                'counts': 'SELECT seeders,seeders_ipv4,seeders_ipv6 FROM torrents WHERE id=12001',
            }.items():
                c.execute(query)
                result[key] = c.fetchall()
            db.rollback()
        return result

    def wait(self, predicate, timeout=8):
        end = time.monotonic()+timeout
        while True:
            state = self.state()
            if predicate(state):
                return state
            assert time.monotonic() < end, 'state_timeout'
            time.sleep(.05)


def main():
    assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients'
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=['php', 'rust'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), 'existing_result'
    client = Client()
    report = dict(status='running', backend=args.backend, steps=[])
    listeners = []
    rule = ['-i','eth1','-s',TARGETS[4],'-d',SOURCES[4],'-p','tcp','--dport','46889','-j','UNIT3DDS_PROBE']
    firewall = False

    def record(label, value):
        report['steps'].append(dict(label=label, result=value))
        print(label, flush=True)

    def listen(family, port):
        value = Listener(family, port)
        listeners.append(value)
        return value

    def expect(v4, v6):
        return client.wait(lambda s: [(e['family'], e['connectable']) for e in s['endpoints']] == [(4,v4),(6,v6)])

    def listed(label, v4, v6):
        # O cliente observador PHP tambem precisa receber sua primeira checagem.
        end = time.monotonic()+8
        while True:
            result = client.announce(observer=True)
            if result['peers_bytes'] == v4 and result['peers6_bytes'] == v6 and result['complete'] == 1:
                record(label, result)
                return
            assert time.monotonic() < end, 'response_timeout'
            time.sleep(.3)

    try:
        listen(4,46881)
        listen(6,46881)
        for family in [4,6]:
            for version in [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3]:
                result = client.announce(family, version=version)
                assert result['tls'] == ('TLSv1.2' if version == ssl.TLSVersion.TLSv1_2 else 'TLSv1.3')
                record('tls-verificado-'+str(family)+'-'+result['tls'], result)
        state = expect(1,1)
        assert [e['ip'] for e in state['endpoints']] == list(SOURCES.values())
        record('origens-reais-headers-forjados-ignorados', state)
        for mode in ['unknown-ca', 'wrong-name']:
            context = ssl.create_default_context(cafile=str(client.ca) if mode == 'wrong-name' else None)
            try:
                with socket.create_connection((TARGETS[4],8443), timeout=3) as raw:
                    with context.wrap_socket(raw, server_hostname='invalid.lab' if mode=='wrong-name' else TARGETS[4]):
                        raise AssertionError('invalid_certificate_accepted')
            except ssl.SSLCertVerificationError:
                record('certificado-recusado-'+mode, True)
        for family in [4,6]:
            try:
                socket.create_connection((TARGETS[family],6969), timeout=.5).close()
                raise AssertionError('backend_exposed')
            except (ConnectionRefusedError, TimeoutError, OSError) as error:
                record('backend-loopback-'+str(family), type(error).__name__)
        client.announce(6,46883,1100)
        record('falha-ipv6-isolada', expect(1,0))
        listed('lista-ipv4-preservada',6,0)
        listen(6,46882)
        client.announce(6,46882,1100)
        expect(1,1)
        listed('lista-dualstack',6,18)
        client.announce(4,46885,1100)
        record('falha-ipv4-isolada', expect(0,1))
        listed('lista-ipv6-preservada',0,18)
        client.announce(4,46881,1100)
        expect(1,1)
        listed('lista-restaurada',6,18)

        subprocess.run(['iptables','-N','UNIT3DDS_PROBE'],check=True,capture_output=True)
        firewall = True
        subprocess.run(['iptables','-A','UNIT3DDS_PROBE','-j','DROP'],check=True,capture_output=True)
        subprocess.run(['iptables','-I','INPUT','1']+rule,check=True,capture_output=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(client.announce,4,46889,1200)
            end = time.monotonic()+4
            while True:
                rows = subprocess.check_output(['iptables','-L','UNIT3DDS_PROBE','-nvx'],text=True)
                packets = sum(int(line.split()[0]) for line in rows.splitlines() if 'DROP' in line)
                if packets > 0:
                    break
                assert time.monotonic() < end, 'probe_not_observed'
                time.sleep(.02)
            client.announce(4,46881,1300)
            pending.result(timeout=5)
        time.sleep(1.2)
        state = expect(1,1)
        assert state['endpoints'][0]['port'] == 46881
        assert state['user'][0]['uploaded'] == 300
        assert state['history'][0] == dict(uploaded=300,actual_uploaded=300)
        record('probe-atrasado-nao-altera-substituto', dict(dropped_probe_packets=packets,state=state))

        temporary = listen(4,46900)
        client.announce(4,46900,1300)
        client.wait(lambda s: len(s['endpoints']) == 2 and s['endpoints'][0]['port'] == 46900
            and s['endpoints'][0]['connectable'] == 1 and temporary.count > 0)
        temporary.close()
        client.announce(4,46900,1300)
        record('resultado-positivo-ainda-vigente', expect(1,1))
        time.sleep(4.2)
        client.announce(4,46900,1300)
        record('ttl-revalida-porta-fechada', expect(0,1))
        client.announce(4,46881,1300)
        expect(1,1)
        listed('fim-dualstack',6,18)
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__,
            error=str(error) if isinstance(error,AssertionError) else 'Consultar diagnostico local')
        raise
    finally:
        if firewall:
            subprocess.run(['iptables','-D','INPUT']+rule,check=True,capture_output=True)
            subprocess.run(['iptables','-F','UNIT3DDS_PROBE'],check=True,capture_output=True)
            subprocess.run(['iptables','-X','UNIT3DDS_PROBE'],check=True,capture_output=True)
        report['tcp_accepts'] = sum(listener.count for listener in listeners)
        for listener in listeners:
            listener.close()
        report['final'] = client.state()
        args.output.write_text(json.dumps(report,indent=2,default=str)+'\n')


if __name__ == '__main__':
    main()
