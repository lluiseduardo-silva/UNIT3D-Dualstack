#!/usr/bin/env python3
"""Auditoria SQL somente leitura após o encerramento; não inicia carga."""
import argparse
import json
from pathlib import Path
import socket
import sys

sys.path.insert(0, '/opt/unit3d-dualstack')
from density_common import connect, snapshot

assert socket.gethostname() == 'unit3d-ds-clients'
parser = argparse.ArgumentParser()
parser.add_argument('name')
args = parser.parse_args()
assert all(c.isalnum() or c == '-' for c in args.name)
root = Path('/mnt/unit3d-archive/results/soak') / args.name
final = json.loads((root / 'final.json').read_text())
state = snapshot()
with connect() as db, db.cursor() as cursor:
    cursor.execute('SELECT DATABASE() AS name')
    assert cursor.fetchone()['name'] == 'unit3d_dualstack_journal_test'
    queries = {
        'families': 'SELECT family,COUNT(*) AS n FROM peer_ips WHERE user_id>=20000 GROUP BY family',
        'peer_history_mismatches': 'SELECT COUNT(*) AS n FROM peers p LEFT JOIN history h USING(user_id,torrent_id) WHERE p.user_id>=20000 AND (h.user_id IS NULL OR p.uploaded<>h.actual_uploaded OR p.uploaded<>h.uploaded)',
        'user_credit_mismatches': 'SELECT COUNT(*) AS n FROM users u LEFT JOIN (SELECT user_id,SUM(uploaded) AS uploaded FROM peers WHERE user_id>=20000 GROUP BY user_id) p ON p.user_id=u.id WHERE u.id>=20000 AND (p.user_id IS NULL OR u.uploaded<>p.uploaded OR u.seedbonus<>0)',
        'torrents': 'SELECT COUNT(*) AS n,SUM(seeders) AS seeders,SUM(leechers) AS leechers,SUM(seeders_ipv4) AS seeders_ipv4,SUM(seeders_ipv6) AS seeders_ipv6,SUM(leechers_ipv4) AS leechers_ipv4,SUM(leechers_ipv6) AS leechers_ipv6,SUM(times_completed) AS times_completed FROM torrents WHERE id>=20000',
        'owner': 'SELECT backend,generation,COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1',
    }
    checks = {}
    for label, query in queries.items():
        cursor.execute(query)
        checks[label] = cursor.fetchall()
credit = final['audit']['credit']
assert all(state[table]['uploaded'] == credit for table in ('peers', 'history', 'users'))
# Expiração pode produzir uma transição sem request; auditoria individual no
# gerador restringe essa diferença ao peer de controle de expiração.
extra=state['peers']['versions']-final['accepted']
assert extra==0 or (extra==1 and final['expiry_checked']), 'version_count'
assert state['peers']['n'] == final['audit']['peers']
assert state['peer_ips']['n'] == final['audit']['endpoints']
assert checks['peer_history_mismatches'][0]['n'] == 0
assert checks['user_credit_mismatches'][0]['n'] == 0
assert checks['owner'][0]['live'] == 0, 'owner_not_released'
assert not Path('/opt/unit3d-dualstack/soak-aliases.json').exists(), 'aliases_not_cleaned'
print(json.dumps({'name': args.name, 'status': 'final_accounting_verified',
                  'snapshot': state, 'checks': checks, 'aliases_removed': True}, indent=2, default=str))
