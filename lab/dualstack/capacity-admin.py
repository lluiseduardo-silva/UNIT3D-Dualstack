#!/usr/bin/env python3
"""Administração restrita à base de capacidade; nunca imprime configuração privada."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit

BASE = Path('/opt/unit3d-dualstack')
DB = 'unit3d_dualstack_capacity_20261010'
SOURCE = 'unit3d_dualstack_recovery_test'
NAME = 'unit3d-ds-capacity'
DIGEST = '25a9860c6caad0d78e2c3f8073f6ecd6822c05cbcd1b45773d0994a7df6d6833'


def command(args, timeout=60, **kwargs):
    r = subprocess.run(args, capture_output=True, timeout=timeout, **kwargs)
    assert r.returncode == 0, 'comando_falhou'
    return r.stdout


def mysql(sql, timeout=30):
    return command(['docker', 'exec', '-i', 'unit3d-ds-mysql', 'sh', '-c',
                    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --skip-column-names'],
                   timeout, input=sql.encode()).decode().strip()


def source_state():
    return mysql(f'SELECT COUNT(*),SUM(state_version),SUM(uploaded) FROM {SOURCE}.peers; '
                 f'SELECT SUM(uploaded) FROM {SOURCE}.users; SELECT COUNT(*) FROM {SOURCE}.peer_ips;')


def data(action):
    assert socket.gethostname() == 'unit3d-ds-data'
    if action == 'prepare':
        before = source_state()
        assert mysql(f"SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{DB}'") == '0', 'base_ja_existe'
        assert mysql(f'SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM {SOURCE}.tracker_ownership WHERE id=1') == '0'
        dump = command(['docker', 'exec', 'unit3d-ds-mysql', 'sh', '-c',
                        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --skip-lock-tables --set-gtid-purged=OFF '+SOURCE], 120)
        mysql(f'CREATE DATABASE {DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        command(['docker', 'exec', '-i', 'unit3d-ds-mysql', 'sh', '-c',
                 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot '+DB], 120, input=dump)
        user = command(['docker', 'exec', 'unit3d-ds-mysql', 'printenv', 'MYSQL_USER']).decode().strip()
        assert re.fullmatch('[a-zA-Z0-9_]+', user)
        mysql(f"GRANT ALL PRIVILEGES ON {DB}.* TO '{user}'@'%'")
        assert before == source_state(), 'fonte_alterada'
        print(json.dumps({'prepared': DB, 'source_preserved': True}))
    elif action == 'reset':
        assert mysql(f'SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM {DB}.tracker_ownership WHERE id=1') == '0', 'proprietario_ativo'
        assert mysql(f"SELECT COUNT(*) FROM performance_schema.threads WHERE PROCESSLIST_DB='{DB}'") == '0', 'conexoes_ativas'
        mysql(f"""USE {DB}; START TRANSACTION;
UPDATE peers SET uploaded=0,downloaded=0,state_version=0,created_at=UTC_TIMESTAMP(),updated_at=UTC_TIMESTAMP(),session_generation=1,active=1,visible=1,connectable=1,protocol_state=JSON_OBJECT('last_announces',JSON_OBJECT('4',UNIX_TIMESTAMP(),'6',UNIX_TIMESTAMP()),'session_started_at',UNIX_TIMESTAMP()),ip=INET6_ATON('172.29.92.30');
UPDATE peer_ips SET ip=INET6_ATON(IF(family=4,'172.29.92.30','fd42:756e:6974:92::30')),last_announced_at=UTC_TIMESTAMP(),created_at=UTC_TIMESTAMP(),updated_at=UTC_TIMESTAMP(),revision=1,connectable=1;
UPDATE history SET uploaded=0,downloaded=0,actual_uploaded=0,actual_downloaded=0,client_uploaded=0,client_downloaded=0,state_version=0,seedtime=0,active=1,swarm_updated_at=UTC_TIMESTAMP(),updated_at=UTC_TIMESTAMP();
UPDATE users SET uploaded=0,downloaded=0,seedbonus=0;
UPDATE torrents SET times_completed=0,balance=0;
COMMIT;""", 90)
        assert mysql(f'SELECT COUNT(*),SUM(state_version),SUM(uploaded) FROM {DB}.peers') == '10000\t0\t0'
        assert mysql(f'SELECT COUNT(*) FROM {DB}.peer_ips') == '20000'
        print(json.dumps({'reset': DB}))
    elif action == 'status':
        print(json.dumps({'database': DB, 'rows': mysql(f"""SELECT 'peers',COUNT(*),SUM(state_version),SUM(uploaded) FROM {DB}.peers;
