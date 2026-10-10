#!/usr/bin/env python3
"""Exporta apenas JSONs permitidos, conferindo segredos antes de criar o arquivo."""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import tarfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('runs', nargs='+')
    args = parser.parse_args()
    assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients'
    base = Path('/opt/unit3d-dualstack')
    root = base/'real-clients'
    fixture = json.loads((base/'fixture.json').read_text())
    files = []
    for run in args.runs:
        assert re.fullmatch(r'(php|rust)-[0-9]{8}T[0-9]{6}', run)
        folder = root/run
        files.append(folder/'versions.json')
        files.extend(sorted(folder.glob('*/result.json')))
    for path in files:
        payload = path.read_text()
        assert all(user['passkey'] not in payload for user in fixture['users'])
        assert '/announce/' not in payload and 'password' not in payload.lower()
        json.loads(payload)
    target = Path('/tmp/unit3d-real-client-results.tgz')
    with tarfile.open(target, 'w:gz') as archive:
        for path in files:
            archive.add(path, arcname=str(path.relative_to(root)), recursive=False)
    target.chmod(0o644)  # Conteudo ja validado como publico; permite a copia pelo usuario lab.
    print(json.dumps({'exported_public_files': len(files), 'archive': str(target)}))


if __name__ == '__main__':
    main()
