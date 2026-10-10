#!/usr/bin/env python3
"""Diagnostico SQL somente de leitura no banco descartavel do benchmark."""
import importlib.util
import json
import time

spec = importlib.util.spec_from_file_location('fixture', '/opt/unit3d-dualstack/benchmark-fixture.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
fields = ['seeders', 'leechers', 'seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6']
expressions = []
for field in fields:
    seeder = int(field.startswith('seeders'))
    family = ' AND e.family='+field[-1] if field.endswith(('4', '6')) else ''
    expressions.append(f'SUM(p.active=1 AND p.visible=1 AND p.seeder={seeder} AND EXISTS(SELECT 1 FROM peer_ips e WHERE e.user_id=p.user_id AND e.torrent_id=p.torrent_id AND e.peer_id=p.peer_id{family})) AS {field}')
select = 'SELECT /*+ MAX_EXECUTION_TIME(5000) */ p.torrent_id,'+','.join(expressions)+' FROM peers p GROUP BY p.torrent_id'
update = 'UPDATE torrents t LEFT JOIN ('+select+') c ON c.torrent_id=t.id SET '+','.join(f't.{f}=COALESCE(c.{f},0)' for f in fields)
output = {}
with fixture.connect() as db, db.cursor() as c:
    c.execute('SELECT DATABASE() AS name')
    assert c.fetchone()['name'] == 'unit3d_dualstack_journal_test'
    queries = {
        'active_queries': "SELECT ID,TIME,STATE,LEFT(INFO,350) AS statement FROM information_schema.PROCESSLIST WHERE DB=DATABASE() AND COMMAND<>'Sleep' AND ID<>CONNECTION_ID() AND INFO LIKE 'UPDATE torrents t LEFT JOIN (SELECT p.torrent_id,%'",
        'table_sizes': 'SELECT (SELECT COUNT(*) FROM peers) AS peers,(SELECT COUNT(*) FROM peer_ips) AS endpoints',
        'endpoint_indexes': 'SHOW INDEX FROM peer_ips',
        'peers_indexes': 'SHOW INDEX FROM peers',
        'update_plan': 'EXPLAIN FORMAT=JSON '+update,
        'select_plan': 'EXPLAIN FORMAT=JSON '+select,
    }
    for name, query in queries.items():
        c.execute(query)
        rows = c.fetchall()
        output[name] = json.loads(rows[0]['EXPLAIN']) if name.endswith('_plan') else rows
    started = time.monotonic()
    try:
        c.execute(select)
        output['select_result'] = c.fetchall()
    except Exception as error:
        output['select_error'] = dict(type=type(error).__name__, code=error.args[0])
    output['select_seconds'] = time.monotonic()-started
    db.rollback()
print(json.dumps(output, default=str, indent=2))
