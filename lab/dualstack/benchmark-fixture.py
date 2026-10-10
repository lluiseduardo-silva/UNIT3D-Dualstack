#!/usr/bin/env python3
"""Populacao deterministica no banco descartavel, somente com tracker parado."""
import argparse
import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket

import pymysql

BASE = Path('/opt/unit3d-dualstack')


def connect():
    values = dict(line.split('=', 1) for line in (BASE/'database.env').read_text().splitlines())
    return pymysql.connect(host='172.29.92.20', user=values['MYSQL_USER'], password=values['MYSQL_PASSWORD'],
                          database='unit3d_dualstack_journal_test', autocommit=False,
                          connect_timeout=5, read_timeout=120, write_timeout=120,
                          cursorclass=pymysql.cursors.DictCursor)


def insert(cursor, table, rows):
    columns = list(rows[0])
    sql = 'INSERT INTO `'+table+'` ('+','.join('`'+c+'`' for c in columns)+') VALUES ('+','.join(['%s']*len(columns))+')'
    cursor.executemany(sql, [[row[c] for c in columns] for row in rows])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--peers', type=int, choices=[1000, 54000, 100000], default=1000)
    parser.add_argument('--dual-percent', type=int, choices=[0, 50, 100], default=0)
    parser.add_argument('--distribution', choices=['distributed', 'popular'], default='distributed')
    args = parser.parse_args()
    assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients'
    os.umask(0o077)
    # Segredos locais preservados entre baseline e candidato; nunca exportados.
    keyfile = BASE/'benchmark-key.json'
    if not keyfile.exists():
        keyfile.write_text(json.dumps({'seed': secrets.token_hex(32)}))
    key = json.loads(keyfile.read_text())['seed']
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)
    torrent_count = args.peers//10 if args.distribution == 'distributed' else 1
    manifest = dict(vars(args), torrents=torrent_count, seeders=args.peers*4//5,
                    leechers=args.peers//5, lanes=[], created_at=now.isoformat())
    with connect() as db, db.cursor() as cursor:
        cursor.execute('SELECT DATABASE() AS name')
        assert cursor.fetchone()['name'] == 'unit3d_dualstack_journal_test'
        cursor.execute('SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1 FOR UPDATE')
        assert not cursor.fetchone()['live'], 'Encerre o proprietario'
        cursor.execute('SELECT COUNT(*) AS n FROM peers')
        assert cursor.fetchone()['n'] == 0, 'Restaure a fixture antes de preparar a populacao'
        cursor.execute('SELECT * FROM users WHERE id=12001')
        user_template = cursor.fetchone()
        cursor.execute('SELECT * FROM torrents WHERE id=12001')
        torrent_template = cursor.fetchone()
        hashes = [hashlib.sha1(('unit3d-benchmark-'+str(i)).encode()).digest() for i in range(torrent_count)]
        for offset in range(0, torrent_count, 500):
            rows = []
            for i in range(offset, min(offset+500, torrent_count)):
                count = 10 if torrent_count > 1 else args.peers
                rows.append(dict(torrent_template, id=20000+i, name='Benchmark '+str(i), info_hash=hashes[i],
                                 size=16777216, free=0, doubleup=0, seeders=count*4//5, leechers=count//5,
                                 seeders_ipv4=count*4//5, leechers_ipv4=count//5,
                                 seeders_ipv6=0, leechers_ipv6=0, times_completed=0))
            insert(cursor, 'torrents', rows)
        for offset in range(0, args.peers, 500):
            users, peers, histories, endpoints = [], [], [], []
            for i in range(offset, min(offset+500, args.peers)):
                user_id = 20000+i
                torrent_index = i//10 if torrent_count > 1 else 0
                torrent_id = 20000+torrent_index
                peer_id = ('-qB4500-'+f'{i:012d}').encode()
                passkey = hashlib.sha256((key+':'+str(i)).encode()).hexdigest()[:32]
                seeder = i % 10 < 8
                dual = i % 100 < args.dual_percent
                number = 100+i % 72
                ipv4, ipv6 = '172.29.92.'+str(number), 'fd42:756e:6974:92::'+str(number)
                port = 10000+i//72
                users.append(dict(user_template, id=user_id, username='bench'+str(i), email='bench'+str(i)+'@example.invalid',
                                  passkey=passkey, uploaded=0, downloaded=0, seedbonus=0, fl_tokens=0,
                                  rsskey=hashlib.sha256((key+':rss:'+str(i)).encode()).hexdigest()[:32],
                                  api_token=None, remember_token=None, is_donor=0, is_lifetime=0,
                                  deleted_at=None, tracker_removal_state=0))
                identity = dict(user_id=user_id, torrent_id=torrent_id, peer_id=peer_id)
                peers.append(dict(identity, ip=ipaddress.ip_address(ipv4).packed, port=port, agent='libtorrent/2.0.10',
                                  uploaded=0, downloaded=0, left=0 if seeder else 16777216, seeder=seeder,
                                  created_at=now, updated_at=now, connectable=1, active=1, visible=1,
                                  state_version=0, session_generation=1, completion_reported=seeder))
                histories.append(dict(user_id=user_id, torrent_id=torrent_id, agent='libtorrent/2.0.10',
                                      client_uploaded=0, client_downloaded=0, seeder=seeder, active=1, immune=0,
                                      created_at=now, updated_at=now, swarm_updated_at=now,
                                      completed_at=now if seeder else None))
                for family, ip in [(4, ipv4)]+([(6, ipv6)] if dual else []):
                    endpoints.append(dict(identity, family=family, ip=ipaddress.ip_address(ip).packed, port=port,
                                          connectable=1, last_announced_at=now, connectivity_checked_at=now,
                                          revision=1, created_at=now, updated_at=now))
                manifest['lanes'].append(dict(index=i, user_id=user_id, torrent_id=torrent_id,
                    info_hash=hashes[torrent_index].hex(), peer_id=peer_id.hex(), passkey=passkey,
                    ipv4=ipv4, ipv6=ipv6, port=port, seeder=seeder, dual=dual))
            insert(cursor, 'users', users)
            insert(cursor, 'peers', peers)
            insert(cursor, 'history', histories)
            insert(cursor, 'peer_ips', endpoints)
        cursor.execute('UPDATE torrents t SET seeders_ipv6=(SELECT COUNT(*) FROM peers p JOIN peer_ips e USING(user_id,torrent_id,peer_id) WHERE p.torrent_id=t.id AND p.seeder=1 AND e.family=6),leechers_ipv6=(SELECT COUNT(*) FROM peers p JOIN peer_ips e USING(user_id,torrent_id,peer_id) WHERE p.torrent_id=t.id AND p.seeder=0 AND e.family=6) WHERE t.id>=20000')
        db.commit()
    (BASE/'benchmark-fixture.json').write_text(json.dumps(manifest))
    print(json.dumps({k: v for k, v in manifest.items() if k != 'lanes'}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Mensagens SQL podem incluir credenciais da fixture: apenas tipo/codigo.
        print(json.dumps({'status': 'failed', 'error': type(error).__name__,
                          'code': error.args[0] if error.args and isinstance(error.args[0], int) else None}))
        raise SystemExit(1)
