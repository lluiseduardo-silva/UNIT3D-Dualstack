#!/usr/bin/env python3
"""Prepara copia de codigo/cache e banco separados; preserva a evidencia v2."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
from urllib.parse import urlsplit,urlunsplit

BASE=Path('/opt/unit3d-dualstack')
DB='unit3d_dualstack_recovery_test'
NAME='unit3d-ds-lease-recovery'
ORIGINAL='8b825a1afb418f237803d5306abb0b57c2340ecb4b9f5871bc61dd290f3e4ace'
assert os.geteuid()==0
os.umask(0o077)
action=sys.argv[2] if len(sys.argv)>2 else 'prepare'
def command(args,timeout=90):
    r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    assert r.returncode==0,'comando_falhou'
    return r.stdout

if sys.argv[1]=='data':
    assert socket.gethostname()=='unit3d-ds-data'
    spec=importlib.util.spec_from_file_location('admin','/tmp/lease-probe-admin.py')
    admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)
    admin.DB=DB
    admin.OLD='unit3d_dualstack_probe_20261009'
    if action=='restore':
        spec=importlib.util.spec_from_file_location('archive','/usr/local/sbin/unit3d-archive-binlogs.py')
        archive=importlib.util.module_from_spec(spec);spec.loader.exec_module(archive)
        assert archive.mysql(f'SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM {DB}.tracker_ownership WHERE id=1')[0][0]=='0'
        assert archive.mysql(f"SELECT COUNT(*) FROM performance_schema.threads WHERE PROCESSLIST_DB='{DB}'")[0][0]=='0'
        archive.mysql(f'DROP DATABASE {DB}')
        action='prepare'
    admin.data(action)
elif sys.argv[1]=='tracker':
    assert socket.gethostname()=='unit3d-ds-tracker'
    source=BASE/'repos/UNIT3D-Announce'
    target=BASE/'experiments/lease-recovery'
    assert hashlib.sha256((source/'target/release/unit3d-announce').read_bytes()).hexdigest()==ORIGINAL
    if action=='prepare':
        assert not target.exists()
        assert shutil.disk_usage(BASE).free>4*1024**3
        shutil.copytree(source,target,ignore=shutil.ignore_patterns('.git','.env','target'))
        shutil.copytree(source/'target',target/'target')
        with tarfile.open('/tmp/lease-recovery-source.tar') as archive:
            for member in archive.getmembers():
                path=Path(member.name)
                assert not path.is_absolute() and '..' not in path.parts
                assert path.parts[0] in ('src','tests','.sqlx','Cargo.toml','Cargo.lock')
                assert member.isfile() or member.isdir()
            archive.extractall(target,filter='data')
        print(json.dumps({'prepared':str(target),'original_preserved':True,'free_bytes':shutil.disk_usage(BASE).free}))
        raise SystemExit(0)
    digest=hashlib.sha256((target/'target/release/unit3d-announce').read_bytes()).hexdigest()
    assert digest!=ORIGINAL,'candidato_nao_compilado'
    if action=='start':
        assert not command(['docker','ps','--format','{{.Names}}']).strip()
        assert NAME not in command(['docker','ps','-a','--format','{{.Names}}']).splitlines()
        values={k.strip():v.strip() for line in (source/'.env').read_text().splitlines() if '=' in line and not line.lstrip().startswith('#') for k,v in [line.split('=',1)]}
        url=urlsplit(values['DATABASE_URL']);values['DATABASE_URL']=urlunsplit((url.scheme,url.netloc,'/'+DB,url.query,url.fragment))
        values.update(LISTENING_IP_ADDRESS='::',LISTENING_PORT='8081',ANNOUNCE_MIN_ENFORCED='0',DUALSTACK_ENABLED='true',DUALSTACK_BATCH_SIZE='500',
            DUALSTACK_ENDPOINT_TTL='7200',DUALSTACK_ALLOW_PRIVATE_ADDRESSES='true',IS_CONNECTIVITY_CHECK_ENABLED='false',REQUIRE_PEER_CONNECTIVITY='false',
            IS_ANNOUNCE_LOGGING_ENABLED='false',USER_RECEIVE_SEED_LIST_RATE_LIMITS='1=10000',USER_RECEIVE_LEECH_LIST_RATE_LIMITS='1=10000',NUMWANT_MAX='25')
        values.pop('LISTENING_UNIX_SOCKET',None);values.pop('REVERSE_PROXY_CLIENT_IP_HEADER_NAME',None)
        env=BASE/'lease-recovery.env';env.write_text(''.join(k+'='+v+'\n' for k,v in values.items()));env.chmod(0o600)
        # Docker precisa do mountpoint antes de montar /app como somente leitura.
        if not (target/'.env').exists(): (target/'.env').touch(mode=0o600)
        images=dict(line.split('=',1) for line in (BASE/'lab/images.env').read_text().splitlines() if '=' in line)
        command(['docker','run','-d','--name',NAME,'--network','host','--stop-signal=SIGTERM','--stop-timeout=180','--log-opt','max-size=10m','--log-opt','max-file=2',
            '-v',str(target)+':/app:ro','-v',str(env)+':/app/.env:ro','-w','/app',images['RUST_IMAGE'].strip('"\''),'./target/release/unit3d-announce'])
    elif action=='stop':
        command(['docker','stop','-t','180',NAME],timeout=195)
    elif action=='remove':
        state=json.loads(command(['docker','inspect',NAME,'--format','{{json .State}}']))
        assert not state['Running'];command(['docker','rm',NAME])
        print(json.dumps({'action':action,'removed':NAME}));raise SystemExit(0)
    else:assert action=='status'
    state=json.loads(command(['docker','inspect',NAME,'--format','{{json .State}}']))
    r=subprocess.run(['docker','logs',NAME],capture_output=True,text=True,timeout=10)
    lines=[s for s in (r.stdout+r.stderr).splitlines() if any(t in s for t in ('Coordenador','Persistencia','Lote pendente','Renovacao transitoria'))]
    print(json.dumps({'action':action,'binary_sha256':digest,'original_binary_preserved':True,'state':{k:state[k] for k in ('Running','ExitCode','OOMKilled','StartedAt','FinishedAt')},'diagnostics':lines}))
else:
    raise SystemExit('acao invalida')
