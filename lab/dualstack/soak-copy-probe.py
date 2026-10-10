#!/usr/bin/env python3
"""Pressão controlada do mesmo copiador: arquivo fechado congelado no SSD."""
import importlib.util
import json
from pathlib import Path
import sys

spec=importlib.util.spec_from_file_location('archive','/usr/local/sbin/unit3d-archive-binlogs.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
a.verify_mount()
source=Path('/opt/unit3d-dualstack/soak-copy-source.bin')
if sys.argv[1]=='prepare':
    config=json.loads(a.CONFIG.read_text())
    origin=a.ROOT/'binlogs'/config['server_uuid']/'binlog.000003'
    result=a.copy_verified(origin,source,origin.stat().st_size,128)
else:
    name,number=sys.argv[1:]
    assert all(c.isalnum() or c=='-' for c in name) and number.isdigit()
    folder=a.ROOT/'results/soak'/name
    a.write_json(folder/('copy-started-'+number+'.json'),{'started':True})
    result=a.copy_verified(source,folder/('copy-'+number+'.bin'),source.stat().st_size,32)
    a.write_json(folder/('copy-finished-'+number+'.json'),result)
print(json.dumps(result))
