#!/usr/bin/env python3
"""Snapshot somente leitura do banco isolado, sem passkeys ou credenciais na saida."""
import json
from pathlib import Path
import socket
import pymysql

if socket.gethostname() != 'unit3d-ds-clients':
    raise SystemExit('Exige a VM isolada de clientes.')
credentials = dict(line.split('=', 1) for line in Path('/opt/unit3d-dualstack/database.env').read_text().splitlines())
db = pymysql.connect(host='172.29.92.20', user=credentials['MYSQL_USER'], password=credentials['MYSQL_PASSWORD'],
                     database='unit3d_dualstack_journal_test', autocommit=True, cursorclass=pymysql.cursors.DictCursor,
                     connect_timeout=3, read_timeout=3, write_timeout=3)
statements = {
    'runtime': "SELECT DATABASE() AS db,VERSION() AS version,@@transaction_isolation AS isolation_level,@@innodb_lock_wait_timeout AS lock_wait_seconds",
    'owner': "SELECT generation,backend,php_journal_drained,COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) AS live FROM tracker_ownership WHERE id=1",
    'peers': "SELECT user_id,torrent_id,HEX(peer_id) AS peer_id_hex,state_version,session_generation,uploaded,downloaded,active,seeder FROM peers ORDER BY user_id,torrent_id,peer_id",
    'endpoints': "SELECT user_id,torrent_id,HEX(peer_id) AS peer_id_hex,family,INET6_NTOA(ip) AS ip,port,revision,last_announced_at,connectable,connectivity_checked_at FROM peer_ips ORDER BY user_id,torrent_id,peer_id,family",
    'history': "SELECT user_id,torrent_id,state_version,uploaded,actual_uploaded,downloaded,actual_downloaded,active,seeder,seedtime,created_at,updated_at,swarm_updated_at,completed_at FROM history ORDER BY user_id,torrent_id",
    'user': "SELECT id,uploaded,downloaded FROM users WHERE id=12001",
    'torrent': "SELECT id,seeders,leechers,seeders_ipv4,seeders_ipv6,leechers_ipv4,leechers_ipv6,times_completed FROM torrents WHERE id=12001",
    'timestamp_types': "SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('history','peers','peer_ips') AND DATA_TYPE IN ('timestamp','datetime') ORDER BY TABLE_NAME,ORDINAL_POSITION",
    'test_triggers': "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE() AND TRIGGER_NAME='dualstack_test_fail'",
    'test_constraints': "SELECT CONSTRAINT_NAME FROM information_schema.CHECK_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_NAME='dualstack_test_fail'",
}
try:
    result = {}
    with db.cursor() as cursor:
        for label, query in statements.items():
            cursor.execute(query)
            result[label] = cursor.fetchall()
    print(json.dumps(result, indent=2, default=str))
finally:
    db.close()
