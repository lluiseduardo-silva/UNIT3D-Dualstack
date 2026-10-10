#!/usr/bin/env python3
"""Atualiza estatisticas apenas da fixture, antes de abrir o tracker."""
import importlib.util
import json
import time

spec = importlib.util.spec_from_file_location('fixture', '/opt/unit3d-dualstack/benchmark-fixture.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
started = time.monotonic()
with fixture.connect() as db, db.cursor() as c:
    c.execute('SELECT DATABASE() AS name')
    assert c.fetchone()['name'] == 'unit3d_dualstack_journal_test'
    c.execute('SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1')
    assert c.fetchone()['live'] == 0, 'Encerre o proprietario antes de preparar estatisticas'
    c.execute('ANALYZE TABLE peers,peer_ips,history,torrents')
    rows = c.fetchall()
    assert len(rows) == 4 and all(row['Msg_type'] == 'status' and row['Msg_text'] == 'OK' for row in rows)
print(json.dumps(dict(fixture_statistics='analyzed', tables=['peers','peer_ips','history','torrents'], seconds=time.monotonic()-started)))
