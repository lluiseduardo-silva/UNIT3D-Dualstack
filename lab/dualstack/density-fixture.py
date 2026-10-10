#!/usr/bin/env python3
"""Fixture por layout, com usuarios reutilizados e dois endpoints por peer."""
import argparse
import datetime
import hashlib
import ipaddress
import json
import os
import socket

from density_common import BASE, connect, insert


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('plan')
    parser.add_argument('--skip-analyze', action='store_true', help='Preservar estatisticas naturais para ensaiar bootstrap')
    args = parser.parse_args()
    assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients'
    os.umask(0o077)
    plan = json.loads((BASE/args.plan).read_text())
    sizes = plan['sizes']
    assert sizes and all(50 <= n <= 100000 and n % 10 == 0 for n in sizes)
    assert sum(sizes) <= 200000 and len(sizes) <= 400
    secret = json.loads((BASE/'benchmark-key.json').read_text())['seed']
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)
    users = max(sizes)
    keys = [hashlib.sha256((secret+':density:'+str(i)).encode()).hexdigest()[:32] for i in range(users)]
    hashes = [hashlib.sha1(('density-torrent-'+str(i)).encode()).digest() for i in range(len(sizes))]
    manifest = dict(name=plan['name'], sizes=sizes, peers=sum(sizes), users=users,
                    torrents=len(sizes), dual_percent=100, created_at=now.isoformat(),
                    statistics_analyzed=not args.skip_analyze, lanes=[])
    with connect() as db, db.cursor() as c:
        c.execute('SELECT DATABASE() AS name')
        assert c.fetchone()['name'] == 'unit3d_dualstack_journal_test'
        c.execute('SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1 FOR UPDATE')
        assert not c.fetchone()['live']
        c.execute('SELECT COUNT(*) AS n FROM peers')
        assert c.fetchone()['n'] == 0, 'Exige fixture limpa e backend parado'
        c.execute('SELECT * FROM users WHERE id=12001')
        user_template = c.fetchone()
        c.execute('SELECT * FROM torrents WHERE id=12001')
        torrent_template = c.fetchone()
        for offset in range(0, users, 500):
            insert(c, 'users', [dict(user_template, id=20000+i, username='density'+str(i),
                email='density'+str(i)+'@example.invalid', passkey=keys[i], uploaded=0, downloaded=0,
                seedbonus=0, fl_tokens=0, rsskey=hashlib.sha256((secret+':density-rss:'+str(i)).encode()).hexdigest()[:32],
                api_token=None, remember_token=None, is_donor=0, is_lifetime=0, deleted_at=None,
                tracker_removal_state=0) for i in range(offset, min(offset+500, users))])
        insert(c, 'torrents', [dict(torrent_template, id=20000+t, name='Density '+str(t), info_hash=hashes[t],
            size=16777216, free=0, doubleup=0, seeders=n*4//5, leechers=n//5,
            seeders_ipv4=n*4//5, seeders_ipv6=n*4//5, leechers_ipv4=n//5, leechers_ipv6=n//5,
            times_completed=0) for t, n in enumerate(sizes)])
        for t, n in enumerate(sizes):
            for offset in range(0, n, 500):
                peers, history, endpoints = [], [], []
                for i in range(offset, min(offset+500, n)):
                    pid = ('-DS0001-'+f'{i:012d}').encode()
                    seeder = i % 10 < 8
                    ipv4, ipv6 = '172.29.92.'+str(100+i % 72), 'fd42:756e:6974:92::'+str(100+i % 72)
                    port = 10000+i//72
                    identity = dict(user_id=20000+i, torrent_id=20000+t, peer_id=pid)
                    peers.append(dict(identity, ip=ipaddress.ip_address(ipv4).packed, port=port,
                        agent='libtorrent/2.0.10', uploaded=0, downloaded=0, left=0 if seeder else 16777216,
                        seeder=seeder, created_at=now, updated_at=now, connectable=1, active=1, visible=1,
                        state_version=0, session_generation=1, completion_reported=seeder))
                    history.append(dict(user_id=20000+i, torrent_id=20000+t, agent='libtorrent/2.0.10',
                        client_uploaded=0, client_downloaded=0, seeder=seeder, active=1, immune=0,
                        created_at=now, updated_at=now, swarm_updated_at=now, completed_at=now if seeder else None))
                    for family, address in [(4, ipv4), (6, ipv6)]:
                        endpoints.append(dict(identity, family=family, ip=ipaddress.ip_address(address).packed,
                            port=port, connectable=1, last_announced_at=now, connectivity_checked_at=now,
                            revision=1, created_at=now, updated_at=now))
                    manifest['lanes'].append(dict(index=len(manifest['lanes']), user_slot=i, user_id=20000+i,
                        torrent_slot=t, torrent_id=20000+t, info_hash=hashes[t].hex(), peer_id=pid.hex(),
                        passkey=keys[i], ipv4=ipv4, ipv6=ipv6, port=port, seeder=seeder))
                insert(c, 'peers', peers)
                insert(c, 'history', history)
                insert(c, 'peer_ips', endpoints)
        db.commit()
        if not args.skip_analyze:
            c.execute('ANALYZE TABLE peers,peer_ips,history,torrents,users')
            assert all(row['Msg_text'] == 'OK' for row in c.fetchall())
    (BASE/'density-fixture.json').write_text(json.dumps(manifest))
    print(json.dumps({k: v for k, v in manifest.items() if k != 'lanes'}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps(dict(status='failed', error=type(error).__name__,
            code=error.args[0] if error.args and isinstance(error.args[0], int) else None)))
        raise SystemExit(1)
