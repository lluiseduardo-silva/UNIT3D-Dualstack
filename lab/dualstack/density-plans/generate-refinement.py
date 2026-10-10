"""Refina o intervalo de 20 a 40 mil observado na varredura inicial."""
import json
import random
from pathlib import Path

sizes = [50, 250, 20000, 25000, 30000, 40000]
order = list(range(len(sizes)))
shuffled = order.copy()
random.Random(920031).shuffle(shuffled)
phases = []
for repeat, slots in enumerate([order, list(reversed(order)), shuffled], 1):
    for slot in slots:
        phases.append(dict(name=f'refine-n{sizes[slot]}-r{repeat}', warmup=5, seconds=30,
            groups={'target': {'torrents': [slot], 'rate': 1000}}))
Path(__file__).with_name('refinement.json').write_text(json.dumps(
    dict(name='density-refinement-v1', sizes=sizes, phases=phases), indent=2)+'\n')
