#!/usr/bin/env python3
"""Sonda curta de infraestrutura; não representa throughput do tracker."""
import argparse
import json
from pathlib import Path
import socket
import time
import pymysql

assert socket.gethostname() == 'unit3d-ds-clients'
parser = argparse.ArgumentParser()
parser.add_argument('--seconds', type=int, default=25)
args = parser.parse_args()
credentials = dict(line.split('=', 1) for line in Path('/opt/unit3d-dualstack/database.env').read_text().splitlines())
db = pymysql.connect(host='172.29.92.20', user=credentials['MYSQL_USER'], password=credentials['MYSQL_PASSWORD'],
                     database='unit3d_dualstack_journal_test', autocommit=True,
                     connect_timeout=5, read_timeout=5, write_timeout=5)
try:
    with db.cursor() as c:
        c.execute('CREATE TABLE IF NOT EXISTS storage_archive_probe (id INT PRIMARY KEY, n BIGINT NOT NULL, payload VARBINARY(16384) NOT NULL) ENGINE=InnoDB')
        c.execute("INSERT IGNORE INTO storage_archive_probe VALUES (1,0,REPEAT('x',16384))")
        c.execute('SELECT n FROM storage_archive_probe WHERE id=1')
        before = c.fetchone()[0]
        samples = []
        began = time.monotonic()
        for i in range(args.seconds * 200):
            delay = began + i / 200 - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            start = time.monotonic()
            c.execute('UPDATE storage_archive_probe SET n=n+1 WHERE id=1')
            samples.append((time.monotonic() - start) * 1000)
        elapsed = time.monotonic() - began
        c.execute('SELECT n FROM storage_archive_probe WHERE id=1')
        assert c.fetchone()[0] - before == len(samples)
        ordered = sorted(samples)
        print(json.dumps({'offered_tps': 200, 'commits': len(samples), 'elapsed_seconds': elapsed,
                          'throughput': len(samples) / elapsed,
                          'p50_ms': ordered[int(len(samples) * .5)],
                          'p95_ms': ordered[int(len(samples) * .95)],
                          'p99_ms': ordered[int(len(samples) * .99)], 'max_ms': max(samples),
                          'errors': 0, 'samples_ms': samples}))
finally:
    db.close()
