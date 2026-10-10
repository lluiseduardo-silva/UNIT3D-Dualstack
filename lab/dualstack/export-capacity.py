#!/usr/bin/env python3
"""Exporta apenas JSON/JSONL públicos da série de capacidade indicada."""
import argparse
import json
from pathlib import Path
import tarfile

p=argparse.ArgumentParser();p.add_argument('series');args=p.parse_args()
assert args.series.replace('-','').isalnum()
root=Path('/storage_pool/unit3d-dualstack')
selected=[]
for role in ('supervisor','tracker','data','clients'):
    parent=root/role/('capacity' if role=='supervisor' else 'results/capacity')
    for folder in parent.glob(args.series+'*'):
        if not folder.is_dir() or not (folder.name==args.series or folder.name.startswith(args.series+'-')):continue
        selected.extend(f for f in folder.rglob('*') if f.is_file() and f.suffix in ('.json','.jsonl'))
assert selected
target=Path('/tmp')/(args.series+'-public.tar.gz')
with tarfile.open(target,'w:gz') as archive:
    for file in sorted(selected):
        assert file.resolve().is_relative_to(root.resolve()) and not file.is_symlink()
        archive.add(file,arcname=file.relative_to(root).as_posix(),recursive=False)
print(json.dumps({'files':len(selected),'bytes':target.stat().st_size,'archive':str(target)}))
