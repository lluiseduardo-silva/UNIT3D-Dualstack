#!/usr/bin/env python3
"""Conferir que o laboratorio partiu exatamente do checkout preservado."""
import hashlib
import json
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[2]
results=root/'lab/dualstack/results/throughput'
reference=json.loads((results/'rust-reference-hashes.json').read_text(encoding='utf-8-sig'))
experiment=json.loads((results/'rust-experiment-hashes.json').read_text(encoding='utf-8-sig'))
assert experiment['lock_sha256']==reference['Cargo.lock']
for name,digest in reference.items():
    assert hashlib.sha256((root/'repos/UNIT3D-Announce'/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==digest, name
modified=sorted(name for name,digest in experiment['hashes'].items() if reference.get(name)!=digest)
assert modified==['src/dualstack/coordinator.rs','src/dualstack/lab_metrics.rs','src/dualstack/mod.rs','src/dualstack/persistence.rs','src/dualstack/response.rs']
expected={'UNIT3D':'6d8e7437daa652fb02519584c456b15dceacffa4','UNIT3D-Announce':'a9ab263de2fe6473c86eeabfd0b6ca1c019f6070'}
for project,commit in expected.items():
    path=root/'repos'/project
    assert subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()==commit
    assert not subprocess.check_output(['git','-C',str(path),'status','--porcelain'],text=True).strip()
assert experiment['base']==expected['UNIT3D-Announce']
output=dict(status='passed',products=expected,reference_files=len(reference),experimental_changes=modified,
            description='Hashes normalizados para LF; produtos limpos e preservados. Experimento em copia isolada.')
(results/'sources-verified.json').write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps(output))
