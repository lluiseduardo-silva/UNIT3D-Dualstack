#!/usr/bin/env python3
"""Valida fatores atualizados pelo UNIT3D em announces reais das duas familias."""
import argparse
import http.client
import json
from pathlib import Path
import socket
import time
import urllib.parse

import pymysql
from baseline import safe_response

assert socket.gethostname() == 'unit3d-ds-clients'
parser = argparse.ArgumentParser()
parser.add_argument('--profile',choices=['free-double','normal'],required=True)
parser.add_argument('--output',type=Path,required=True)
args = parser.parse_args()
base = Path('/opt/unit3d-dualstack')
fixture = json.loads((base/'fixture.json').read_text())
credentials = dict(line.split('=',1) for line in (base/'database.env').read_text().splitlines())
db = pymysql.connect(host='172.29.92.20',user=credentials['MYSQL_USER'],password=credentials['MYSQL_PASSWORD'],
    database='unit3d_dualstack_journal_test',autocommit=True,cursorclass=pymysql.cursors.DictCursor,
    connect_timeout=3,read_timeout=3,write_timeout=3)
report = {'status':'running','profile':args.profile,'responses':[]}

def credit():
    with db.cursor() as cursor:
        cursor.execute('SELECT uploaded,downloaded FROM users WHERE id=12001')
        return cursor.fetchone()

try:
    report['before'] = credit()
    upload,download = (1100,100) if args.profile=='free-double' else (1200,200)
    for family in [4,6]:
        params = {'info_hash':bytes.fromhex(fixture['torrents'][1]['info_hash_hex']),'peer_id':b'-DS9200-000000000004',
            'port':6881,'uploaded':upload,'downloaded':download,'left':100,'compact':1,'numwant':0}
        connection = http.client.HTTPConnection('172.29.92.10' if family==4 else 'fd42:756e:6974:92::10',8080,
            timeout=5,source_address=('172.29.92.30' if family==4 else 'fd42:756e:6974:92::30',0))
        connection.request('GET','/announce/'+fixture['users'][0]['passkey']+'?'+urllib.parse.urlencode(params,quote_via=urllib.parse.quote),headers={'User-Agent':'libtorrent/2.0.10'})
        response = connection.getresponse()
        body = safe_response(response.read())
        connection.close()
        assert response.status==200 and 'failure reason' not in body,'Announce recusado'
        report['responses'].append({'family':family,'response':body})
    time.sleep(0.3)
    report['after'] = credit()
    expected_upload,expected_download = (200,0) if args.profile=='free-double' else (100,100)
    assert report['after']['uploaded']-report['before']['uploaded']==expected_upload,'Double upload aplicado incorretamente'
    assert report['after']['downloaded']-report['before']['downloaded']==expected_download,'Freeleech aplicado incorretamente'
    report['status']='passed'
except Exception as error:
    report['status']='failed'
    report['error_type']=type(error).__name__
    report['error']=str(error) if isinstance(error,AssertionError) else 'Falha de infraestrutura; consultar diagnostico privado.'
finally:
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    db.close()
    print(json.dumps({'status':report['status'],'profile':args.profile,'error':report.get('error')}))
raise SystemExit(0 if report['status']=='passed' else 1)
