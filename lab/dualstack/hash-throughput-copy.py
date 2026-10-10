#!/usr/bin/env python3
"""Exportar somente hashes; confirmar tambem o manifesto da preparacao."""
from pathlib import Path
import hashlib
import json
import socket
assert socket.gethostname()=='unit3d-ds-tracker'
root=Path('/opt/unit3d-dualstack/experiments/throughput-rust')
manifest=json.loads((root/'lab-source.json').read_text())
for name,digest in manifest['hashes'].items():
    data=(root/name).read_bytes()
    raw=hashlib.sha256(data).hexdigest()
    normalized=hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()
    assert digest in [raw,normalized], name
    manifest['hashes'][name]=normalized
manifest['hash_normalization']='LF'
manifest['binary_sha256']=hashlib.sha256((root/'target/release/unit3d-announce').read_bytes()).hexdigest()
manifest['lock_sha256']=hashlib.sha256((root/'Cargo.lock').read_bytes().replace(b'\r\n',b'\n')).hexdigest()
print(json.dumps(manifest,indent=2))
