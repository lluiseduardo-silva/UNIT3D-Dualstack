#!/usr/bin/env python3
"""Falhas de provisionamento contra namespaces Linux reais, sem tracker."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

BASE = Path('/opt/unit3d-dualstack')
sys.path.insert(0, str(BASE))
spec = importlib.util.spec_from_file_location('real_clients', BASE/'real-clients.py')
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)


def main():
    bt.check(os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-clients', 'VM clientes exigida')
    bt.check('ds-bt-' not in bt.command('ip', 'netns', 'list'), 'Clientes ja ativos')
    real_command, real_write = bt.command, Path.write_text
    cases = ['before_link', 'after_link', 'after_move', 'after_hosts']
    results = []
    for fault in cases:
        def command(*args, **kwargs):
            matches = {
                'before_link': args[:3] == ('ip', 'link', 'add'),
                'after_link': args[:4] == ('ip', 'link', 'set', 'ds-bt-seed'),
                'after_move': 'sysctl' in args,
            }
            if matches.get(fault):
                raise RuntimeError('injected')
            return real_command(*args, **kwargs)

        def write(path, *args, **kwargs):
            if fault == 'after_hosts' and str(path) == '/etc/netns/ds-bt-seed/hosts':
                raise RuntimeError('injected')
            return real_write(path, *args, **kwargs)

        with tempfile.TemporaryDirectory(prefix='ds-lifecycle-') as folder:
            try:
                with patch.object(bt, 'command', command), patch.object(Path, 'write_text', write):
                    bt.Client('qbit', 'seed', 'dual', Path(folder))
            except RuntimeError as error:
                bt.check(str(error) == 'injected', 'Erro inesperado')
            else:
                raise AssertionError('Falha nao injetada')
        bt.check('ds-bt-seed' not in real_command('ip', 'netns', 'list'), 'Namespace vazou')
        bt.check(not any(i['ifname'] == 'ds-bt-seed' for i in json.loads(real_command('ip', '-j', 'link'))), 'Macvlan vazou')
        bt.check(not Path('/etc/netns/ds-bt-seed').exists(), 'Configuracao vazou')
        results.append({'fault': fault, 'status': 'passed'})

    real_command('ip', 'netns', 'add', 'ds-bt-seed')
    try:
        with tempfile.TemporaryDirectory(prefix='ds-lifecycle-') as folder:
            try:
                bt.Client('qbit', 'seed', 'dual', Path(folder))
            except AssertionError:
                pass
            else:
                raise AssertionError('Namespace existente foi adotado')
        bt.check('ds-bt-seed' in real_command('ip', 'netns', 'list'), 'Recurso preexistente removido')
        results.append({'fault': 'existing_namespace_preserved', 'status': 'passed'})
    finally:
        real_command('ip', 'netns', 'delete', 'ds-bt-seed')
    print(json.dumps({'status': 'passed', 'cases': results}))


if __name__ == '__main__':
    main()
