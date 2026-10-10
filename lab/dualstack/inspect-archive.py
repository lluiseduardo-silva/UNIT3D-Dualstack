#!/usr/bin/env python3
"""Estado operacional público; não exporta binlogs, senhas ou SQL de usuários."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess

spec = importlib.util.spec_from_file_location('archive', '/usr/local/sbin/unit3d-archive-binlogs.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
a.verify_mount()
config = json.loads(a.CONFIG.read_text())
a.server_guard(config)
manifests = [json.loads(p.read_text()) for p in sorted((a.ROOT / 'binlogs' / config['server_uuid']).glob('binlog.*.json'))]
settings = a.mysql("SHOW GLOBAL VARIABLES WHERE Variable_name IN ('version','log_bin','binlog_format','binlog_row_image','binlog_expire_logs_seconds','binlog_expire_logs_auto_purge','max_binlog_size','innodb_redo_log_capacity','innodb_flush_log_at_trx_commit','sync_binlog');")
report = {'settings': dict(settings), 'current_binlogs': a.inventory(),
          'archived_files': len(manifests), 'archived_bytes': sum(m['bytes'] for m in manifests),
          'first_archived': manifests[0]['file'], 'last_archived': manifests[-1]['file'],
          'free_ssd_bytes': os.statvfs('/').f_bavail * os.statvfs('/').f_frsize,
          'free_archive_bytes': os.statvfs(a.ROOT).f_bavail * os.statvfs(a.ROOT).f_frsize,
          'timer_active': subprocess.run(['systemctl','is-active','--quiet','unit3d-binlog-archive.timer']).returncode == 0,
          'manifest': [{k:m[k] for k in ('file','bytes','sha256')} for m in manifests]}
print(json.dumps(report, indent=2))