SELECT 'history',SUM(uploaded),SUM(actual_uploaded) FROM {DB}.history;
SELECT 'users',SUM(uploaded) FROM {DB}.users;
SELECT 'endpoints',COUNT(*),SUM(family=4),SUM(family=6) FROM {DB}.peer_ips;
SELECT 'owner',generation,COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM {DB}.tracker_ownership WHERE id=1;
SELECT 'settings',VERSION(),@@innodb_buffer_pool_size,@@innodb_flush_log_at_trx_commit,@@sync_binlog,@@innodb_io_capacity,@@innodb_io_capacity_max;
""").splitlines()}))
    else:
        raise AssertionError('acao_invalida')


def tracker(action, *, target=None, digest=DIGEST):
    assert socket.gethostname() == 'unit3d-ds-tracker'
    target = target or BASE/'experiments/lease-recovery'
    assert hashlib.sha256((target/'target/release/unit3d-announce').read_bytes()).hexdigest() == digest
    proof={}
    if action == 'start':
        assert not command(['docker', 'ps', '--format', '{{.Names}}']).strip(), 'outro_tracker_ativo'
        assert NAME not in command(['docker', 'ps', '-a', '--format', '{{.Names}}']).decode().splitlines()
        values = dict(line.split('=', 1) for line in (BASE/'lease-recovery.env').read_text().splitlines() if '=' in line)
        u = urlsplit(values['DATABASE_URL'])
        values['DATABASE_URL'] = urlunsplit((u.scheme,u.netloc,'/'+DB,u.query,u.fragment))
        values.update(DUALSTACK_BATCH_SIZE='500', DUALSTACK_ENDPOINT_TTL='7200', DUALSTACK_MAX_PENDING_TRANSITIONS='100000')
        env = BASE/'capacity.env'
        env.write_text(''.join(k+'='+v+'\n' for k,v in values.items())); env.chmod(0o600)
        images = dict(line.split('=',1) for line in (BASE/'lab/images.env').read_text().splitlines() if '=' in line)
        command(['docker','run','-d','--name',NAME,'--network','host','--stop-signal=SIGTERM','--stop-timeout=180',
                 '--log-opt','max-size=10m','--log-opt','max-file=2','-v',str(target)+':/app:ro',
                 '-v',str(env)+':/app/.env:ro','-w','/app',images['RUST_IMAGE'].strip('"\''),'./target/release/unit3d-announce'])
        deadline = time.monotonic()+120
        while True:
            try:
                with socket.create_connection(('127.0.0.1',8081),timeout=1): break
            except OSError:
                assert time.monotonic()<deadline, 'readiness_timeout'
                time.sleep(.5)
    elif action == 'stop':
        if NAME in command(['docker','ps','-a','--format','{{.Names}}']).decode().splitlines():
            command(['docker','stop','-t','180',NAME],195)
            state=json.loads(command(['docker','inspect',NAME,'--format','{{json .State}}']))
            assert state['ExitCode']==0 and not state['OOMKilled'], 'encerramento_falhou'
            proof={'exit_code':state['ExitCode'],'oom_killed':state['OOMKilled'],'finished_at':state['FinishedAt']}
            command(['docker','rm',NAME])
    else:
        raise AssertionError('acao_invalida')
    print(json.dumps({'action':action,'binary_sha256':digest,**proof}))


if __name__ == '__main__':
    os.umask(0o077)
    assert os.geteuid()==0
    try: {'data':data,'tracker':tracker}[sys.argv[1]](sys.argv[2])
    except Exception as e:
        print(json.dumps({'status':'failed','type':type(e).__name__, 'reason':str(e) if isinstance(e,AssertionError) else 'diagnostico_local'}))
        raise SystemExit(1)
