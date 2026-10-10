#!/usr/bin/env python3
"""Preserva evidências privadas da v2 no laboratório antes de reutilizar o schema."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess

assert os.geteuid()==0
os.umask(0o077)
base=Path('/opt/unit3d-dualstack')
role=socket.gethostname()
if role=='unit3d-ds-data':
    spec=importlib.util.spec_from_file_location('admin','/tmp/lease-probe-admin.py')
    admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)
    admin.DB='unit3d_dualstack_soak_v2_evidence'
    admin.data('prepare')  # Cópia somente dentro da VM; nenhuma exportação do dump.
    spec=importlib.util.spec_from_file_location('archive','/usr/local/sbin/unit3d-archive-binlogs.py')
    a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
    tables=a.mysql("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA='unit3d_dualstack_journal_test' AND TABLE_TYPE='BASE TABLE'")
    for (table,) in tables:
        assert table.replace('_','').isalnum()
        counts=a.mysql(f'SELECT COUNT(*) FROM unit3d_dualstack_journal_test.`{table}`; SELECT COUNT(*) FROM {admin.DB}.`{table}`')
        assert counts[0]==counts[1], 'contagem_copia_divergente'
    print(json.dumps({'database_evidence':admin.DB,'tables_verified':len(tables),'copy_verified':True}))
elif role=='unit3d-ds-tracker':
    result=subprocess.run(['docker','inspect','unit3d-ds-rust','--format','{{json .State}}'],capture_output=True,text=True,check=True)
    state=json.loads(result.stdout)
    assert not state['Running'] and state['ExitCode']==1 and state['FinishedAt'].startswith('2026-10-09T07:22:06')
    digest=hashlib.sha256((base/'repos/UNIT3D-Announce/target/release/unit3d-announce').read_bytes()).hexdigest()
    assert digest=='8b825a1afb418f237803d5306abb0b57c2340ecb4b9f5871bc61dd290f3e4ace'
    subprocess.run(['docker','rename','unit3d-ds-rust','unit3d-ds-rust-soak-v2-evidence'],check=True,timeout=10)
    print(json.dumps({'container_preserved':'unit3d-ds-rust-soak-v2-evidence','binary_sha256':digest}))
elif role=='unit3d-ds-clients':
    target=base/'evidence-soak-v2';target.mkdir(exist_ok=False,mode=0o700)
    data=(base/'density-fixture.json').read_bytes()
    assert json.loads(data)['name']=='soak-rust-six-hours-v2'
    (target/'density-fixture.json').write_bytes(data)
    print(json.dumps({'private_fixture_preserved_on_guest':True}))
else:raise SystemExit('host_invalido')
