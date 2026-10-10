#!/usr/bin/env python3
"""A/B de cache usando o mesmo diagnóstico, auditoria e restauração de recursos."""
import argparse
import importlib.util
import json
from pathlib import Path
import signal

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('memory', HERE/'capacity-memory-series.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def main(args):
    manifest = json.loads((HERE/'capacity-cache-manifest.json').read_text())
    assert args.variant in manifest['variants']
    assert args.name.startswith('capacity-cache-'+args.variant+'-'), 'nome_divergente'
    proof = json.loads((HERE/'capacity-cache-previous-state.json').read_text())
    assert proof['preserved_locally'] and not proof['exported'] and proof['source_series']=='capacity-memory-4g-v1'
    original_guest = m.s.guest
    verified=json.loads(original_guest(120,['python3',m.s.LAB+'/capacity-cache-admin.py',args.variant,'tracker','verify']))
    assert verified['binary_verified'] and verified['binary_sha256']==manifest['variants'][args.variant]['binary_sha256']
    def guest(vm, argv, *rest, **kwargs):
        if vm == 120 and argv[:3] == ['python3',m.s.LAB+'/capacity-admin.py','tracker']:
            argv = ['python3',m.s.LAB+'/capacity-cache-admin.py',args.variant,*argv[2:]]
        return original_guest(vm, argv, *rest, **kwargs)
    m.s.guest = guest
    signal.signal(signal.SIGTERM, lambda *_: setattr(m.s, 'stop', True))
    # A cópia privada de A1 já foi verificada; não chamar o backup específico de v2.
    m.main(args, preserve_previous=False, metadata={'variant':args.variant, **manifest['variants'][args.variant]})
    folder=m.s.ROOT/'supervisor/capacity'/args.name
    state=m.s.read(folder/'status.json')
    if state['status'] != 'completed' or not state.get('resources_restored'):
        raise SystemExit(1)


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('name')
    p.add_argument('--variant', choices=['a','b'], required=True)
    p.add_argument('--mode', choices=['calibration','diagnostic'], required=True)
    main(p.parse_args())
