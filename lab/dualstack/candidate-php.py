#!/usr/bin/env python3
"""Contrato HTTP compartilhado, com origens reais e saida sem credenciais."""
import argparse
import datetime
import http.client
import json
from pathlib import Path
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import pymysql
from baseline import safe_response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--database-env', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--backend', choices=['php-standalone', 'rust'], default='php-standalone')
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    credentials = dict(line.split('=', 1) for line in args.database_env.read_text().splitlines())
    db = pymysql.connect(host='172.29.92.20', user=credentials['MYSQL_USER'],
                         password=credentials['MYSQL_PASSWORD'], database='unit3d_dualstack_journal_test',
                         autocommit=True, cursorclass=pymysql.cursors.DictCursor,
                         connect_timeout=3, read_timeout=3, write_timeout=3)
    report = {'status': 'running', 'backend': args.backend, 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'steps': []}
    peer = b'-DS9200-000000000001'

    def check(condition, message):
        if not condition:
            raise AssertionError(message)

    def state(user=12001, torrent=12001, peer_id=peer):
        with db.cursor() as cursor:
            cursor.execute('SELECT state_version,uploaded,downloaded,active,seeder FROM peers WHERE user_id=%s AND torrent_id=%s AND peer_id=%s', (user, torrent, peer_id))
            logical = cursor.fetchone()
            cursor.execute('SELECT family,INET6_NTOA(ip) AS ip,port,revision FROM peer_ips WHERE user_id=%s AND torrent_id=%s AND peer_id=%s ORDER BY family', (user, torrent, peer_id))
            endpoints = cursor.fetchall()
            cursor.execute('SELECT uploaded,downloaded FROM users WHERE id=%s', (user,))
            credit = cursor.fetchone()
        return {'peer': logical, 'endpoints': endpoints, 'credit': credit}

    def announce(label, family, event='started', upload=1000, downloaded=0, left=100, port=6881, user_index=0, torrent_index=0, peer_id=peer, numwant=25, headers=None, alternatives=None, source_override=None, concurrent=False, failure_expected=False):
        params = {'info_hash': bytes.fromhex(fixture['torrents'][torrent_index]['info_hash_hex']), 'peer_id': peer_id,
                  'port': port, 'uploaded': upload, 'downloaded': downloaded, 'left': left, 'event': event, 'numwant': numwant, 'compact': 1}
        params.update(alternatives or {})
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        ip = '172.29.92.10' if family == 4 else 'fd42:756e:6974:92::10'
        source = '172.29.92.30' if family == 4 else 'fd42:756e:6974:92::30'
        source = source_override or source
        connection = http.client.HTTPConnection(ip, 8080, timeout=5, source_address=(source, 0))
        connection.request('GET', '/announce/'+fixture['users'][user_index]['passkey']+'?'+query,
                           headers={'User-Agent': 'libtorrent/2.0.10', **(headers or {})})
        response = connection.getresponse()
        decoded = safe_response(response.read())
        connection.close()
        entry = {'label': label, 'user_id': fixture['users'][user_index]['id'], 'torrent_id': fixture['torrents'][torrent_index]['id'],
                 'peer_id_hex': peer_id.hex(), 'source_family': family, 'event': event, 'uploaded': str(upload), 'response': decoded}
        report['steps'].append(entry)
        check(response.status == 200, label+': status HTTP inesperado')
        if failure_expected:
            check('failure reason' in decoded, label+': esperava recusa explicita')
            return decoded
        check('failure reason' not in decoded, label+': announce recusado: '+str(decoded.get('failure reason')))
        if concurrent:
            return decoded
        time.sleep(0.3)
        entry['persisted'] = state(fixture['users'][user_index]['id'], fixture['torrents'][torrent_index]['id'], peer_id)
        return decoded

    try:
        announce('primeiro-ipv4', 4)
        announce('segunda-familia', 6)
        check(len(state()['endpoints']) == 2, 'Duas familias devem preservar dois endpoints')
        announce('primeiro-delta', 6, 'completed', 1100, 100, 0)
        announce('contador-atrasado', 4, 'completed', 1050, 100, 0)
        announce('segundo-delta', 4, 'completed', 1200, 100, 0)
        check(state()['credit']['uploaded'] == 200, 'Credito cumulativo deve ser 200')
        observer = b'-DS9200-000000000002'
        response = announce('numwant-um-peer-dois-caminhos', 4, user_index=1, peer_id=observer, upload=0, numwant=1)
        check(response['complete'] == 1 and response['peers_bytes'] == 6 and response['peers6_bytes'] == 18, 'Um peer selecionado deve retornar ambos endpoints')
        response = announce('numwant-zero', 6, user_index=1, peer_id=observer, upload=0, numwant=0)
        check(response['complete'] == 1 and response['peers_bytes'] == 0 and response['peers6_bytes'] == 0, 'numwant zero deve preservar estatisticas')
        announce('stop-ipv4-porta-zero', 4, 'stopped', 1200, 100, 0, port=0)
        check([row['family'] for row in state()['endpoints']] == [6] and state()['peer']['active'] == 1, 'Stop IPv4 nao pode remover IPv6')
        version = state()['peer']['state_version']
        announce('stop-repetido', 4, 'stopped', 9999, 100, 0, port=0)
        check(state()['peer']['state_version'] == version and state()['credit']['uploaded'] == 200, 'Stop repetido nao pode alterar credito ou versao')
        forged = b'-DS9200-000000000003'
        announce('origem-forjada-ignorada', 4, user_index=2, peer_id=forged, upload=0,
                 headers={'X-Forwarded-For': '2001:db8::dead', 'X-Real-IP': '2001:db8::dead'},
                 alternatives={'ip': '2001:db8::dead', 'ipv6': '2001:db8::dead', 'ipv4': '192.0.2.99'})
        check(state(12003, peer_id=forged)['endpoints'][0]['ip'] == '172.29.92.30', 'Somente a origem observada pode ser registrada')
        reverse = b'-DS9200-000000000004'
        announce('ordem-inversa-ipv6', 6, torrent_index=1, peer_id=reverse)
        announce('ordem-inversa-ipv4', 4, torrent_index=1, peer_id=reverse)
        check(len(state(torrent=12002, peer_id=reverse)['endpoints']) == 2, 'Ordem inversa deve preservar ambos caminhos')
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(announce, 'concorrente-'+str(i), 4 if i % 2 == 0 else 6, 'completed', 1300+i*100, 100, 0, concurrent=True) for i in range(8)]
            for future in futures:
                future.result()
        time.sleep(0.5)
        report['concurrent_final'] = state()
        check(state()['credit']['uploaded'] == 1000 and state()['peer']['uploaded'] == 2000, 'Concorrencia HTTP nao pode duplicar credito')
        announce('rotacao-ipv6-real', 6, 'completed', 2000, 100, 0, source_override='fd42:756e:6974:92::31')
        check(state()['endpoints'][1]['ip'] == 'fd42:756e:6974:92::31', 'IPv6 deve ser substituido pela origem nova')
        version = state()['peer']['state_version']
        announce('stop-ipv6-antigo', 6, 'stopped', 9000, 100, 0, port=0)
        check(state()['peer']['state_version'] == version and state()['credit']['uploaded'] == 1000, 'Stop do endereco antigo deve ser ignorado')
        exact = b'-DS9200-000000000005'
        announce('uint64-inicial', 4, upload=18446744073709551614, user_index=3, peer_id=exact)
        announce('uint64-segunda-familia', 6, upload=18446744073709551614, user_index=3, peer_id=exact)
        announce('uint64-incremento', 6, 'completed', 18446744073709551615, user_index=3, peer_id=exact)
        check(state(12004, peer_id=exact)['peer']['uploaded'] == 18446744073709551615 and state(12004, peer_id=exact)['credit']['uploaded'] == 1, 'HTTP deve preservar uint64 exato')
        for i in [6, 7]:
            extra = ('-DS9200-'+str(i).zfill(12)).encode()
            for family in [4, 6]:
                announce('limite-peer-'+str(i)+'-ipv'+str(family), family, peer_id=extra)
        announce('quarto-peer-recusado', 4, peer_id=b'-DS9200-000000000008', failure_expected=True)
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error_type'] = type(error).__name__
        # Mensagens de drivers/conexoes podem incluir SQL ou URL; nunca exporta-las.
        report['error'] = str(error) if isinstance(error, AssertionError) else 'Falha de infraestrutura; consultar diagnostico local sem credenciais.'
    finally:
        report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        args.output.write_text(json.dumps(report, indent=2, default=str)+'\n')
        print(json.dumps({'status': report['status'], 'steps': len(report['steps']), 'error': report.get('error')}))
        db.close()
    raise SystemExit(0 if report['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()
