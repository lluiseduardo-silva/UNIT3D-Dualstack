"""Plano publico; nenhum segredo ou acesso ao ambiente."""
import json
from pathlib import Path

sizes = [50] + [50]*128 + [250]*128 + [10000]*8
normal = list(range(1, 129))
dense = list(range(129, 257))
extreme = list(range(257, 265))
cases = [('probe', None, 0)]
cases += [('fixed-control', normal, 800)]
cases += [(f'fixed-dense-k{k}', dense[:k], 800) for k in [1, 4, 16, 64, 128]]
for k in [1, 4, 16, 32]:
    cases += [(f'grow-control-k{k}', normal[:k], 50*k),
              (f'grow-dense-k{k}', dense[:k], 50*k)]
for k in [1, 2, 4, 8]:
    cases += [(f'extreme-control-k{k}', normal[:k], 200*k),
              (f'extreme-dense-k{k}', extreme[:k], 200*k)]
phases = []
for repeat in [1, 2]:
    for name, slots, rate in cases if repeat == 1 else reversed(cases):
        groups = {'probe': {'torrents': [0], 'rate': 200}}
        if slots:
            groups['background'] = {'torrents': slots, 'rate': rate}
        phases.append(dict(name=f'{name}-r{repeat}', warmup=5, seconds=15, groups=groups))
plan = dict(name='density-interference-v1', sizes=sizes, phases=phases)
Path(__file__).with_name('interference.json').write_text(json.dumps(plan, indent=2)+'\n')
