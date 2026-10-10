#!/usr/bin/env python3
"""Conferencia somente leitura depois de drenar e encerrar a ultima serie."""
import json
import os
import socket

from density_common import BASE, connect, snapshot

assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients'
fixture = json.loads((BASE/'density-fixture.json').read_text())
plan = json.loads((BASE/(fixture['name']+'.json')).read_text())
last = json.loads((BASE/'density-results'/fixture['name']/(plan['phases'][-1]['name']+'.json')).read_text())
assert last['status'] == 'passed'
state = snapshot()
with connect() as db, db.cursor() as c:
    c.execute('SELECT DATABASE() AS name')
    assert c.fetchone()['name'] == 'unit3d_dualstack_journal_test'
    c.execute('SELECT backend,generation,COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1')
    state['ownership'] = c.fetchone()
    c.execute('''SELECT COUNT(*) AS n FROM peers p JOIN history h USING(user_id,torrent_id)
        WHERE p.user_id>=20000 AND (p.uploaded<>h.actual_uploaded OR p.uploaded<>h.uploaded)''')
    peer_mismatches = int(c.fetchone()['n'])
    c.execute('''SELECT COUNT(*) AS n FROM users u JOIN
        (SELECT user_id,SUM(uploaded) AS uploaded FROM peers WHERE user_id>=20000 GROUP BY user_id) p
        ON p.user_id=u.id WHERE u.uploaded<>p.uploaded''')
    user_mismatches = int(c.fetchone()['n'])
    c.execute('''SELECT COUNT(*) AS n FROM peer_ips WHERE user_id>=20000 AND
        ((family=4 AND OCTET_LENGTH(ip)<>4) OR (family=6 AND OCTET_LENGTH(ip)<>16))''')
    endpoint_mismatches = int(c.fetchone()['n'])
    c.execute('''SELECT id,seeders,seeders_ipv4,seeders_ipv6,leechers,leechers_ipv4,leechers_ipv6
        FROM torrents WHERE id>=20000 ORDER BY id''')
    counts = c.fetchall()
    assert len(counts) == len(fixture['sizes'])
    torrent_mismatches = sum(any(int(row[k]) != fixture['sizes'][t]*(4 if k.startswith('seeders') else 1)//5
        for k in ['seeders','seeders_ipv4','seeders_ipv6','leechers','leechers_ipv4','leechers_ipv6'])
        for t, row in enumerate(counts))
    # Somente contagem: nao exportar texto SQL de outros processos.
    c.execute('''SELECT COUNT(*) AS n FROM information_schema.PROCESSLIST
        WHERE ID<>CONNECTION_ID() AND DB='unit3d_dualstack_journal_test' AND COMMAND<>'Sleep' ''')
    active_queries = int(c.fetchone()['n'])
state.update(series=fixture['name'], mismatches=dict(peers=peer_mismatches, users=user_mismatches,
    endpoints=endpoint_mismatches, torrents=torrent_mismatches), active_test_queries=active_queries)
assert not any(state['mismatches'].values()) and not state['ownership']['live'] and active_queries == 0
assert state['peers']['n'] == fixture['peers'] and state['peer_ips']['n'] == 2*fixture['peers']
assert state['peers']['versions'] == last['cumulative_accepted']
assert all(state[t]['uploaded'] == last['expected_upload'] for t in ['peers','history','users'])
assert state['failed_jobs']['n'] == 0 and state['locks'] == last['after']['locks']
print(json.dumps(state))
