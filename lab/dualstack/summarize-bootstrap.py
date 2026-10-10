#!/usr/bin/env python3
"""Audita os seis casos, dezoito aberturas e os planos de acesso medidos."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
directory = root/'lab/dualstack/results/bootstrap'


def tables(value):
    if isinstance(value, dict):
        if 'table_name' in value:
            yield value
        for child in value.values():
            yield from tables(child)
    elif isinstance(value, list):
        for child in value:
            yield from tables(child)


results = []
for population in [1000, 54000, 100000]:
    for layout in ['distributed', 'concentrated']:
        path = directory/f'bootstrap-{population}-{layout}-v1.json'
        report = json.loads(path.read_text(encoding='utf-8-sig'))
        assert report['peers'] == population and report['statistics_analyzed'] is False
        assert report['torrents'] == (population//250 if layout == 'distributed' else 1)
        assert len(report['opens']) == 3
        assert all(o['credit'] == 0 and o['endpoints'] == population*2 and o['seconds'] < 30 for o in report['opens'])
        old, new = report['probes']
        assert not new['interrupted_at_2s'] and new['seconds'] < 2
        access = [t for t in tables(new['plan']) if t['table_name'] == 'p']
        assert len(access) == 1 and access[0]['access_type'] == 'eq_ref' and access[0]['key'] == 'PRIMARY'
        reads = new['handler_read_deltas']
        # Leitura de endpoints proporcional a N, sem repetir varredura por peer.
        assert sum(reads.values()) < population*12
        results.append(dict(peers=population, torrents=report['torrents'], layout=layout,
            bootstrap_min_seconds=min(o['seconds'] for o in report['opens']),
            bootstrap_max_seconds=max(o['seconds'] for o in report['opens']),
            query_seconds=new['seconds'], legacy_seconds=old['seconds'],
            legacy_interrupted_at_2s=old['interrupted_at_2s'],
            candidate_handler_reads=reads, legacy_handler_reads=old['handler_read_deltas']))
sources = [json.loads((directory/f'source-{place}.json').read_text(encoding='utf-8-sig')) for place in ['local', 'tracker']]
assert sources[0] == sources[1], 'Fontes executados diferem do checkout'
summary = dict(status='passed', cases=6, opens=18, source_fingerprint=sources[0]['fingerprint'], results=results,
    limits=['controle antigo com indice adverso forcado, nao baseline tipico',
            'Handler_read_* mede operacoes de acesso; nao equivale a ROWS_EXAMINED',
            'sem ANALYZE corretivo; estatisticas automaticas do MySQL preservadas',
            'ensaio de inicializacao; nao mede throughput nem seis horas'])
(directory/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
paths = sorted(p for p in directory.iterdir() if p.is_file() and p.name != 'manifest.json')
manifest = dict(algorithm='sha256', files=len(paths), bytes=sum(p.stat().st_size for p in paths),
    sha256={p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
(directory/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps(summary, indent=2))
