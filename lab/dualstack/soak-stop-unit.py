#!/usr/bin/env python3
"""Parada idempotente de unidades transitórias exclusivas deste laboratório."""
import subprocess
import sys

name=sys.argv[1]
assert name.startswith(('unit3d-soak-load-','unit3d-soak-observer-'))
assert all(c.isalnum() or c=='-' for c in name)
state=subprocess.run(['systemctl','show',name,'--value','-p','LoadState'],capture_output=True,text=True,check=True,timeout=5).stdout.strip()
if state!='not-found':
    subprocess.run(['systemctl','stop',name],check=True,timeout=140)
