#!/usr/bin/env python3
"""Ensaio local do proxy confiavel e reload, sem exportar chave administrativa."""
import http.client
import json
from pathlib import Path
import socket
import urllib.parse

if socket.gethostname() != 'unit3d-ds-tracker':
    raise SystemExit('Exige VM isolada de tracker.')
base = Path('/opt/unit3d-dualstack')
path = base/'rust-candidate.env'
original = path.read_bytes()
values = dict(line.split('=',1) for line in original.decode().splitlines() if '=' in line)
assert values['DUALSTACK_TRUSTED_PROXIES']=='127.0.0.1/32'
assert values['LISTENING_IP_ADDRESS']=='127.0.0.1'
report = {'status':'running','invalid_origins':[],'reload_statuses':[]}

def request(method, route, headers=None):
    connection = http.client.HTTPConnection('127.0.0.1',6969,timeout=3)
    connection.request(method,route,headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status,body

try:
    query = urllib.parse.urlencode({'info_hash':bytes(20),'peer_id':b'-DS9200-000000000009',
        'port':6881,'uploaded':0,'downloaded':0,'left':100,'compact':1})
    for address in ['0.0.0.0','::','224.0.0.1','ff02::1','169.254.1.1','fe80::1','invalido']:
        status,body = request('GET','/announce/'+'a'*32+'?'+query,{'User-Agent':'libtorrent/2.0.10','X-Real-IP':address})
        assert status==200 and b'Invalid announce origin.' in body,'Origem invalida nao recusada'
        report['invalid_origins'].append(address)
    # Alteracao na mesma inode, preservando o bind mount do arquivo.
    path.write_bytes(original.replace(b'DUALSTACK_ENABLED=true',b'DUALSTACK_ENABLED=false'))
    status,_ = request('POST','/announce/'+values['APIKEY']+'/config/reload')
    report['reload_statuses'].append(status)
    assert status==409,'Reload deve recusar mudanca de backend/politica'
    path.write_bytes(original)
    status,_ = request('POST','/announce/'+values['APIKEY']+'/config/reload')
    report['reload_statuses'].append(status)
    assert status==200,'Reload da mesma politica deve funcionar'
    report['status']='passed'
except Exception as error:
    report['status']='failed'
    report['error_type']=type(error).__name__
    report['error']=str(error) if isinstance(error,AssertionError) else 'Falha de infraestrutura; consultar diagnostico privado.'
finally:
    path.write_bytes(original)
    (base/'results/rust-http-boundaries.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
raise SystemExit(0 if report['status']=='passed' else 1)
