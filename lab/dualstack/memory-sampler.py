#!/usr/bin/env python3
"""Amostra processos reais e cache sem exportar chaves ou credenciais."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time


def main():
    assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-tracker'
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend',choices=['php','rust'],required=True)
    parser.add_argument('--seconds',type=int,default=155)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    assert 1 <= args.seconds <= 240 and not args.output.exists()
    containers = ['unit3d-ds-rust'] if args.backend == 'rust' else ['unit3d-ds-php','unit3d-ds-coordinator','unit3d-ds-probe']
    roots = {name:int(subprocess.check_output(['docker','inspect','-f','{{.State.Pid}}',name])) for name in containers}

    def process_memory(pid):
        result = dict(rss_kib=0,pss_kib=0,processes=0)
        pending = [pid]
        while pending:
            current = pending.pop()
            try:
                for task in (Path('/proc')/str(current)/'task').iterdir():
                    pending.extend(map(int,(task/'children').read_text().split()))
                text = (Path('/proc')/str(current)/'smaps_rollup').read_text()
                fields = {line.split(':')[0]:int(line.split()[1]) for line in text.splitlines() if line.startswith(('Rss:', 'Pss:'))}
                result['rss_kib'] += fields['Rss']
                result['pss_kib'] += fields['Pss']
                result['processes'] += 1
            except (FileNotFoundError,ProcessLookupError):
                continue
        return result

    with args.output.open('x') as output:
        for _ in range(args.seconds):
            started = time.monotonic()
            row = dict(at=time.time(),processes={name:process_memory(pid) for name,pid in roots.items()})
            if args.backend == 'php':
                raw = subprocess.check_output(['docker','exec','unit3d-ds-coordinator','php','/lab/memory-redis.php'],text=True)
                row['cache'] = json.loads(raw)
                assert row['cache']['entries'] <= 16 and row['cache']['deadlines'] <= 16
            output.write(json.dumps(row)+'\n')
            output.flush()
            time.sleep(max(0,1-(time.monotonic()-started)))


if __name__ == '__main__':
    main()
