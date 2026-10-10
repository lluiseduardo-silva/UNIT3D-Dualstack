#!/usr/bin/env python3
"""Instala a política de arquivo no laboratório; não inicia automaticamente."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

assert socket.gethostname() == 'unit3d-ds-data' and os.geteuid() == 0
os.umask(0o077)
source = Path(__file__).with_name('archive-binlogs.py')
spec = importlib.util.spec_from_file_location('archive', source)
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)
archive.verify_mount()
uuid = archive.mysql('SELECT @@server_uuid;')[0][0]
config_path = Path('/etc/unit3d-binlog-archive.json')
if not config_path.exists():
    old = archive.mysql('SELECT @@binlog_expire_logs_auto_purge,@@binlog_expire_logs_seconds;')[0]
    config_path.write_text(json.dumps({'server_uuid': uuid, 'exclusive_lab_no_replicas': True,
                                      'previous_auto_purge': int(old[0]),
                                      'previous_expire_seconds': int(old[1])}) + '\n')
config = json.loads(config_path.read_text())
assert config['server_uuid'] == uuid
# Automatic expiry must not race the archive or remove an unverified file.
# This changes retention only; fsync and row logging remain unchanged.
archive.mysql('SET PERSIST binlog_expire_logs_auto_purge=OFF;')
archive.server_guard(config)
shutil.copyfile(source, '/usr/local/sbin/unit3d-archive-binlogs.py')
os.chmod('/usr/local/sbin/unit3d-archive-binlogs.py', 0o700)
Path('/etc/systemd/system/unit3d-binlog-archive.service').write_text('''[Unit]
Description=Arquivo verificado dos binlogs do laboratorio UNIT3D
After=docker.service mnt-unit3d\\x2darchive.mount
RequiresMountsFor=/mnt/unit3d-archive

[Service]
Type=oneshot
UMask=0077
ExecStart=/usr/bin/python3 /usr/local/sbin/unit3d-archive-binlogs.py --purge --max-files 2 --mib-per-second 32
TimeoutStartSec=180
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
''')
Path('/etc/systemd/system/unit3d-binlog-archive.timer').write_text('''[Unit]
Description=Arquivar binlogs fechados do laboratorio UNIT3D

[Timer]
OnBootSec=60
OnUnitInactiveSec=15
AccuracySec=1
Unit=unit3d-binlog-archive.service

[Install]
WantedBy=timers.target
''')
subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=15)
print(json.dumps({'server_uuid': uuid, 'automatic_expiry': False,
                  'service_installed': True, 'timer_started': False,
                  'copy_limit_mib_s': 32}))
