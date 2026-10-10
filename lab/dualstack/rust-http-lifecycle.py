#!/usr/bin/env python3
"""Verifica SIGTERM/restart real sem exportar URLs, passkeys ou credenciais."""
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
    parser.add_argument('--phase', choices=['before', 'stopped', 'resumed'], required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--database-env', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    values = dict(line.split('=', 1) for line in args.database_env.read_text().splitlines())
    db = pymysql.connect(host='172.29.92.20', user=values['MYSQL_USER'], password=values['MYSQL_PASSWORD'],
        database='unit3d_dualstack_journal_test', autocommit=True,
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=3, read_timeout=3, write_timeout=3)
    fixture = json.loads(args.fixture.read_text())
    report = {'phase': args.phase, 'status': 'running', 'responses': []}

    def check(condition, message):
        if not condition:
            raise AssertionError(message)

    def snapshot():
        queries = {
            'peers': 'SELECT user_id,torrent_id,HEX(peer_id) AS peer_id,state_version,uploaded,downloaded,active FROM peers ORDER BY user_id,torrent_id,peer_id',
            'endpoints': 'SELECT user_id,torrent_id,HEX(peer_id) AS peer_id,family,INET6_NTOA(ip) AS ip,port FROM peer_ips ORDER BY user_id,torrent_id,peer_id,family',
            'users': 'SELECT id,uploaded,downloaded FROM users ORDER BY id',
            'history': 'SELECT user_id,torrent_id,state_version,uploaded,downloaded,actual_uploaded,actual_downloaded,active FROM history ORDER BY user_id,torrent_id',
            'torrents': 'SELECT id,seeders,leechers,seeders_ipv4,seeders_ipv6,leechers_ipv4,leechers_ipv6,times_completed,balance FROM torrents ORDER BY id',
        }
        with db.cursor() as cursor:
            result = {}
            for key, query in queries.items():
                cursor.execute(query)
                result[key] = cursor.fetchall()
            return result

    def owner():
        with db.cursor() as cursor:
            cursor.execute('SELECT generation,backend,COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1')
            return cursor.fetchone()

    def announce(family, upload):
        params = {'info_hash': bytes.fromhex(fixture['torrents'][0]['info_hash_hex']), 'peer_id': b'-DS9200-000000000001',
            'port': 6881, 'uploaded': upload, 'downloaded': 100, 'left': 0, 'event': 'started', 'numwant': 0, 'compact': 1}
        connection = http.client.HTTPConnection('172.29.92.10' if family == 4 else 'fd42:756e:6974:92::10', 8080,
            timeout=3, source_address=('172.29.92.30' if family == 4 else 'fd42:756e:6974:92::31', 0))
        connection.request('GET', '/announce/'+fixture['users'][0]['passkey']+'?'+urllib.parse.urlencode(params, quote_via=urllib.parse.quote),
            headers={'User-Agent': 'libtorrent/2.0.10'})
        response = connection.getresponse()
        body = safe_response(response.read())
        connection.close()
        report['responses'].append({'family': family, 'upload': upload, 'response': body})
        check(response.status == 200 and 'failure reason' not in body, 'Announce apos restart recusado')

    try:
        current = snapshot()
        report['owner'] = owner()
        if args.phase == 'before':
            check(report['owner']['live'] == 1, 'Coordenador deveria possuir o swarm')
            args.checkpoint.write_text(json.dumps({'state': current, 'owner': report['owner']}, indent=2)+'\n')
        else:
            checkpoint = json.loads(args.checkpoint.read_text())
            check(current == checkpoint['state'], 'Persistencia mudou sem novos announces')
            if args.phase == 'stopped':
                check(report['owner']['live'] == 0, 'SIGTERM nao liberou a lease')
            else:
                check(report['owner']['live'] == 1 and report['owner']['generation'] > checkpoint['owner']['generation'], 'Restart nao assumiu geracao nova')
                announce(4, 2000)
                announce(6, 2000)
                time.sleep(0.3)
                check(snapshot()['users'] == current['users'], 'Repeticao apos restart reaplicou credito')
                announce(4, 2100)
                announce(6, 2100)
                time.sleep(0.3)
                after = snapshot()
                initial_user = next(row for row in current['users'] if row['id'] == 12001)
                final_user = next(row for row in after['users'] if row['id'] == 12001)
                check(final_user['uploaded'] == initial_user['uploaded']+100, 'Delta novo deve ser 100 nas duas familias')
                check(after['endpoints'] == current['endpoints'], 'Restart alterou os endpoints')
                check(after['torrents'][0]['times_completed'] == current['torrents'][0]['times_completed'], 'Restart duplicou conclusao')
                report['state_after'] = after
        report['status'] = 'passed'
        report['state_before'] = current
    except Exception as error:
        report['status'] = 'failed'
        report['error_type'] = type(error).__name__
        report['error'] = str(error) if isinstance(error, AssertionError) else 'Falha de infraestrutura; consultar diagnostico privado.'
    finally:
        args.output.write_text(json.dumps(report, indent=2, default=str)+'\n')
        db.close()
        print(json.dumps({'status': report['status'], 'phase': args.phase, 'error': report.get('error')}))
    raise SystemExit(0 if report['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()
