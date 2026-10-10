#!/usr/bin/env python3
"""Aliases limitados, em endereços exclusivos da fixture do laboratório."""
import argparse
import json
from pathlib import Path
import socket
import subprocess

assert socket.gethostname()=='unit3d-ds-clients'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['add','remove']);args=parser.parse_args()
marker=Path('/opt/unit3d-dualstack/soak-aliases.json')
if args.action=='add':
    assert not marker.exists(),'aliases_owned_by_previous_run'
    current=json.loads(subprocess.check_output(['ip','-j','addr','show','dev','eth1'],text=True))
    used={a['local'] for a in current[0]['addr_info']}
    addresses=[f'172.29.92.{100+i}/32' for i in range(72)]
    addresses += [f'fd42:756e:6974:92::{100+i}/128' for i in range(72)]
    addresses += [f'fd42:756e:6974:92::{0xa000+i:x}/128' for i in range(32)]
    assert all(a.split('/')[0] not in used for a in addresses),'unexpected_existing_alias'
    created=[]
    marker.write_text('[]\n')
    for a in addresses:
        command=['ip','addr','add',a,'dev','eth1']
        if ':' in a:command.append('nodad')
        subprocess.run(command,check=True,timeout=5)
        created.append(a);marker.write_text(json.dumps(created)+'\n')
else:
    addresses=json.loads(marker.read_text())
    for a in addresses:
        assert a.startswith(('172.29.92.','fd42:756e:6974:92::'))
        subprocess.run(['ip','addr','del',a,'dev','eth1'],check=True,timeout=5)
    marker.unlink()
print(json.dumps({'action':args.action,'addresses':len(addresses)}))
