#!/usr/bin/env python3
"""Preparação exclusiva do diagnóstico; preserva banco e container da v2."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

BASE = Path('/opt/unit3d-dualstack')
DB = 'unit3d_dualstack_probe_20261009'
OLD = 'unit3d_dualstack_journal_test'
NAME = 'unit3d-ds-lease-probe'
HASH = '8b825a1afb418f237803d5306abb0b57c2340ecb4b9f5871bc61dd290f3e4ace'
os.umask(0o077)


def command(args, **kwargs):
    r = subprocess.run(args, capture_output=True, timeout=kwargs.pop('timeout', 30), **kwargs)
    if r.returncode:
        raise RuntimeError('comando_falhou_' + str(r.returncode))
    return r.stdout


def data(action):
    assert socket.gethostname() == 'unit3d-ds-data'
    s = importlib.util.spec_from_file_location('archive', '/usr/local/sbin/unit3d-archive-binlogs.py')
    a = importlib.util.module_from_spec(s); s.loader.exec_module(a)
    def old_state():
        return a.mysql(f"SELECT SUM(state_version),SUM(uploaded),COUNT(*) FROM {OLD}.peers; SELECT SUM(uploaded),SUM(actual_uploaded) FROM {OLD}.history; SELECT SUM(uploaded) FROM {OLD}.users; SELECT COUNT(*) FROM {OLD}.peer_ips; SELECT generation,COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM {OLD}.tracker_ownership WHERE id=1;")
    before = old_state()
    assert before[-1][-1] == '0', 'proprietario_anterior_ativo'
    if action == 'prepare':
        assert int(a.mysql(f"SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{DB}'")[0][0]) == 0
        assert os.statvfs('/').f_bavail * os.statvfs('/').f_frsize > 8 * 1024**3
        a.mysql(f'CREATE DATABASE {DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        # Dump permanece em memória na VM; nunca é impresso, salvo ou exportado.
        dump = command(['docker','exec','unit3d-ds-mysql','sh','-c',
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --skip-lock-tables --set-gtid-purged=OFF '+OLD], timeout=90)
        command(['docker','exec','-i','unit3d-ds-mysql','sh','-c',
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot '+DB], input=dump, timeout=90)
        user = command(['docker','exec','unit3d-ds-mysql','printenv','MYSQL_USER']).decode().strip()
        assert re.fullmatch(r'[A-Za-z0-9_]+', user)
        a.mysql(f"GRANT ALL PRIVILEGES ON {DB}.* TO '{user}'@'%'")
    elif action == 'reset':
        assert a.mysql(f'SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM {DB}.tracker_ownership WHERE id=1')[0][0] == '0'
        a.mysql(f"""USE {DB}; START TRANSACTION;
UPDATE peers SET uploaded=0,downloaded=0,state_version=0,created_at=UTC_TIMESTAMP(),updated_at=UTC_TIMESTAMP(),session_generation=1,protocol_state=JSON_OBJECT('last_announces',JSON_OBJECT('4',UNIX_TIMESTAMP(),'6',UNIX_TIMESTAMP()),'session_started_at',UNIX_TIMESTAMP()),ip=INET6_ATON('172.29.92.30');
UPDATE peer_ips SET ip=INET6_ATON(IF(family=4,'172.29.92.30','fd42:756e:6974:92::30')),last_announced_at=UTC_TIMESTAMP(),created_at=UTC_TIMESTAMP(),updated_at=UTC_TIMESTAMP(),revision=1;
UPDATE history SET uploaded=0,downloaded=0,actual_uploaded=0,actual_downloaded=0,client_uploaded=0,client_downloaded=0,state_version=0,seedtime=0,swarm_updated_at=UTC_TIMESTAMP(),updated_at=UTC_TIMESTAMP();
UPDATE users SET uploaded=0,downloaded=0,seedbonus=0;
UPDATE torrents SET times_completed=0,balance=0;
COMMIT;""", timeout=60)
    else:
        assert action == 'status'
    after = old_state()
    assert before == after, 'banco_anterior_alterado'
    result={'action':action,'database':DB,'original_state':after,'original_unchanged':True}
    if action == 'status':
        result['probe_audit']=a.mysql(f"""SELECT 'peers',COUNT(*),SUM(state_version),SUM(uploaded),SUM(active),SUM(seeder AND active) FROM {DB}.peers;
