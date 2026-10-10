#!/usr/bin/env python3
"""Amostras locais de recursos, sem logs ou configuracoes dos containers."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('--seconds', type=int, required=True)
parser.add_argument('--label', required=True)
parser.add_argument('--stop-file', type=Path)
args = parser.parse_args()
assert not args.stop_file or (args.stop_file.parent == Path('/tmp') and args.stop_file.name.startswith('density-throughput-') and args.stop_file.suffix == '.stop')
assert os.geteuid() == 0 and socket.gethostname() in ['unit3d-ds-tracker', 'unit3d-ds-data']
assert 1 <= args.seconds <= 22000 and all(c.isalnum() or c == '-' for c in args.label)
root = Path('/opt/unit3d-dualstack/results/benchmarks')
root.mkdir(exist_ok=True)
target = root/(args.label+'-'+socket.gethostname()+'.jsonl')
started = time.monotonic()
with target.open('x') as output:
    while time.monotonic()-started < args.seconds:
        if args.stop_file and args.stop_file.exists():
            break
        raw = subprocess.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}'],
                             check=True, text=True, capture_output=True, timeout=10).stdout
        # stats contem somente uso de recursos; ainda assim, limitar campos.
        rows = [{k: v for k, v in json.loads(line).items()
                 if k in ['Name', 'CPUPerc', 'MemUsage', 'MemPerc', 'NetIO', 'BlockIO', 'PIDs']}
                for line in raw.splitlines()]
        memory = {line.split(':')[0]: line.split(':')[1].strip() for line in Path('/proc/meminfo').read_text().splitlines()
                  if line.split(':')[0] in ['MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree']}
        output.write(json.dumps({'elapsed': time.monotonic()-started, 'at': time.time(),
                                 'containers': rows, 'memory': memory, 'loadavg': Path('/proc/loadavg').read_text().strip()})+'\n')
        output.flush()
        time.sleep(min(5, max(0, args.seconds-(time.monotonic()-started))))
print(json.dumps({'status': 'collected', 'path': str(target)}))
