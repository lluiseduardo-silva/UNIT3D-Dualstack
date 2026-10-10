#!/usr/bin/env python3
"""Consolidacao final, preservando os limites de cada medicao."""
import hashlib
import json
from pathlib import Path

root=Path(__file__).parent/'results/throughput'
audits=[json.loads(p.read_text()) for p in sorted(root.glob('*-audit.json'))]
assert len(audits)==12 and all(a['status']=='passed' for a in audits)
for a in audits:
    for name,digest in a['sha256'].items():
        assert hashlib.sha256((root/a['series']/name).read_bytes()).hexdigest()==digest
before=json.loads((root/'state-before-restart.json').read_text(encoding='utf-8-sig'))
after=json.loads((root/'final-state.json').read_text(encoding='utf-8-sig'))
assert after['ownership']['generation']==before['ownership']['generation']+1
assert not after['ownership']['live'] and not after['active_test_queries']
assert not any(after['mismatches'].values())
for table in ['peers','history','users','peer_ips','locks','failed_jobs']:
    assert after[table]==before[table]
sources=json.loads((root/'sources-verified.json').read_text())
assert sources['status']=='passed'
matrix={
    'smoke-v1':('instrumented',200), 'ramp-v1':('instrumented',200),
    'reference-v1':('reference',200), 'unobserved-v1':('unobserved',200),
    'drain-v1':('drain',200), 'mixed-reference-v1':('instrumented',200),
    'mixed-drain-v1':('drain',200), 'mixed-batch500-v1':('drain',500),
    'fast-smoke-v1':('drain',500), 'fast-ramp-v1':('drain',500),
    'ceiling-v1':('drain',500), 'sustained-v1':('drain',500)
}
out=dict(status='passed',scope='levantamento e prototipos no laboratorio; produtos preservados',
    accepted=sum(a['accepted'] for a in audits),measured_samples=sum(a['measured_samples'] for a in audits),
    phases=sum(a['phases'] for a in audits),series=len(audits),
    experiments={k:dict(mode=v[0],batch=v[1]) for k,v in matrix.items()},
    validations=dict(accounting=True,response_contract=True,raw_sample_audit=True,
        source_identity=True,restart_preserves_confirmed_state=True),
    products=sources['products'],
    limits=['rampas curtas e um ensaio de 180 segundos; nao sao seis horas',
        'fixture de 250 usuarios, 40 torrents e 10000 peers; 100% dualstack',
        'HTTP direto, conexoes persistentes, probes e log de announces desativados',
        'teto do HTTP nao encontrado; limite observado foi a confirmacao assincrona',
        'nao isola SSD fisico de virtualizacao e outras cargas do host'])
(root/'summary.json').write_text(json.dumps(out,indent=2)+'\n')
checkpoint=dict(out,report='docs/dualstack-throughput.md',results='lab/dualstack/results/throughput',
    next='implementar gravador com drenagem limitada e lote configuravel; otimizar SQL antes de dividir mutexes')
(root.parent.parent/'checkpoint-throughput.json').write_text(json.dumps(checkpoint,indent=2)+'\n')
manifest={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file() and p.name!='manifest.json'}
(root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k in ['status','accepted','measured_samples','phases','series']}))
