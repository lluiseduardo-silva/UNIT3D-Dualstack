#!/usr/bin/env python3
"""Instrumentacao isolada do produto: nao altera politica, SQL ou cadencia."""
from pathlib import Path
import hashlib
import json
import shutil
import socket
import sys

BASE = Path('/opt/unit3d-dualstack')
assert socket.gethostname() == 'unit3d-ds-tracker'
source = BASE/'repos/UNIT3D-Announce'
label,expected=sys.argv[1:]
assert label in ('writer-cadence','writer-endpoints')
target = BASE/'experiments'/label
files=sorted((source/'src').rglob('*.rs'))+[source/'Cargo.toml',source/'Cargo.lock']
reference={p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in files}
fingerprint=hashlib.sha256(json.dumps(reference,sort_keys=True,separators=(',',':')).encode()).hexdigest()
assert fingerprint==expected, 'Base Rust diferente do checkpoint'
assert not (target/'lab-source.json').exists(), 'Copia concluida; nao sobrescrever'
assert not target.exists(), 'Diretorio existente; nao sobrescrever'
shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git', 'target', '.env'))
# Compartilhar apenas o cache de compilacao, preservando o binario de referencia.
if not (target/'target').exists():
    shutil.copytree(source/'target', target/'target', copy_function=shutil.copy2)
changes = []


def edit(name, old, new):
    path = target/'src/dualstack'/name
    text = path.read_text()
    assert text.count(old) == 1, (name, old[:70], text.count(old))
    path.write_text(text.replace(old, new))
    changes.append(name)


shutil.copyfile(BASE/'lab/throughput-metrics.rs', target/'src/dualstack/lab_metrics.rs')
edit('mod.rs', 'pub mod peer;', 'pub(crate) mod lab_metrics;\npub mod peer;')
edit('coordinator.rs', '        let mut swarm = self.state.lock();\n        if (!swarm.ready', '''        let wait = super::lab_metrics::Span::new(0);
        let mut swarm = self.state.lock();
        drop(wait);
        let _held = super::lab_metrics::Span::new(1);
        if (!swarm.ready''')
edit('response.rs', '        let state = self.state.lock();', '''        let wait = super::lab_metrics::Span::new(2);
        let state = self.state.lock();
        drop(wait);
        let _held = super::lab_metrics::Span::new(3);''')
edit('coordinator.rs', '                    return Ok(batch.len());', '''                    super::lab_metrics::committed(batch.len());
                    return Ok(batch.len());''')
edit('coordinator.rs', '        let worker = async {', '''        let metrics = async {
            let mut timer=tokio::time::interval(Duration::from_secs(1));
            loop { timer.tick().await; super::lab_metrics::emit(self.backlog(), self.retry_count()); }
            #[allow(unreachable_code)] Ok::<(),Error>(())
        };
        let worker = async {''')
edit('coordinator.rs', '            result=worker => result,', '            result=worker => result,\n            result=metrics => result,')
edit('persistence.rs', '    tokio::time::timeout(Duration::from_secs(15), persist_inner', '    let _elapsed=super::lab_metrics::Span::new(4);\n    tokio::time::timeout(Duration::from_secs(15), persist_inner')
edit('persistence.rs', '    let identities: BTreeSet<_> = ordered.iter().map(|c| c.identity).collect();\n    let mut tx = pool.begin().await?;\n    lease.fence', '    let identities: BTreeSet<_> = ordered.iter().map(|c| c.identity).collect();\n    let elapsed=super::lab_metrics::Span::new(5);\n    let mut tx = pool.begin().await?;\n    drop(elapsed);\n    let elapsed=super::lab_metrics::Span::new(6);\n    lease.fence')
edit('persistence.rs', '    let mut final_peers = BTreeMap::new();', '    drop(elapsed);\n    let elapsed=super::lab_metrics::Span::new(7);\n    let mut final_peers = BTreeMap::new();')
edit('persistence.rs', '    if applied == 0 { tx.commit().await?; return Ok(0); }', '    drop(elapsed);\n    if applied == 0 { tx.commit().await?; return Ok(0); }\n    let elapsed=super::lab_metrics::Span::new(8);')
endpoint_marker = '    // Persistir somente familias alteradas nas transicoes ainda nao confirmadas.' if label=='writer-endpoints' else '    let mut q = QueryBuilder::<MySql>::new("DELETE FROM peer_ips WHERE (user_id,torrent_id,peer_id) IN (");'
edit('persistence.rs', endpoint_marker, '    drop(elapsed);\n    let elapsed=super::lab_metrics::Span::new(9);\n'+endpoint_marker)
edit('persistence.rs', '    let mut q = QueryBuilder::<MySql>::new("INSERT INTO history (user_id,torrent_id,agent,uploaded', '    drop(elapsed);\n    let elapsed=super::lab_metrics::Span::new(10);\n    let mut q = QueryBuilder::<MySql>::new("INSERT INTO history (user_id,torrent_id,agent,uploaded')
edit('persistence.rs', '    for (table, fields, deltas) in [', '    drop(elapsed);\n    let elapsed=super::lab_metrics::Span::new(11);\n    for (table, fields, deltas) in [')
edit('persistence.rs', '    tx.commit().await?;\n    Ok(applied)', '    drop(elapsed);\n    let _elapsed=super::lab_metrics::Span::new(12);\n    tx.commit().await?;\n    Ok(applied)')
hashes = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in sorted((target/'src').rglob('*.rs'))}
(target/'lab-source.json').write_text(json.dumps(dict(base=fingerprint, label=label, changed=sorted(set(changes)), hashes=hashes), indent=2)+'\n')
print(json.dumps(dict(status='prepared', changed=sorted(set(changes)), files=len(hashes))))
