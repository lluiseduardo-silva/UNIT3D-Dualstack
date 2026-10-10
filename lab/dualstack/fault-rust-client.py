#!/usr/bin/env python3
"""Controle HTTP/SQL local; nunca exporta URL, passkey ou credenciais."""
import argparse
import http.client
import json
import os
from pathlib import Path
import select
import socket
import sys
import time
import urllib.parse

from density_common import bdecode, connect

assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients'
parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['state', 'block', 'burst'])
parser.add_argument('--base', type=int, default=0)
parser.add_argument('--step', type=int, default=100)
parser.add_argument('--count', type=int, default=1)
args = parser.parse_args()
assert 1 <= args.count <= 200 and args.base >= 0 and args.step >= 0


def state():
    statements = {
        'owner': 'SELECT generation,COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1',
        'peer': 'SELECT uploaded,state_version FROM peers WHERE user_id=12001 AND torrent_id=12001',
        'history': 'SELECT uploaded,actual_uploaded,state_version FROM history WHERE user_id=12001 AND torrent_id=12001',
        'user': 'SELECT uploaded FROM users WHERE id=12001',
        'endpoints': 'SELECT family,revision FROM peer_ips WHERE user_id=12001 AND torrent_id=12001 ORDER BY family',
        'counts': 'SELECT seeders,seeders_ipv4,seeders_ipv6 FROM torrents WHERE id=12001',
        'queries': "SELECT COUNT(*) AS n FROM information_schema.PROCESSLIST WHERE DB=DATABASE() AND ID<>CONNECTION_ID() AND COMMAND<>'Sleep'",
    }
    with connect() as db, db.cursor() as c:
        out = {}
        for key, query in statements.items():
            c.execute(query)
            out[key] = c.fetchall()
        db.rollback()
    return out


def burst():
    fixture = json.loads(Path('/opt/unit3d-dualstack/fixture.json').read_text())
    connections = {}
    start = time.monotonic()
    accepted = 0
    try:
        for index in range(args.count):
            family = 4 if index % 2 == 0 else 6
            if family not in connections:
                target, source = ('172.29.92.10', '172.29.92.30') if family == 4 else ('fd42:756e:6974:92::10', 'fd42:756e:6974:92::30')
                connections[family] = http.client.HTTPConnection(target, 8080, timeout=2, source_address=(source, 0))
            params = dict(info_hash=bytes.fromhex(fixture['torrents'][0]['info_hash_hex']),
                peer_id=b'-DS9200-000000000091', port=6881, uploaded=args.base+(index+1)*args.step,
                downloaded=0, left=0, event='completed', compact=1, numwant=0)
            query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
            connection = connections[family]
            connection.request('GET', '/announce/'+fixture['users'][0]['passkey']+'?'+query,
                headers={'User-Agent': 'libtorrent/2.0.10'})
            response = connection.getresponse()
            body = bdecode(response.read())
            assert response.status == 200 and b'failure reason' not in body and b'warning message' not in body, 'announce_rejected'
            accepted += 1
    finally:
        for connection in connections.values():
            connection.close()
    return dict(accepted=accepted, uploaded=args.base+accepted*args.step,
        duration_seconds=time.monotonic()-start, families=[4, 6] if accepted > 1 else [4])


try:
    if args.mode == 'state':
        result = state()
    elif args.mode == 'burst':
        result = burst()
    else:
        with connect() as db, db.cursor() as c:
            c.execute('SELECT id FROM users WHERE id=12001 FOR UPDATE')
            assert c.fetchone()['id'] == 12001
            print(json.dumps(dict(ready=True)), flush=True)
            # EOF ou sinal do orquestrador libera o lock; limite de seguranca 10 s.
            if select.select([sys.stdin], [], [], 10)[0]:
                sys.stdin.readline()
            db.rollback()
        result = dict(released=True)
    print(json.dumps(result, default=str), flush=True)
except Exception as error:
    print(json.dumps(dict(status='failed', error_type=type(error).__name__)), flush=True)
    raise SystemExit(1)
