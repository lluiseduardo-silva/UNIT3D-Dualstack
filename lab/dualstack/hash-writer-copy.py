#!/usr/bin/env python3
"""Exportar somente identidade de codigo/binario, nunca ambiente privado."""
from pathlib import Path
import hashlib
import json
import socket
import sys

assert socket.gethostname()=='unit3d-ds-tracker'
label,=sys.argv[1:]
assert label in ('writer-cadence','writer-endpoints')
root=Path('/opt/unit3d-dualstack/experiments')/label
record=json.loads((root/'lab-source.json').read_text())
current={str(p.relative_to(root)):hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sorted((root/'src').rglob('*.rs'))}
assert current==record['hashes'], 'Instrumentacao mudou depois do preparo'
record['binary_sha256']=hashlib.sha256((root/'target/release/unit3d-announce').read_bytes()).hexdigest()
record['cargo_sha256']={name:hashlib.sha256((root/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in ('Cargo.toml','Cargo.lock')}
print(json.dumps(record,indent=2))
