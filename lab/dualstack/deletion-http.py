#!/usr/bin/env python3
"""Confirma recusa apos exclusao e continuidade com origens IPv4/IPv6 reais."""
import argparse
import http.client
import json
from pathlib import Path
import time
import urllib.parse

import pymysql
from baseline import safe_response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--database-env', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--backend', choices=['php-standalone', 'rust'], required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    credentials = dict(line.split('=', 1) for line in args.database_env.read_text().splitlines())
    db = pymysql.connect(host='172.29.92.20', user=credentials['MYSQL_USER'],
                         password=credentials['MYSQL_PASSWORD'], database='unit3d_dualstack_journal_test',
                         autocommit=True, connect_timeout=3, read_timeout=3, write_timeout=3)
    report = {'status': 'running', 'backend': args.backend, 'steps': []}
    peer = b'-DS9200-DELETE000001'
    try:
        for torrent_index in (0, 1):
            for family in (4, 6):
                params = {'info_hash': bytes.fromhex(fixture['torrents'][torrent_index]['info_hash_hex']),
                          'peer_id': peer, 'port': 6881, 'uploaded': 0, 'downloaded': 0,
                          'left': 100, 'event': 'started', 'numwant': 0, 'compact': 1}
                host, source = (('172.29.92.10', '172.29.92.30') if family == 4 else
                                ('fd42:756e:6974:92::10', 'fd42:756e:6974:92::30'))
                connection = http.client.HTTPConnection(host, 8080, timeout=5, source_address=(source, 0))
                path = '/announce/'+fixture['users'][5]['passkey']+'?'+urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
                connection.request('GET', path, headers={'User-Agent': 'libtorrent/2.0.10'})
                response = connection.getresponse()
                decoded = safe_response(response.read())
                connection.close()
                assert response.status == 200, 'Status HTTP inesperado'
                assert ('failure reason' in decoded) == (torrent_index == 0), 'Recusa divergente'
                report['steps'].append({'torrent_id': fixture['torrents'][torrent_index]['id'],
                                        'family': family, 'rejected': 'failure reason' in decoded})
        deadline = time.monotonic()+10
        while True:
            with db.cursor() as cursor:
                cursor.execute('SELECT COUNT(*) FROM peer_ips WHERE torrent_id=12002 AND user_id=12006 AND peer_id=%s', (peer,))
                endpoints = cursor.fetchone()[0]
            if endpoints == 2:
                break
            assert time.monotonic() < deadline, 'Dois endpoints nao persistidos'
            time.sleep(0.1)
        with db.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM peers WHERE torrent_id=12001')
            assert cursor.fetchone()[0] == 0, 'Torrent excluido ressuscitou'
            cursor.execute('SELECT COUNT(*) FROM peers WHERE torrent_id=12002 AND user_id=12006 AND peer_id=%s', (peer,))
            assert cursor.fetchone()[0] == 1, 'Peer duplicado'
        report.update(status='passed', other_torrent_logical_peers=1, other_torrent_endpoints=2)
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise SystemExit(1) from None
    finally:
        db.close()
        args.output.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps({'status': report['status'], 'backend': args.backend, 'steps': len(report['steps'])}))


if __name__ == '__main__':
    main()