SELECT 'history',SUM(uploaded),SUM(actual_uploaded) FROM {DB}.history;
SELECT 'users',SUM(uploaded) FROM {DB}.users;
SELECT 'endpoints',COUNT(*),SUM(family=4),SUM(family=6),SUM(OCTET_LENGTH(ip)<>IF(family=4,4,16)) FROM {DB}.peer_ips;
SELECT 'over_limit',COUNT(*) FROM (SELECT user_id,torrent_id,peer_id FROM {DB}.peer_ips GROUP BY user_id,torrent_id,peer_id HAVING COUNT(*)>2) p;
SELECT 'lease',generation,COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM {DB}.tracker_ownership WHERE id=1;
SELECT 'connections',COUNT(*) FROM performance_schema.threads WHERE PROCESSLIST_DB='{DB}' AND PROCESSLIST_ID<>CONNECTION_ID();
SELECT 'waits',COUNT(*) FROM performance_schema.data_lock_waits w JOIN performance_schema.data_locks r ON r.ENGINE_LOCK_ID=w.REQUESTING_ENGINE_LOCK_ID AND r.ENGINE=w.ENGINE WHERE r.OBJECT_SCHEMA='{DB}';
SELECT 'configuration',VERSION(),@@innodb_flush_log_at_trx_commit,@@sync_binlog,@@innodb_buffer_pool_size,@@innodb_redo_log_capacity,@@innodb_io_capacity,@@innodb_io_capacity_max,@@transaction_isolation,@@innodb_lock_wait_timeout;""")
    print(json.dumps(result))


def tracker(action):
    assert socket.gethostname() == 'unit3d-ds-tracker'
    binary = BASE/'repos/UNIT3D-Announce/target/release/unit3d-announce'
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    assert digest == HASH, 'binario_diferente'
    if action == 'start':
        existing = command(['docker','ps','-a','--format','{{.Names}}']).decode().splitlines()
        assert NAME not in existing
        assert not command(['docker','ps','--format','{{.Names}}']).decode().strip(), 'tracker_ativo'
        values = {k.strip():v.strip() for line in (BASE/'repos/UNIT3D-Announce/.env').read_text().splitlines()
                  if '=' in line and not line.lstrip().startswith('#') for k,v in [line.split('=',1)]}
        url = urlsplit(values['DATABASE_URL'])
        values['DATABASE_URL'] = urlunsplit((url.scheme,url.netloc,'/'+DB,url.query,url.fragment))
        values.update(LISTENING_IP_ADDRESS='::',LISTENING_PORT='8081',ANNOUNCE_MIN_ENFORCED='0',DUALSTACK_ENABLED='true',
            DUALSTACK_BATCH_SIZE='500',DUALSTACK_ENDPOINT_TTL='7200',DUALSTACK_ALLOW_PRIVATE_ADDRESSES='true',
            IS_CONNECTIVITY_CHECK_ENABLED='false',REQUIRE_PEER_CONNECTIVITY='false',IS_ANNOUNCE_LOGGING_ENABLED='false',
            USER_RECEIVE_SEED_LIST_RATE_LIMITS='1=10000',USER_RECEIVE_LEECH_LIST_RATE_LIMITS='1=10000',NUMWANT_MAX='25')
        values.pop('LISTENING_UNIX_SOCKET',None);values.pop('REVERSE_PROXY_CLIENT_IP_HEADER_NAME',None)
        envfile=BASE/'lease-probe.env';envfile.write_text(''.join(k+'='+v+'\n' for k,v in values.items()));envfile.chmod(0o600)
        images=dict(line.split('=',1) for line in (BASE/'lab/images.env').read_text().splitlines() if '=' in line)
        image=images['RUST_IMAGE'].strip('"\'')
        command(['docker','run','-d','--name',NAME,'--network','host','--stop-signal=SIGTERM','--stop-timeout=60',
            '--log-opt','max-size=10m','--log-opt','max-file=2','-v',str(BASE/'repos/UNIT3D-Announce')+':/app:ro',
            '-v',str(envfile)+':/app/.env:ro','-w','/app',image,'./target/release/unit3d-announce'])
    elif action == 'stop':
        command(['docker','stop','-t','60',NAME],timeout=75)
    elif action == 'remove':
        state=json.loads(command(['docker','inspect',NAME,'--format','{{json .State}}']))
        assert not state['Running'];command(['docker','rm',NAME])
        print(json.dumps({'action':action,'removed':NAME}));return
    else:
        assert action == 'status'
    state=json.loads(command(['docker','inspect',NAME,'--format','{{json .State}}']))
    log_result=subprocess.run(['docker','logs',NAME],capture_output=True,text=True,timeout=10)
    assert log_result.returncode==0
    logs=log_result.stdout+log_result.stderr
    # Saída pública inclui somente diagnóstico do coordenador, nunca URLs/env.
    logs=[x for x in logs.splitlines() if 'Coordenador dualstack:' in x or 'Tempo limite' in x]
    print(json.dumps({'action':action,'binary_sha256':digest,'state':{k:state[k] for k in ('Running','ExitCode','OOMKilled','StartedAt','FinishedAt')},'diagnostics':logs}))


if __name__ == '__main__':
    assert os.geteuid()==0
    try:
        role,action=sys.argv[1:];{'data':data,'tracker':tracker}[role](action)
    except Exception as error:
        print(json.dumps({'status':'failed','type':type(error).__name__,'reason':str(error) if isinstance(error,(AssertionError,RuntimeError)) else 'ver_log_local'}))
        raise SystemExit(1)
