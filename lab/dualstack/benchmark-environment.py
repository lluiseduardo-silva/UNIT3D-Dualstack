#!/usr/bin/env python3
"""Inventario publico de runtime; nunca exporta env, tokens ou comandos privados."""
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess

base = Path('/opt/unit3d-dualstack')
hostname = socket.gethostname()
assert os.geteuid() == 0 and hostname in ['unit3d-ds-tracker', 'unit3d-ds-data', 'unit3d-ds-clients']


def command(*args):
    return subprocess.check_output(args, text=True, timeout=30).strip()


report = dict(host=hostname, kernel=platform.release(), python=platform.python_version(),
              cpu_count=os.cpu_count(), architecture=platform.machine())
report['memory'] = {line.split(':')[0]: line.split(':')[1].strip() for line in Path('/proc/meminfo').read_text().splitlines()
                    if line.startswith(('MemTotal:', 'SwapTotal:'))}
report['cpu_model'] = next(line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name'))
report['disk'] = command('df', '-B1', str(base))
if hostname != 'unit3d-ds-clients':
    report['docker'] = command('docker', 'version', '--format', '{{.Server.Version}}')
    report['images'] = []
    image_names = ['unit3d-ds-php:baseline'] if hostname == 'unit3d-ds-tracker' else ['mysql:8.0', 'redis:7.2']
    if hostname == 'unit3d-ds-tracker':
        image_names += [line.split('=', 1)[1] for line in (base/'lab/images.env').read_text().splitlines()
                        if line.startswith(('RUST_IMAGE=', 'NGINX_IMAGE='))]
        report['source_sha256'] = {}
        for project in ['UNIT3D', 'UNIT3D-Announce']:
            digest = hashlib.sha256()
            root = base/'repos'/project
            selected = ['app', 'config', 'database/migrations'] if project == 'UNIT3D' else ['src']
            for directory in selected:
                for path in sorted((root/directory).rglob('*')):
                    if path.is_file():
                        digest.update(path.relative_to(root).as_posix().encode()+b'\0'+path.read_bytes())
            report['source_sha256'][project] = digest.hexdigest()
    for name in image_names:
        inspected = json.loads(command('docker', 'image', 'inspect', name))[0]
        report['images'].append({key: inspected[key] for key in ['Id', 'RepoDigests', 'Architecture', 'Os']})
print(json.dumps(report, indent=2))
