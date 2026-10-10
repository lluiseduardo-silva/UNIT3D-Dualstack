#!/usr/bin/env python3
"""Perfil isolado a partir do runner validado, usando o binário de produto."""
import json
import hashlib
from pathlib import Path
import socket
import subprocess
import sys

assert socket.gethostname()=='unit3d-ds-tracker'
plan=json.loads(Path(sys.argv[1]).read_text())
assert plan['ttl'] in (15,60,7200)
base=Path('/opt/unit3d-dualstack')
text=(base/'lab/benchmark-backend.sh').read_text()
if 'rust_binary_sha256' in plan:
    # Binário validado em cópia separada; o binário/checkout da v2 ficam intactos.
    candidate=base/'experiments/lease-recovery'
    digest=hashlib.sha256((candidate/'target/release/unit3d-announce').read_bytes()).hexdigest()
    assert digest==plan['rust_binary_sha256']=='25a9860c6caad0d78e2c3f8073f6ecd6822c05cbcd1b45773d0994a7df6d6833'
    text=text.replace('$source_dir/UNIT3D-Announce',str(candidate))
needle="values.pop('LISTENING_UNIX_SOCKET', None)"
assert text.count(needle)==1
text=text.replace(needle,"values.update(DUALSTACK_BATCH_SIZE='500', DUALSTACK_ENDPOINT_TTL='"+str(plan['ttl'])+"')\n"+needle)
needle='docker run -d --name unit3d-ds-rust --network host'
assert text.count(needle)==1
text=text.replace(needle,needle+' --log-opt max-size=10m --log-opt max-file=2')
target=base/'lab/soak-backend-generated.sh'
target.write_text(text)
variant=plan.get('comparison_variant','candidate')
assert variant in ('original','candidate')
assert variant!='original' or 'rust_binary_sha256' not in plan
subprocess.run(['bash',str(target),'start','rust',variant],check=True,timeout=300)
if 'rust_binary_sha256' in plan:
    assert hashlib.sha256((candidate/'target/release/unit3d-announce').read_bytes()).hexdigest()==digest
    print(json.dumps({'rust_binary_sha256':digest,'validated_candidate':True}))
