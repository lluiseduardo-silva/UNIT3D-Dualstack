#!/usr/bin/env python3
"""Converter somente a fixture recém-criada para um endpoint IPv4 por peer."""
import json
import os
import socket
import sys
sys.path.insert(0,'/opt/unit3d-dualstack')
from density_common import BASE,connect

assert os.geteuid()==0 and socket.gethostname()=='unit3d-ds-clients'
os.umask(0o077)
name=sys.argv[1]
plan=json.loads((BASE/'soak'/(name+'.json')).read_text())
assert plan['comparison_variant'] in ('original','candidate')
path=BASE/'density-fixture.json';fixture=json.loads(path.read_text())
assert fixture['name']==name and fixture['dual_percent']==100
with connect() as db,db.cursor() as c:
    c.execute('SELECT SUM(uploaded) AS u,SUM(state_version) AS v FROM peers');row=c.fetchone()
    assert int(row['u'])==int(row['v'])==0
    c.execute('SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1')
    assert not c.fetchone()['live']
    c.execute('DELETE FROM peer_ips WHERE family=6 AND user_id>=20000')
    assert c.rowcount==fixture['peers']
    c.execute('UPDATE torrents SET seeders_ipv6=0,leechers_ipv6=0 WHERE id>=20000')
    db.commit()
    c.execute('ANALYZE TABLE peers,peer_ips,history,torrents,users')
    assert all(r['Msg_text']=='OK' for r in c.fetchall())
fixture['dual_percent']=0;path.write_text(json.dumps(fixture))
private=BASE/'comparison-fixtures'/name
private.mkdir(parents=True,exist_ok=False,mode=0o700)
(private/'density-fixture.json').write_text(json.dumps(fixture))
print(json.dumps(dict(name=name,peers=fixture['peers'],torrents=fixture['torrents'],users=fixture['users'],dual_percent=0)))
