#!/usr/bin/env python3
"""Comparacoes da implementacao, separadas dos experimentos anteriores."""
import json
from pathlib import Path

root=Path(__file__).parent/'plans'
for stage,rates in [('reference200',[4000]),('cadence200',[4000,6000]),('cadence500',[6000,8000,10000,12000]),
                    ('endpoints200',[4000,6000]),('endpoints500',[6000,8000,10000,12000])]:
    name='density-throughput-writer-'+stage+'-v1'
    plan=dict(name=name,sizes=[250]*40,phases=[
        dict(name=f'rate-{rate}-r{repeat+1}',warmup=5,seconds=20,shuffle=True,fast=True,
             groups=dict(target=dict(torrents=list(range(40)),rate=rate)))
        for repeat in range(3) for rate in rates])
    target=root/(name+'.json')
    assert not target.exists() or json.loads(target.read_text())==plan
    target.write_text(json.dumps(plan,indent=2)+'\n')

# Confirmar margem no patamar abaixo do teto, com a mesma fixture e gerador.
name='density-throughput-writer-endpoints-sustained-v1'
plan=dict(name=name,sizes=[250]*40,phases=[dict(name='rate-8000-sustained',
    warmup=10,seconds=180,shuffle=True,fast=True,
    groups=dict(target=dict(torrents=list(range(40)),rate=8000)))])
target=root/(name+'.json')
assert not target.exists() or json.loads(target.read_text())==plan
target.write_text(json.dumps(plan,indent=2)+'\n')
