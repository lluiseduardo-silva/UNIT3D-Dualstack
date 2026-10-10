#!/usr/bin/env python3
"""Seleção explícita de binário para o A/B; preserva o binário de referência."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('admin', HERE/'capacity-admin.py')
a = importlib.util.module_from_spec(spec); spec.loader.exec_module(a)


def main(argv):
    assert os.geteuid() == 0
    os.umask(0o077)
    if argv == ['preserve-a1']:
        assert socket.gethostname() == 'unit3d-ds-data'
        assert a.mysql(f'SELECT COUNT(*),SUM(state_version),SUM(uploaded) FROM {a.DB}.peers') == '10000\t1815000\t90752000', 'estado_a1_divergente'
        assert a.mysql(f'SELECT COALESCE(lease_expires_at>UTC_TIMESTAMP(3),0) FROM {a.DB}.tracker_ownership WHERE id=1') == '0'
        assert a.mysql(f"SELECT COUNT(*) FROM performance_schema.threads WHERE PROCESSLIST_DB='{a.DB}'") == '0'
        target = a.BASE/'private/capacity-memory-4g-v1.sql'
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open('xb') as out:
            target.chmod(0o600)
            result = subprocess.run(['docker','exec','unit3d-ds-mysql','sh','-c',
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --skip-lock-tables --set-gtid-purged=OFF '+a.DB], stdout=out, stderr=subprocess.PIPE, timeout=90)
        assert result.returncode == 0 and target.stat().st_size > 0, 'copia_incompleta'
        print(json.dumps({'preserved_locally':True, 'source_series':'capacity-memory-4g-v1',
                          'bytes':target.stat().st_size, 'sha256':hashlib.sha256(target.read_bytes()).hexdigest(), 'exported':False}))
        return
    assert len(argv) == 3 and argv[0] in ('a','b') and argv[1] == 'tracker' and argv[2] in ('start','stop','verify'), 'acao_invalida'
    manifest = json.loads((HERE/'capacity-cache-manifest.json').read_text())
    variant = manifest['variants'][argv[0]]
    expected = a.BASE/'experiments'/('lease-recovery' if argv[0]=='a' else 'statement-cache-b')
    assert Path(variant['runtime_path']) == expected, 'caminho_invalido'
    if argv[0] == 'a':
        assert variant['binary_sha256'] == a.DIGEST, 'referencia_alterada'
    if argv[2] == 'verify':
        assert socket.gethostname() == 'unit3d-ds-tracker'
        assert hashlib.sha256((expected/'target/release/unit3d-announce').read_bytes()).hexdigest() == variant['binary_sha256'], 'binario_divergente'
        print(json.dumps({'variant':argv[0], 'binary_verified':True, **variant}))
        return
    a.tracker(argv[2], target=expected, digest=variant['binary_sha256'])


if __name__ == '__main__':
    try: main(sys.argv[1:])
    except Exception as exc:
        print(json.dumps({'status':'failed','type':type(exc).__name__,
                          'reason':str(exc) if isinstance(exc,AssertionError) else 'diagnostico_local'}))
        raise SystemExit(1)
