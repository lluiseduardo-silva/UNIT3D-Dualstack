#!/usr/bin/env python3
"""Integração exclusiva do laboratório: força rotação real entre as consultas."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import time
from unittest.mock import patch

assert socket.gethostname() == 'unit3d-ds-data' and os.geteuid() == 0
spec = importlib.util.spec_from_file_location('archive', Path(__file__).with_name('archive-binlogs.py'))
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)
archive.verify_mount()
archive.server_guard(json.loads(archive.CONFIG.read_text()))
real_mysql = archive.mysql

def accounting():
    return real_mysql('SELECT COUNT(*),SUM(state_version),SUM(uploaded) FROM unit3d_dualstack_journal_test.peers; '
                      'SELECT COUNT(*),SUM(actual_uploaded),SUM(uploaded) FROM unit3d_dualstack_journal_test.history; '
                      'SELECT SUM(uploaded) FROM unit3d_dualstack_journal_test.users; '
                      'SELECT COUNT(*) FROM unit3d_dualstack_journal_test.peer_ips; '
                      'SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM unit3d_dualstack_journal_test.tracker_ownership WHERE id=1;')

before = accounting()
assert before[-1] == ['0'], 'tracker_must_be_stopped'
cases = []

def run(rotations):
    remaining = rotations
    lists = 0
    def query(sql, *, timeout):
        nonlocal remaining, lists
        rows = real_mysql(sql, timeout=timeout)
        if sql == 'SHOW BINARY LOGS;':
            lists += 1
            if remaining:
                # Use the actual server, not a forged list or alternate schema.
                real_mysql('FLUSH BINARY LOGS;', timeout=timeout)
                remaining -= 1
        return rows
    started = time.monotonic()
    with patch.object(archive, 'mysql', side_effect=query):
        try:
            logs = archive.inventory()
        except RuntimeError as error:
            assert rotations == 3 and str(error) == 'rotation_during_inventory_retry_later'
            result = 'exhausted_as_expected'
        else:
            assert rotations == 1 and logs[-1][0] == real_mysql('SHOW MASTER STATUS;')[0][0]
            result = 'recovered'
    elapsed = time.monotonic() - started
    assert remaining == 0 and lists == (2 if rotations == 1 else 3)
    assert elapsed < 5, 'inventory_budget_exceeded'
    cases.append({'rotations': rotations, 'attempts': lists, 'seconds': elapsed, 'result': result})

for _ in range(20):
    run(1)
run(3)
assert archive.inventory(), 'stable_inventory_after_exhaustion'
after = accounting()
assert before == after, 'accounting_changed'
print(json.dumps({'status': 'passed', 'cases': cases, 'real_rotations': 23,
                  'accounting_unchanged': True, 'sql_accounting': after}, indent=2))
