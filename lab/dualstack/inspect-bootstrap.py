#!/usr/bin/env python3
"""Fechamento agregado do ensaio, sem exportar identidades ou credenciais."""
import argparse
import json
import os
import socket

from density_common import connect

assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients'
parser = argparse.ArgumentParser()
parser.add_argument('--quiescent-only', action='store_true', help='Conferir encerramento depois das suites que creditam trafego')
args = parser.parse_args()
queries = {
    'runtime': 'SELECT DATABASE() AS db, VERSION() AS version, @@transaction_isolation AS isolation_level, @@innodb_lock_wait_timeout AS lock_wait_seconds, UTC_TIMESTAMP(3) AS at',
    'owner': 'SELECT generation,backend,COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1',
    'peers': 'SELECT COUNT(*) AS total,SUM(state_version<>0 OR uploaded<>0 OR downloaded<>0) AS changed FROM peers',
    'endpoints': 'SELECT family,COUNT(*) AS total FROM peer_ips GROUP BY family ORDER BY family',
    'endpoint_limit': 'SELECT MAX(n) AS maximum FROM (SELECT COUNT(*) n FROM peer_ips GROUP BY user_id,torrent_id,peer_id) e',
    'history': 'SELECT COUNT(*) AS total,SUM(uploaded<>0 OR downloaded<>0 OR actual_uploaded<>0 OR actual_downloaded<>0) AS changed FROM history',
    'users': 'SELECT COUNT(*) AS total,SUM(uploaded<>0 OR downloaded<>0) AS changed FROM users WHERE id>=20000',
    'counts': 'SELECT SUM(seeders) AS seeders,SUM(leechers) AS leechers,SUM(seeders_ipv4) AS seeders_ipv4,SUM(seeders_ipv6) AS seeders_ipv6,SUM(leechers_ipv4) AS leechers_ipv4,SUM(leechers_ipv6) AS leechers_ipv6 FROM torrents',
    'active_queries': "SELECT ID,COMMAND,TIME,STATE FROM information_schema.PROCESSLIST WHERE DB=DATABASE() AND ID<>CONNECTION_ID() AND COMMAND<>'Sleep'",
}
with connect() as db, db.cursor() as cursor:
    report = {}
    for name, query in queries.items():
        cursor.execute(query)
        report[name] = cursor.fetchall()
    db.rollback()
assert report['runtime'][0]['db'] == 'unit3d_dualstack_journal_test'
assert report['owner'][0]['live'] == 0 and not report['active_queries']
if not args.quiescent_only:
    assert all(report[name][0]['changed'] == 0 for name in ['peers', 'history', 'users'])
    assert report['endpoint_limit'][0]['maximum'] == 2
print(json.dumps(report, indent=2, default=str))
