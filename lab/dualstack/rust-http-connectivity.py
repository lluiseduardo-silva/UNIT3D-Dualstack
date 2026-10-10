#!/usr/bin/env python3
"""Probes TCP reais por familia; este ensaio nao simula BitTorrent."""
import argparse
import http.client
import json
from pathlib import Path
import socket
import threading
import time
import urllib.parse

import pymysql
from baseline import safe_response


def main():
    if socket.gethostname() != 'unit3d-ds-clients':
        raise SystemExit('Exige a VM isolada de clientes.')
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--database-env', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    values = dict(line.split('=', 1) for line in args.database_env.read_text().splitlines())
    fixture = json.loads(args.fixture.read_text())
    db = pymysql.connect(host='172.29.92.20', user=values['MYSQL_USER'], password=values['MYSQL_PASSWORD'],
        database='unit3d_dualstack_journal_test', autocommit=True,
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=3, read_timeout=3, write_timeout=3)
    report = {'status': 'running', 'steps': [], 'probes_accepted': {'4': 0, '6': 0}}
    listeners = []

    def check(condition, message):
        if not condition:
            raise AssertionError(message)

    def listen(family, port):
        server = socket.socket(socket.AF_INET if family == 4 else socket.AF_INET6)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('172.29.92.30' if family == 4 else 'fd42:756e:6974:92::30', port))
        server.listen(128)
        listeners.append(server)
        def accept():
            while True:
                try:
                    connection, _ = server.accept()
                    report['probes_accepted'][str(family)] += 1
                    connection.close()
                except OSError:
                    return
        threading.Thread(target=accept, daemon=True).start()

    def state():
        with db.cursor() as cursor:
            cursor.execute('SELECT family,INET6_NTOA(ip) AS ip,port,connectable,revision FROM peer_ips WHERE user_id=12001 ORDER BY family')
            endpoints = cursor.fetchall()
            cursor.execute('SELECT seeders,seeders_ipv4,seeders_ipv6,times_completed FROM torrents WHERE id=12001')
            counts = cursor.fetchone()
            cursor.execute('SELECT uploaded FROM users WHERE id=12001')
            return {'endpoints': endpoints, 'counts': counts, 'uploaded': cursor.fetchone()['uploaded']}

    def announce(label, family=4, observer=False, port=6881, upload=1000):
        params = {'info_hash': bytes.fromhex(fixture['torrents'][0]['info_hash_hex']),
            'peer_id': b'-DS9200-000000000002' if observer else b'-DS9200-000000000001',
            'port': port, 'uploaded': 0 if observer else upload, 'downloaded': 0,
            'left': 100 if observer else 0, 'event': 'started', 'numwant': 1,
            'compact': 1, 'ip': '192.0.2.99', 'ipv6': '2001:db8::bad'}
        connection = http.client.HTTPConnection('172.29.92.10' if family == 4 else 'fd42:756e:6974:92::10',8080,
            timeout=5,source_address=('172.29.92.30' if family == 4 else 'fd42:756e:6974:92::30',0))
        connection.request('GET','/announce/'+fixture['users'][1 if observer else 0]['passkey']+'?'+urllib.parse.urlencode(params,quote_via=urllib.parse.quote),
            headers={'User-Agent':'libtorrent/2.0.10','X-Real-IP':'2001:db8::bad','X-Forwarded-For':'192.0.2.99'})
        response = connection.getresponse()
        body = safe_response(response.read())
        connection.close()
        check(response.status == 200 and 'failure reason' not in body,label+': announce recusado')
        time.sleep(0.3)
        report['steps'].append({'label':label,'family':family,'response':body,'persisted':state()})
        return body

    try:
        listen(4,6881)
        announce('ipv4-conectavel')
        announce('ipv6-fechado',family=6)
        current = state()
        check([(e['family'],e['connectable']) for e in current['endpoints']] == [(4,1),(6,0)],'Conectividade deve ser independente')
        check([e['ip'] for e in current['endpoints']] == ['172.29.92.30','fd42:756e:6974:92::30'],'Proxy deve sobrescrever headers forjados e usar origem real')
        response = announce('lista-preserva-ipv4',observer=True)
        check(response['complete']==1 and response['peers_bytes']==6 and response['peers6_bytes']==0,'IPv6 fechado nao pode remover IPv4 valido')
        listen(6,6882)
        announce('troca-porta-ipv6-conectavel',family=6,port=6882,upload=1100)
        response = announce('lista-ambos-caminhos',observer=True)
        check(response['complete']==1 and response['peers_bytes']==6 and response['peers6_bytes']==18,'Dois endpoints conectaveis devem ser publicados')
        announce('troca-porta-ipv4-fechada',port=6883,upload=1100)
        current = state()
        check([(e['family'],e['connectable']) for e in current['endpoints']] == [(4,0),(6,1)],'Falha IPv4 nao pode alterar IPv6')
        response = announce('lista-preserva-ipv6',observer=True)
        check(response['complete']==1 and response['peers_bytes']==0 and response['peers6_bytes']==18,'IPv4 fechado nao pode remover IPv6 valido')
        announce('recupera-ipv4',upload=1100)
        response = announce('lista-restaurada',observer=True)
        check(response['peers_bytes']==6 and response['peers6_bytes']==18,'IPv4 recuperado deve voltar sem remover IPv6')
        check(state()['uploaded']==100,'Probes nao podem duplicar credito')
        check(report['probes_accepted']['4']>0 and report['probes_accepted']['6']>0,'Exige conexoes TCP reais nas duas familias')
        report['status']='passed'
    except Exception as error:
        report['status']='failed'
        report['error_type']=type(error).__name__
        report['error']=str(error) if isinstance(error,AssertionError) else 'Falha de infraestrutura; consultar diagnostico privado.'
    finally:
        for server in listeners:
            server.close()
        db.close()
        args.output.write_text(json.dumps(report,indent=2,default=str)+'\n')
        print(json.dumps({'status':report['status'],'steps':len(report['steps']),'probes_accepted':report['probes_accepted'],'error':report.get('error')}))
    raise SystemExit(0 if report['status']=='passed' else 1)


if __name__ == '__main__':
    main()
