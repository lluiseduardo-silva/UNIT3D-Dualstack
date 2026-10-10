#!/usr/bin/env python3
"""Planos publicos limitados: cada fase drena antes da proxima."""
import json
from pathlib import Path

root=Path(__file__).parent/'plans'
root.mkdir(exist_ok=True)


def make(name, rates, warmup=5, seconds=15, sizes=None, shuffle=False, fast=False):
    sizes=sizes or [250]*40
    phases=[dict(name=f'rate-{rate}-r{i+1}', warmup=warmup, seconds=seconds,
                 groups=dict(target=dict(torrents=list(range(len(sizes))), rate=rate))) for i,rate in enumerate(rates)]
    if shuffle:
        for phase in phases: phase['shuffle']=True
    if fast:
        for phase in phases: phase['fast']=True
    plan=dict(name='density-throughput-'+name, sizes=sizes, phases=phases)
    path=root/(plan['name']+'.json')
    if path.exists():
        assert json.loads(path.read_text())==plan, 'Nao sobrescrever plano diferente'
    else:
        path.write_text(json.dumps(plan,indent=2)+'\n')


make('smoke-v1',[1000,3000],1,3)
make('reference-v1',[1500,4000])
make('unobserved-v1',[1500,4000])
make('ramp-v1',[1000,1800,2000,2500,3000,4000])
make('drain-v1',[1000,2000,3000,4000,6000])
make('mixed-reference-v1',[4000],shuffle=True)
make('mixed-drain-v1',[4000,6000,4000,6000,4000,6000],shuffle=True)
make('mixed-batch500-v1',[4000,6000,4000,6000,4000,6000],shuffle=True)
make('fast-smoke-v1',[4000,6000],1,3,shuffle=True,fast=True)
make('fast-ramp-v1',[4000,6000,8000,10000],3,10,shuffle=True,fast=True)
make('ceiling-v1',[10000,12000,10000],3,15,shuffle=True,fast=True)
make('sustained-v1',[8000],10,180,shuffle=True,fast=True)
