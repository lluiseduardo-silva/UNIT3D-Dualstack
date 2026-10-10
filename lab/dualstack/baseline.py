#!/usr/bin/env python3
"""Baseline deterministico por sockets reais; resultados nunca incluem passkeys."""
import argparse
import datetime
import http.client
import ipaddress
import json
from pathlib import Path
import time
import urllib.parse

import pymysql


def bdecode(data):
    def parse(pos):
        marker = data[pos:pos + 1]
        if marker == b'i':
            end = data.index(b'e', pos)
            return int(data[pos + 1:end]), end + 1
        if marker in (b'd', b'l'):
            value = {} if marker == b'd' else []
            pos += 1
            while data[pos:pos + 1] != b'e':
                item, pos = parse(pos)
                if marker == b'd':
                    entry, pos = parse(pos)
                    value[item] = entry
                else:
                    value.append(item)
            return value, pos + 1
        end = data.index(b':', pos)
        size = int(data[pos:end])
        return data[end + 1:end + 1 + size], end + 1 + size
    result, end = parse(0)
    if end != len(data):
        raise ValueError('Resposta bencode contem bytes restantes')
    return result


def safe_response(body):
    result = {}
    for key, value in bdecode(body).items():
        name = key.decode('ascii')
        if key in (b'peers', b'peers6'):
            size = 6 if key == b'peers' else 18
            if len(value) % size:
                raise ValueError('Lista compacta de tamanho invalido')
            result[name] = [
                {'ip': str(ipaddress.ip_address(value[i:i + size - 2])),
                 'port': int.from_bytes(value[i + size - 2:i + size], 'big')}
                for i in range(0, len(value), size)
            ]
            result[name + '_bytes'] = len(value)
        else:
            result[name] = value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value
    return result


def snapshot(connection, user_id, torrent_id):
    statements = {
        'peer': ('SELECT user_id,torrent_id,HEX(peer_id) AS peer_id_hex,INET6_NTOA(ip) AS ip,port,uploaded,downloaded,`left`,seeder,active,visible,connectable,updated_at FROM peers WHERE user_id=%s AND torrent_id=%s', (user_id, torrent_id)),
        'history': ('SELECT user_id,torrent_id,uploaded,downloaded,actual_uploaded,actual_downloaded,client_uploaded,client_downloaded,active,seedtime,seeder FROM history WHERE user_id=%s AND torrent_id=%s', (user_id, torrent_id)),
        'user': ('SELECT id,uploaded,downloaded FROM users WHERE id=%s', (user_id,)),
        'torrent': ('SELECT id,seeders,leechers,times_completed FROM torrents WHERE id=%s', (torrent_id,)),
        'failed_jobs': ('SELECT COUNT(*) AS count FROM failed_jobs', ()),
    }
    result = {}
    with connection.cursor() as cursor:
        for key, (sql, params) in statements.items():
            cursor.execute(sql, params)
            result[key] = cursor.fetchall()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['php', 'rust'], required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--database-env', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    credentials = dict(line.split('=', 1) for line in args.database_env.read_text().splitlines())
    connection = pymysql.connect(host='172.29.92.20', user=credentials['MYSQL_USER'],
                                 password=credentials['MYSQL_PASSWORD'], database=credentials['MYSQL_DATABASE'],
                                 autocommit=True, cursorclass=pymysql.cursors.DictCursor,
                                 connect_timeout=10, read_timeout=10, write_timeout=10)
    output = {'mode': args.mode, 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'steps': []}
    with connection.cursor() as cursor:
        cursor.execute('SELECT VERSION() AS version, @@transaction_isolation AS isolation_level, @@innodb_lock_wait_timeout AS lock_wait_timeout')
        output['database'] = cursor.fetchone()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def announce(label, family, user_index, torrent_index, event, upload, download, left, port=6881):
        user = fixture['users'][user_index]
        torrent = fixture['torrents'][torrent_index]
        peer_id = f'-qB4500-{user["id"]:012d}'.encode()
        source = '172.29.92.30' if family == 4 else 'fd42:756e:6974:92::30'
        target = '172.29.92.10' if family == 4 else 'fd42:756e:6974:92::10'
        params = {'info_hash': bytes.fromhex(torrent['info_hash_hex']), 'peer_id': peer_id,
                  'port': port, 'uploaded': upload, 'downloaded': download, 'left': left,
                  'compact': 1, 'numwant': 15, 'event': event, 'key': 'a1b2c3d4'}
        client = http.client.HTTPConnection(target, 8080 if args.mode == 'php' else 8081,
                                          timeout=15, source_address=(source, 0))
        started = time.monotonic_ns()
        client.request('GET', '/announce/' + user['passkey'] + '?' + urllib.parse.urlencode(params),
                     headers={'User-Agent': 'qBittorrent/4.5.0'})
        response = client.getresponse()
        body = response.read()
        latency_ms = (time.monotonic_ns() - started) / 1_000_000
        client.close()
        step = {'label': label, 'family': family, 'source': source, 'user_id': user['id'],
                'torrent_id': torrent['id'], 'peer_id_hex': peer_id.hex(), 'event': event,
                'uploaded': upload, 'downloaded': download, 'left': left, 'port': port,
                'http_status': response.status, 'latency_ms': latency_ms, 'body_bytes': len(body)}
        if response.status != 200 or not body.startswith(b'd'):
            step['error'] = 'Resposta HTTP nao contem bencode; consulte logs locais sem publicar credenciais.'
            output['steps'].append(step)
            args.output.write_text(json.dumps(output, indent=2, default=str) + '\n')
            raise RuntimeError(step['error'])
        step['response'] = safe_response(body)
        time.sleep(7)  # Maior que os flushes originais de PHP (5s) e Rust (3s).
        step['database_after_flush'] = snapshot(connection, user['id'], torrent['id'])
        output['steps'].append(step)
        args.output.write_text(json.dumps(output, indent=2, default=str) + '\n')
        print(json.dumps({'label': label, 'response': step['response'], 'peer': step['database_after_flush']['peer'],
                          'user': step['database_after_flush']['user']}, default=str), flush=True)
        if step['database_after_flush']['failed_jobs'][0]['count']:
            raise RuntimeError('O worker registrou jobs falhos; baseline interrompido.')

    for index, first in enumerate((4, 6)):
        second = 6 if first == 4 else 4
        main_user = index * 3
        prefix = f'ipv{first}-ipv{second}'
        announce(prefix + '/initial', first, main_user, index, 'started', 1000, 0, 1000)
        announce(prefix + '/observer-before', first, main_user + 1, index, 'started', 0, 0, 2048)
        announce(prefix + '/second-started', second, main_user, index, 'started', 1000, 0, 1000)
        announce(prefix + '/completed', second, main_user, index, 'completed', 1100, 1000, 0)
        announce(prefix + '/observer-after', first, main_user + 2, index, 'started', 0, 0, 2048)
        announce(prefix + '/stop-original', first, main_user, index, 'stopped', 1200, 1000, 0, port=0)
    connection.close()


if __name__ == '__main__':
    main()
