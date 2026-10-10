#!/usr/bin/env python3
"""Somente metadados públicos permitidos; nunca imprimir o ambiente completo."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys

assert socket.gethostname()=='unit3d-ds-tracker'
name=sys.argv[1];assert all(c.isalnum() or c=='-' for c in name)
b=Path('/opt/unit3d-dualstack')
manifest=json.loads(Path('/tmp/unit3d-original-manifest.json').read_text(encoding='utf-8-sig'))
for filename,digest in manifest.items():
    blob=(b/'originals/UNIT3D-Announce'/filename).read_bytes().replace(b'\r\n',b'\n')
    assert hashlib.sha1(b'blob '+str(len(blob)).encode()+b'\0'+blob).hexdigest()==digest,'original_source_changed'
values={k.strip():v.strip() for line in (b/'rust-benchmark.env').read_text().splitlines() if '=' in line for k,v in [line.split('=',1)]}
keys=['FLUSH_INTERVAL_MILLISECONDS','ANNOUNCE_MIN_ENFORCED','NUMWANT_MAX','IS_CONNECTIVITY_CHECK_ENABLED',
      'REQUIRE_PEER_CONNECTIVITY','IS_ANNOUNCE_LOGGING_ENABLED','USER_RECEIVE_SEED_LIST_RATE_LIMITS',
      'USER_RECEIVE_LEECH_LIST_RATE_LIMITS','DUALSTACK_ENABLED','LISTENING_IP_ADDRESS','LISTENING_PORT',
      'ACTIVE_PEER_TTL','INACTIVE_PEER_TTL','PEER_EXPIRY_INTERVAL']
binary=b/'originals/UNIT3D-Announce/target/release/unit3d-announce'
digest=hashlib.sha256(binary.read_bytes()).hexdigest()
assert digest=='648e22b58f40b91f1760cab415fdf66c830161646aa4fbfe1056268102ee364d','original_binary_changed'
image=subprocess.check_output(['docker','inspect','unit3d-ds-rust','--format','{{.Config.Image}}'],text=True).strip()
result=dict(name=name,commit='fcd189e9aebf07a12a1f8cc39500819c3870925b',verified_files=len(manifest),
    normalized_line_endings=True,binary_sha256=digest,image=image,
    compiler=subprocess.check_output(['docker','exec','unit3d-ds-rust','rustc','-Vv'],text=True),
    environment={k:values.get(k,'unset_uses_code_default') for k in keys})
folder=b/'comparison-provenance';folder.mkdir(exist_ok=True)
(folder/(name+'.json')).write_text(json.dumps(result)+'\n')
print(json.dumps(result))
