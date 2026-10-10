#!/usr/bin/env python3
"""Exporta apenas evidências públicas leves; nunca os binlogs ou a fixture privada."""
import hashlib
import json
from pathlib import Path
import socket
import sys
import tarfile

assert socket.gethostname()=='proxmox'
name=sys.argv[1];assert all(c.isalnum() or c=='-' for c in name)
root=Path('/storage_pool/unit3d-dualstack')
target=Path('/tmp')/(name+'-public.tar.gz')
entries=[]
with tarfile.open(target,'w:gz') as tar:
    for role in ('supervisor','tracker','data','clients'):
        folder=root/role/(name if role=='supervisor' else 'results/soak/'+name)
        if not folder.exists():continue
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or path.suffix not in ('.json','.jsonl'):continue
            relative=path.relative_to(folder)
            # Identity mapping contains only synthetic IDs, no passkeys; still large
            # and unchanged between windows, so keep it with the raw samples on ZFS.
            if path.name=='identities.json':continue
            archive_name=name+'/'+role+'/'+str(relative)
            tar.add(path,arcname=archive_name,recursive=False)
            entries.append({'path':archive_name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
print(json.dumps({'archive':str(target),'files':len(entries),'bytes':target.stat().st_size}))
