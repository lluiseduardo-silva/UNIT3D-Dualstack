#!/usr/bin/env python3
"""Clientes reais em namespaces. Sem peers injetados e sem exportar passkeys."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
import urllib.parse

import libtorrent as lt
import pymysql
from baseline import safe_response

BASE = Path('/opt/unit3d-dualstack')
ROOT = BASE/'real-clients'
SIZE = 16 * 1024 * 1024
CASES = [
    ('qbit-transmission-v4', 'qbit', 'transmission', 'ipv4', None),
    ('qbit-transmission-v6', 'qbit', 'transmission', 'ipv6', None),
    ('transmission-qbit-v4', 'transmission', 'qbit', 'ipv4', None),
    ('transmission-qbit-v6', 'transmission', 'qbit', 'ipv6', None),
    ('qbit-transmission-dual', 'qbit', 'transmission', 'dual', None),
    ('transmission-qbit-dual', 'transmission', 'qbit', 'dual', None),
    ('qbit-fail-v4', 'qbit', 'qbit', 'dual', 4),
    ('qbit-fail-v6', 'qbit', 'qbit', 'dual', 6),
]


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def command(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=15, **kwargs).stdout.strip()


def connect():
    values = dict(line.split('=', 1) for line in (BASE/'database.env').read_text().splitlines())
    db = pymysql.connect(host='172.29.92.20', user=values['MYSQL_USER'], password=values['MYSQL_PASSWORD'],
                         database='unit3d_dualstack_journal_test', autocommit=True,
                         connect_timeout=3, read_timeout=5, write_timeout=5, cursorclass=pymysql.cursors.DictCursor)
    with db.cursor() as cursor:
        cursor.execute('SELECT DATABASE() AS name')
        check(cursor.fetchone()['name'] == 'unit3d_dualstack_journal_test', 'Banco incorreto')
    return db


def metainfo(label):
    payload = (ROOT/'payload.bin').read_bytes()
    pieces = b''.join(hashlib.sha1(payload[i:i+262144]).digest() for i in range(0, len(payload), 262144))
    return {b'name': b'dualstack.bin', b'length': len(payload), b'piece length': 262144,
            b'pieces': pieces, b'private': 1, b'source': ('unit3d-real-'+label).encode()}


def prepare():
    ROOT.mkdir(mode=0o700, exist_ok=True)
    (ROOT/'payload.bin').write_bytes(hashlib.shake_256(b'UNIT3D dualstack real clients v1').digest(SIZE))
    manifest = {'size': SIZE, 'sha256': hashlib.sha256((ROOT/'payload.bin').read_bytes()).hexdigest(), 'cases': []}
    with connect() as db, db.cursor() as cursor:
        cursor.execute('SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1')
        check(not cursor.fetchone()['live'], 'Interrompa o coordenador antes da fixture')
        cursor.execute('SELECT COUNT(*) AS count FROM peers')
        check(cursor.fetchone()['count'] == 0, 'Inicialize o banco isolado antes da fixture')
        cursor.execute('SELECT * FROM torrents WHERE id=12001')
        template = cursor.fetchone()
        check(template is not None, 'Fixture base ausente')
        for index, (label, seed, down, network, failure) in enumerate(CASES):
            info = metainfo(label)
            digest = hashlib.sha1(lt.bencode(info)).hexdigest()
            ident = 12101+index
            row = dict(template, id=ident, name='Real clients '+label, info_hash=bytes.fromhex(digest), size=SIZE,
                       seeders=0, leechers=0, times_completed=0, balance=0)
            columns = ','.join('`'+name+'`' for name in row)
            cursor.execute('INSERT INTO torrents ('+columns+') VALUES ('+','.join(['%s']*len(row))+')', list(row.values()))
            manifest['cases'].append(dict(label=label, seeder=seed, downloader=down, network=network,
                                          failure_family=failure, torrent_id=ident, info_hash=digest))
    (ROOT/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps({'prepared': len(CASES), 'sha256': manifest['sha256'], 'size': SIZE}))


class Client:
    def __init__(self, client, role, network, folder):
        self.client, self.role, self.network = client, role, network
        self.ns = 'ds-bt-'+role
        self.ipv4 = '172.29.92.'+('40' if role == 'seed' else '41')
        self.ipv6 = 'fd42:756e:6974:92::'+('40' if role == 'seed' else '41')
        self.folder = folder/role
        self.folder.mkdir(parents=True)
        self.data = self.folder/'data'
        self.data.mkdir()
        self.process = self.capture = None
        self.handles = []
        self.namespace_owned = self.link_owned = self.hosts_owned = False
        try:
            self.setup_network()
        except BaseException:
            self.close()
            raise

    def setup_network(self):
        network = self.network
        check(self.ns not in command('ip', 'netns', 'list'), 'Namespace ja existente: '+self.ns)
        check(not (Path('/etc/netns')/self.ns).exists(), 'Configuracao de namespace ja existe')
        command('ip', 'netns', 'add', self.ns)
        self.namespace_owned = True
        command('ip', 'link', 'add', self.ns, 'link', 'eth1', 'type', 'macvlan', 'mode', 'bridge')
        self.link_owned = True
        command('ip', 'link', 'set', self.ns, 'netns', self.ns)
        self.link_owned = False
        command('ip', '-n', self.ns, 'link', 'set', self.ns, 'name', 'bt0')
        self.exec('sysctl', '-qw', 'net.ipv6.conf.all.accept_ra=0', 'net.ipv6.conf.default.accept_ra=0')
        command('ip', '-n', self.ns, 'link', 'set', 'lo', 'up')
        command('ip', '-n', self.ns, 'link', 'set', 'bt0', 'up')
        if network != 'ipv6':
            command('ip', '-n', self.ns, 'addr', 'add', self.ipv4+'/24', 'dev', 'bt0')
        if network != 'ipv4':
            command('ip', '-n', self.ns, '-6', 'addr', 'add', self.ipv6+'/64', 'dev', 'bt0', 'nodad')
        else:
            self.exec('sysctl', '-qw', 'net.ipv6.conf.all.disable_ipv6=1')
        hosts = Path('/etc/netns')/self.ns
        hosts.mkdir(parents=True)
        self.hosts_owned = True
        content = '127.0.0.1 localhost\n::1 localhost\n'
        if network != 'ipv6':
            content += '172.29.92.10 tracker.dualstack.test\n'
        if network != 'ipv4':
            content += 'fd42:756e:6974:92::10 tracker.dualstack.test\n'
        (hosts/'hosts').write_text(content)
        (hosts/'resolv.conf').write_text('nameserver 127.0.0.1\noptions attempts:1 timeout:1\n')
        check(not self.exec('ip', 'route', 'show', 'default'), 'Namespace com rota externa')
        check(not self.exec('ip', '-6', 'route', 'show', 'default'), 'Namespace com rota IPv6 externa')

    def exec(self, *args):
        return command('ip', 'netns', 'exec', self.ns, *args)

    def rpc(self, method, data=None, torrent=None):
        request = {'client': self.client, 'method': method}
        if self.client == 'transmission' and self.network == 'ipv6':
            request['rpc_host'] = '::1'
        if data is not None:
            request['data'] = data
        if torrent is not None:
            request['torrent'] = base64.b64encode(torrent).decode()
        output = command('ip', 'netns', 'exec', self.ns, 'python3', str(BASE/'bt-rpc.py'), input=json.dumps(request))
        result = json.loads(output)
        check('rpc_error' not in result, 'Falha de RPC local')
        return result

    def start(self):
        log = (self.folder/'client-private.log').open('w')
        caplog = (self.folder/'capture.log').open('w')
        self.handles.extend([log, caplog])
        self.capture = subprocess.Popen(['ip', 'netns', 'exec', self.ns, 'tcpdump', '--immediate-mode', '-i', 'bt0', '-s', '0', '-U',
                                         '-w', str(self.folder/'private.pcap'), 'tcp'], stdout=caplog, stderr=caplog)
        time.sleep(0.2)
        if self.client == 'qbit':
            profile = self.folder/'profile'
            (profile/'qBittorrent/config').mkdir(parents=True)
            (profile/'qBittorrent/config/qBittorrent.conf').write_text(
                '[LegalNotice]\nAccepted=true\n[Preferences]\nWebUI\\Address=127.0.0.1\n'
                'WebUI\\Port=8088\nWebUI\\LocalHostAuth=false\nWebUI\\CSRFProtection=false\n'
                'WebUI\\HostHeaderValidation=false\n')
            args = ['qbittorrent-nox', '--profile='+str(profile), '--webui-port=8088']
        else:
            profile = self.folder/'profile'
            profile.mkdir()
            settings = {'rpc-bind-address': '::1' if self.network == 'ipv6' else '127.0.0.1',
                        'rpc-whitelist': '127.0.0.1,::1', 'rpc-port': 9091, 'rpc-authentication-required': False,
                        'dht-enabled': False, 'pex-enabled': False, 'lpd-enabled': False, 'port-forwarding-enabled': False,
                        'utp-enabled': False, 'encryption': 0, 'peer-port': 6881, 'peer-port-random-on-start': False,
                        'download-dir': str(self.data), 'speed-limit-down': 1024, 'speed-limit-down-enabled': True,
                        'ratio-limit-enabled': False, 'idle-seeding-limit-enabled': False,
                        'bind-address-ipv4': self.ipv4 if self.network != 'ipv6' else '127.0.0.1',
                        'bind-address-ipv6': self.ipv6 if self.network != 'ipv4' else '::1',
                        'scrape-paused-torrents-enabled': False}
            (profile/'settings.json').write_text(json.dumps(settings))
            args = ['transmission-daemon', '--foreground', '--config-dir', str(profile), '--log-level=error']
        runtime = self.folder/'runtime'
        runtime.mkdir(mode=0o700)
        self.process = subprocess.Popen(['ip', 'netns', 'exec', self.ns, *args], stdout=log, stderr=log,
                                        env=dict(os.environ, XDG_RUNTIME_DIR=str(runtime), TMPDIR=str(runtime)))
        for _ in range(30):
            try:
                self.rpc('app/version' if self.client == 'qbit' else 'session-get')
                break
            except Exception:
                check(self.process.poll() is None, 'Cliente encerrou durante inicializacao')
                time.sleep(0.2)
        else:
            raise AssertionError('RPC nao iniciou')
        if self.client == 'qbit':
            prefs = dict(dht=False, pex=False, lsd=False, upnp=False, encryption=2, bittorrent_protocol=1,
                         # O namespace so possui loopback e bt0, sem rota externa.
                         # libtorrent 2.0.10 tenta bind IPv4 em socket IPv6 quando
                         # outgoing_interfaces recebe um nome de interface (EINVAL).
                         listen_port=6881, random_port=False, current_network_interface='',
                         dl_limit=1024*1024, limit_lan_peers=True, announce_to_all_tiers=True,
                         announce_to_all_trackers=True, queueing_enabled=False)
            self.rpc('app/setPreferences', {'json': json.dumps(prefs)})

    def add(self, info, passkey):
        torrent = lt.bencode({b'info': info, b'announce': ('http://tracker.dualstack.test:8080/announce/'+passkey).encode()})
        if self.role == 'seed':
            os.link(ROOT/'payload.bin', self.data/'dualstack.bin')
        if self.client == 'qbit':
            self.rpc('torrents/add', {'savepath': str(self.data), 'paused': 'false', 'skip_checking': 'false'}, torrent)
        else:
            self.rpc('torrent-add', {'metainfo': base64.b64encode(torrent).decode(), 'download-dir': str(self.data), 'paused': False})

    def status(self):
        if self.client == 'qbit':
            rows = self.rpc('torrents/info')
            if not rows:
                return {'progress': 0, 'downloaded': 0, 'peers': []}
            row = rows[0]
            return {'progress': row['progress'], 'downloaded': row['downloaded'], 'state': row['state']}
        rows = self.rpc('torrent-get', {'fields': ['percentDone', 'downloadedEver', 'peers', 'status', 'error']})['torrents']
        if not rows:
            return {'progress': 0, 'downloaded': 0, 'peers': []}
        row = rows[0]
        return {'progress': row['percentDone'], 'downloaded': row['downloadedEver'], 'state': row['status'],
                'error': row['error'], 'peers': [{'address': p['address'], 'port': p['port']} for p in row['peers']]}

    def block(self, family, blocked=True):
        self.exec('iptables' if family == 4 else 'ip6tables', '-I' if blocked else '-D', 'OUTPUT',
                  '-o', 'bt0', '-p', 'tcp', '-j', 'REJECT', '--reject-with', 'tcp-reset')

    def pause(self):
        if self.client == 'qbit':
            self.rpc('torrents/pause', {'hashes': 'all'})
        else:
            self.rpc('torrent-stop', {})

    def peer_path(self, family, other, blocked):
        self.exec('iptables' if family == 4 else 'ip6tables', '-I' if blocked else '-D', 'OUTPUT',
                  '-d', other.ipv4 if family == 4 else other.ipv6,
                  '-p', 'tcp', '-j', 'REJECT', '--reject-with', 'tcp-reset')

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        if self.capture and self.capture.poll() is None:
            self.capture.send_signal(signal.SIGINT)
            try:
                self.capture.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.capture.kill()
                self.capture.wait(timeout=3)
        for handle in self.handles:
            handle.close()
        if self.link_owned:
            command('ip', 'link', 'delete', self.ns)
            self.link_owned = False
        if self.namespace_owned:
            command('ip', 'netns', 'delete', self.ns)
            self.namespace_owned = False
        path = Path('/etc/netns')/self.ns
        check(path.parent == Path('/etc/netns') and self.ns in ['ds-bt-seed', 'ds-bt-down'], 'Destino de limpeza invalido')
        if self.hosts_owned:
            shutil.rmtree(path)
            self.hosts_owned = False


def snapshot(torrent_id):
    with connect() as db, db.cursor() as cursor:
        result = {}
        for name, query in {
            'peers': 'SELECT user_id,torrent_id,HEX(peer_id) AS peer_id,state_version,uploaded,downloaded,`left`,active,seeder FROM peers WHERE torrent_id=%s ORDER BY user_id,peer_id',
            'endpoints': 'SELECT user_id,HEX(peer_id) AS peer_id,family,INET6_NTOA(ip) AS ip,port,revision FROM peer_ips WHERE torrent_id=%s ORDER BY user_id,peer_id,family',
            'history': 'SELECT user_id,state_version,actual_uploaded,actual_downloaded,uploaded,downloaded,seedtime,active,seeder FROM history WHERE torrent_id=%s ORDER BY user_id',
            'torrent': 'SELECT seeders,leechers,seeders_ipv4,seeders_ipv6,leechers_ipv4,leechers_ipv6,times_completed FROM torrents WHERE id=%s',
        }.items():
            cursor.execute(query, (torrent_id,))
            result[name] = cursor.fetchall()
        cursor.execute('SELECT id,uploaded,downloaded FROM users WHERE id IN (12001,12002) ORDER BY id')
        result['users'] = cursor.fetchall()
        return result


def capture_report(path, fixture):
    # HTTP cru fica apenas na memoria deste processo e no pcap privado.
    fields = ['frame.time_epoch', 'ip.src', 'ipv6.src', 'ip.dst', 'ipv6.dst', 'tcp.stream', 'http.request.uri',
              'http.response.code', 'http.file_data', 'bittorrent.peer_id', 'bittorrent.info_hash', 'bittorrent.msg.type', 'tcp.len']
    args = ['tshark', '-r', str(path), '-Y', 'http or bittorrent', '-T', 'fields', '-E', 'separator=|', '-E', 'occurrence=f']
    for field in fields:
        args += ['-e', field]
    raw = command(*args)
    users = {user['passkey']: user['id'] for user in fixture['users']}
    output = {'announces': [], 'responses': [], 'handshakes': [], 'pieces': []}
    for line in raw.splitlines():
        parts = line.split('|')
        if len(parts) != len(fields):
            continue
        at, ip4, ip6, dst4, dst6, stream, uri, code, body, peer, info, kind, length = parts
        family = 6 if ip6 else 4
        common = {'at': float(at), 'family': family, 'source': ip6 or ip4, 'destination': dst6 or dst4, 'stream': stream}
        if uri and '/announce/' in uri:
            parsed = urllib.parse.urlsplit(uri)
            values = urllib.parse.parse_qs(parsed.query, encoding='latin1', keep_blank_values=True)
            ident = values.get('peer_id', [''])[0].encode('latin1').hex()
            output['announces'].append(dict(common, user_id=users.get(parsed.path.rsplit('/', 1)[-1]), peer_id=ident,
                                            event=values.get('event', [''])[0],
                                            uploaded=int(values.get('uploaded', ['0'])[0]), downloaded=int(values.get('downloaded', ['0'])[0])))
        if body and code:
            try:
                decoded = safe_response(bytes.fromhex(body.replace(':', '')))
                output['responses'].append(dict(common, status=int(code), body=decoded))
            except (ValueError, IndexError, KeyError):
                pass
        if peer:
            output['handshakes'].append(dict(common, peer_id=peer.replace(':', ''), info_hash=info.replace(':', '')))
        if kind == '7':
            output['pieces'].append(dict(common, tcp_bytes=int(length)))
    return output


def run_case(case, backend, folder, fixture, manifest):
    result = {'case': case, 'status': 'running', 'progress': []}
    clients = []
    try:
        result['before_start'] = snapshot(case['torrent_id'])
        check(not result['before_start']['peers'] and not result['before_start']['history'],
              'O caso exige fixture limpa, sem peers ou historico anteriores')
        for role, kind in [('seed', case['seeder']), ('down', case['downloader'])]:
            clients.append(Client(kind, role, case['network'], folder))
        seed, down = clients
        if case['failure_family']:
            # Obrigar o caminho inicial sem injetar peers. Announces continuam
            # nas duas familias; somente o TCP entre clientes e bloqueado.
            remaining = 6 if case['failure_family'] == 4 else 4
            seed.peer_path(remaining, down, True)
            down.peer_path(remaining, seed, True)
        seed.start()
        seed.add(metainfo(case['label']), fixture['users'][0]['passkey'])
        for _ in range(90):
            state = snapshot(case['torrent_id'])
            if any(peer['seeder'] and peer['active'] for peer in state['peers']):
                break
            time.sleep(0.5)
        else:
            raise AssertionError('Seeder nao registrado pelo cliente real')
        result['before_download'] = state
        if case['network'] == 'dual':
            for _ in range(20):
                if {e['family'] for e in state['endpoints']} == {4, 6}:
                    break
                time.sleep(0.5)
                state = snapshot(case['torrent_id'])
            result['before_download'] = state
            check({e['family'] for e in state['endpoints']} == {4, 6},
                  'Seeder dualstack nao anunciou pelas duas familias')
            check(sum(bool(p['active']) for p in state['peers']) == 1,
                  'Seeder dualstack deveria representar um peer logico')
        down.start()
        down.add(metainfo(case['label']), fixture['users'][1]['passkey'])
        started = time.monotonic()
        failed = False
        while time.monotonic()-started < 180:
            status = down.status()
            result['progress'].append(dict(at=time.time(), **status))
            if case['failure_family'] and not failed and status['progress'] >= 0.15:
                remaining = 6 if case['failure_family'] == 4 else 4
                seed.peer_path(remaining, down, False)
                down.peer_path(remaining, seed, False)
                for client in clients:
                    client.block(case['failure_family'])
                result['failure'] = {'at': time.time(), 'family': case['failure_family'], 'progress': status['progress']}
                failed = True
            if status['progress'] >= 1:
                break
            time.sleep(0.5)
        else:
            raise AssertionError('Transferencia nao concluiu em 180 segundos')
        actual = hashlib.sha256((down.data/'dualstack.bin').read_bytes()).hexdigest()
        check(actual == manifest['sha256'], 'SHA256 divergente')
        result['sha256'] = actual
        time.sleep(1)
        result['after_download'] = snapshot(case['torrent_id'])
        check(sum(bool(peer['active']) for peer in result['after_download']['peers']) == 2, 'Clientes deveriam representar dois peers logicos ativos')
        if case['network'] == 'dual' and not case['failure_family']:
            for user in fixture['users'][:2]:
                endpoints = [e for e in result['after_download']['endpoints'] if e['user_id'] == user['id']]
                check(len(endpoints) == 2 and {e['family'] for e in endpoints} == {4, 6}
                      and len({e['peer_id'] for e in endpoints}) == 1,
                      'Cliente dualstack deve ter dois endpoints no mesmo peer')
        # A continuidade ja foi comprovada sob falha. Restaurar a rede permite
        # encerrar ambos os endpoints e conferir todo o credito observado.
        if case['failure_family']:
            for client in clients:
                client.block(case['failure_family'], False)
        for client in reversed(clients):
            client.pause()
        for _ in range(60):
            state = snapshot(case['torrent_id'])
            if not state['endpoints'] and not any(p['active'] for p in state['peers']):
                break
            time.sleep(0.5)
        else:
            raise AssertionError('Encerramento dos endpoints nao persistiu em 30 segundos')
        result['after_stop'] = state
        result['status'] = 'transferred'
    except Exception as error:
        result['status'] = 'failed'
        result['error'] = str(error) if isinstance(error, AssertionError) else type(error).__name__
    finally:
        for client in reversed(clients):
            client.close()
        for client in clients:
            pcap = client.folder/'private.pcap'
            if pcap.exists():
                result[client.role+'_wire'] = capture_report(pcap, fixture)
                result[client.role+'_capture'] = (client.folder/'capture.log').read_text()
    if result['status'] == 'transferred':
        try:
            wire = result['down_wire']
            check(wire['handshakes'], 'Handshake ausente da captura')
            check(wire['responses'], 'Respostas announce ausentes da captura')
            check(any(r['body'].get('peers') or r['body'].get('peers6') for r in wire['responses']), 'Nenhum endpoint recebido do tracker')
            if case['network'] == 'dual':
                check(any(r['body'].get('peers') and r['body'].get('peers6') for r in wire['responses']),
                      'Resposta dualstack nao devolveu as duas familias do seeder')
                for role in ['seed_wire', 'down_wire']:
                    announces = [a for a in result[role]['announces'] if a['event'] != 'stopped']
                    check({a['family'] for a in announces} == {4, 6}
                          and len({a['peer_id'] for a in announces}) == 1,
                          'Cliente nao anunciou a mesma identidade nas duas familias')
            families = {h['family'] for h in wire['handshakes']}
            if case['network'] != 'dual':
                check(families == {4 if case['network'] == 'ipv4' else 6}, 'Familia de handshake divergente')
            if case['failure_family']:
                failure = result['failure']
                remaining = 6 if failure['family'] == 4 else 4
                check(any(p['family'] == failure['family'] and p['at'] < failure['at'] for p in wire['pieces']), 'Familia interrompida nao transferia dados antes da falha')
                check(any(p['family'] == remaining and p['at'] > failure['at'] for p in wire['pieces']), 'Nao houve transferencia na familia restante')
            final = result['after_stop']
            check(len(final['peers']) == 2 and len(final['history']) == 2,
                  'Esperados dois peers e dois historicos no fechamento')
            check(not any(h['active'] for h in final['history']), 'Historico ativo apos os dois clientes pararem')
            counts = final['torrent'][0]
            check(counts['times_completed'] == 1, 'Conclusao ausente ou duplicada')
            check(all(counts[k] == 0 for k in counts if k != 'times_completed'), 'Contagem residual apos stopped')
            result['accounting'] = []
            for role, user in zip(['seed_wire', 'down_wire'], fixture['users'][:2]):
                capture = result[role]
                ok = {r['stream'] for r in capture['responses']
                      if r['status'] == 200 and 'failure reason' not in r['body']}
                announces = [a for a in capture['announces'] if a['stream'] in ok]
                check(announces and announces[0]['event'] == 'started', 'Referencia inicial ausente na captura')
                families = {4, 6} if case['network'] == 'dual' else {4 if case['network'] == 'ipv4' else 6}
                check({a['family'] for a in announces if a['event'] == 'stopped'} == families,
                      'Stopped confirmado deve abranger cada familia anunciada')
                peer = next(p for p in final['peers'] if p['user_id'] == user['id'])
                history = next(h for h in final['history'] if h['user_id'] == user['id'])
                before_user = next(u for u in result['before_start']['users'] if u['id'] == user['id'])
                after_user = next(u for u in final['users'] if u['id'] == user['id'])
                entry = {'user_id': user['id'], 'peer_id': peer['peer_id'], 'state_version': peer['state_version']}
                for field in ['uploaded', 'downloaded']:
                    maximum = max(a[field] for a in announces)
                    delta = maximum-announces[0][field]
                    check(int(peer[field]) == maximum, 'Referencia do peer difere do contador observado')
                    check(int(history['actual_'+field]) == delta, 'Historico real diverge do delta unico')
                    check(int(history[field]) == delta, 'Credito do historico diverge na fixture sem fatores')
                    check(int(after_user[field])-int(before_user[field]) == delta, 'Saldo do usuario diverge do delta unico')
                    entry[field] = delta
                result['accounting'].append(entry)
            check(result['accounting'][0]['uploaded'] >= SIZE and result['accounting'][1]['downloaded'] >= SIZE,
                  'Credito final nao abrange o arquivo transferido')
            result['status'] = 'passed'
        except AssertionError as error:
            result['status'], result['error'] = 'failed', str(error)
    # Evita arquivos extensos: preservar handshakes e resumo temporal dos pacotes piece.
    for role in ['seed_wire', 'down_wire']:
        if role in result:
            packets = result[role].pop('pieces')
            result[role]['pieces_summary'] = {str(f): {'packets': sum(p['family'] == f for p in packets),
                'tcp_bytes': sum(p['tcp_bytes'] for p in packets if p['family'] == f),
                'first_at': min((p['at'] for p in packets if p['family'] == f), default=None),
                'last_at': max((p['at'] for p in packets if p['family'] == f), default=None)} for f in [4, 6]}
    (folder/'result.json').write_text(json.dumps(result, indent=2, default=str)+'\n')
    print(json.dumps({'backend': backend, 'case': case['label'], 'status': result['status'], 'error': result.get('error')}), flush=True)
    return result['status'] == 'passed'


def main():
    check(os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients', 'Exige root na VM clientes do laboratorio')
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--backend', choices=['php', 'rust'])
    parser.add_argument('--case', default='all')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
        return
    check(args.backend is not None, 'Informe backend')
    manifest = json.loads((ROOT/'manifest.json').read_text())
    fixture = json.loads((BASE/'fixture.json').read_text())
    with connect() as db, db.cursor() as cursor:
        cursor.execute('SELECT backend,generation,lease_expires_at>UTC_TIMESTAMP(3) AS live FROM tracker_ownership WHERE id=1')
        owner = cursor.fetchone()
        check(owner['live'] and owner['backend'] == args.backend, 'Backend ativo nao corresponde ao ensaio')
    cases = [case for case in manifest['cases'] if args.case == 'all' or case['label'] in args.case.split(',')]
    check(cases, 'Caso desconhecido')
    folder = ROOT/(args.backend+'-'+time.strftime('%Y%m%dT%H%M%S'))
    folder.mkdir()
    transmission_version = subprocess.run(['transmission-daemon', '--version'], check=True,
                                         text=True, capture_output=True, timeout=5)
    versions = {'qbit': command('qbittorrent-nox', '--version'),
                'transmission': (transmission_version.stdout+transmission_version.stderr).strip(),
                'libtorrent': lt.version, 'tshark': command('tshark', '--version').splitlines()[0], 'owner': owner}
    (folder/'versions.json').write_text(json.dumps(versions, indent=2)+'\n')
    for case in cases:
        case_folder = folder/case['label']
        case_folder.mkdir()
        if not run_case(case, args.backend, case_folder, fixture, manifest):
            raise SystemExit(1)
    print(json.dumps({'status': 'passed', 'cases': len(cases), 'backend': args.backend, 'results': str(folder)}))


if __name__ == '__main__':
    main()
