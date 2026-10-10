#!/usr/bin/env python3
"""Auditoria somente leitura: compara amostras aceitas com SQL após a drenagem."""
import collections
import gzip
import json
from pathlib import Path
import socket
import struct
import sys
import time

assert socket.gethostname() == 'unit3d-ds-clients'
sys.path.insert(0, '/opt/unit3d-dualstack')
from density_common import connect, snapshot

name = sys.argv[1]
assert name in ('soak-rust-six-hours-v2','soak-rust-six-hours-v3','soak-rehearsal-v3')
root = Path('/mnt/unit3d-archive/results/soak') / name
identities = json.loads((root / 'identities.json').read_text())
final = json.loads((root / 'final.json').read_text())
manifest = [json.loads(line) for line in (root / 'samples/manifest.jsonl').read_text().splitlines()]
record = struct.Struct('<IBBQddddI?')
counts, uploaded = collections.Counter(), collections.Counter()
last_received, count = 0., 0
started = time.monotonic()
for entry in manifest:
    path = root / 'samples' / entry['file']
    assert path.parent == root / 'samples'
    with gzip.open(path, 'rb') as stream:
        while block := stream.read(record.size * 20000):
            assert len(block) % record.size == 0
            for index, family, event, counter, scheduled, began, received, ended, size, ok in record.iter_unpack(block):
                assert ok and family in (4, 6)
                counts[index] += 1
                uploaded[index] = max(uploaded[index], counter)
                last_received = max(last_received, received)
                count += 1
assert count == final['accepted'] == final['sample_count']
expected = {(p['user_id'], p['torrent_id']): (counts[p['index']], uploaded[p['index']]) for p in identities}
by_user = collections.Counter()
for (user, _), (_, value) in expected.items():
    by_user[user] += value
state = snapshot()
with connect() as db, db.cursor() as cursor:
    cursor.execute('SELECT DATABASE() AS name')
    assert cursor.fetchone()['name'] == 'unit3d_dualstack_journal_test'
    cursor.execute('SELECT p.user_id,p.torrent_id,p.state_version,p.uploaded,h.actual_uploaded,h.uploaded AS credited,h.seedtime FROM peers p JOIN history h USING(user_id,torrent_id) WHERE p.user_id>=20000')
    peers = cursor.fetchall()
    cursor.execute('SELECT id,uploaded,seedbonus FROM users WHERE id>=20000')
    users = cursor.fetchall()
    cursor.execute('SELECT family,COUNT(*) AS n FROM peer_ips WHERE user_id>=20000 GROUP BY family')
    families = cursor.fetchall()
    cursor.execute('SELECT COUNT(*) AS n FROM (SELECT user_id,torrent_id,peer_id,COUNT(*) AS n FROM peer_ips WHERE user_id>=20000 GROUP BY user_id,torrent_id,peer_id HAVING n>2) s')
    over_limit = cursor.fetchone()['n']
    cursor.execute('SELECT COUNT(*) AS n,SUM(seeders) AS seeders,SUM(leechers) AS leechers,SUM(seeders_ipv4) AS seeders_ipv4,SUM(seeders_ipv6) AS seeders_ipv6,SUM(leechers_ipv4) AS leechers_ipv4,SUM(leechers_ipv6) AS leechers_ipv6,SUM(times_completed) AS times_completed FROM torrents WHERE id>=20000')
    torrents = cursor.fetchone()
    cursor.execute('SELECT backend,generation,COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1')
    owner = cursor.fetchone()
last_torrent = max(p['torrent_id'] for p in identities)
mismatches = collections.Counter()
version_extras = collections.Counter()
for peer in peers:
    accepted, value = expected[(peer['user_id'], peer['torrent_id'])]
    mismatches['peer_credit'] += any(int(peer[k]) != value for k in ('uploaded', 'actual_uploaded', 'credited'))
    extra = int(peer['state_version']) - accepted
    version_extras[extra] += 1
    expiry_control = peer['user_id'] == 20002 and peer['torrent_id'] == last_torrent and final['expiry_checked']
    # O gerador aceita 0 ou 1: a limpeza pode estar incluída em um announce.
    mismatches['peer_version'] += not (extra == 0 or (expiry_control and extra == 1))
    mismatches['seedtime_bound'] += not (0 <= int(peer['seedtime']) <= final['elapsed_seconds'] + 40)
for user in users:
    mismatches['user_credit'] += int(user['uploaded']) != by_user[user['id']]
    mismatches['bon'] += float(user['seedbonus']) != 0
expected_credit = sum(uploaded.values())
checks = {
    'sample_count': count, 'credit_from_accepted_samples': expected_credit,
    'mismatches': dict(mismatches), 'version_extras_per_peer': dict(version_extras),
    'families': families, 'endpoint_limit_violations': over_limit, 'torrents': torrents,
    'owner': owner, 'aliases_removed': not Path('/opt/unit3d-dualstack/soak-aliases.json').exists(),
    'last_accepted_response_seconds': last_received,
    'sample_iteration_seconds': time.monotonic() - started,
}
checks['all_accepted_credit_persisted'] = all(state[t]['uploaded'] == expected_credit for t in ('peers', 'history', 'users'))
checks['all_expected_peers_present'] = len(peers) == len(expected)
print(json.dumps({'name': name, 'snapshot': state, 'checks': checks}, indent=2, default=str))
