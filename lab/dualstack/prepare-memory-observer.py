#!/usr/bin/env python3
"""Copia diagnostica Rust: amostra cardinalidade, sem alterar o produto."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

assert os.geteuid() == 0 and socket.gethostname() == 'unit3d-ds-tracker'
base = Path('/opt/unit3d-dualstack')
source = base/'repos/UNIT3D-Announce'
destination = base/'experiments/network-memory'
assert not destination.exists()
identity = json.loads(subprocess.check_output(['python3',str(base/'lab/bootstrap-source.py'),str(source)]))
assert identity['fingerprint'] == 'a0b448b667f756318200f17fda3e4fc6f2c3b75528c24a9ec9c0dfab80174659'
assert shutil.disk_usage(base).free > 2*1024**3
shutil.copytree(source,destination,ignore=shutil.ignore_patterns('.git','target','.env','*.log'))
(destination/'.env').touch(mode=0o600)
original_binary = source/'target/release/unit3d-announce'
saved_binary = base/'network-validation/product-unit3d-announce'
assert not saved_binary.exists()
shutil.copy2(original_binary,saved_binary)

path = destination/'src/dualstack_network.rs'
text = path.read_text()
marker = 'impl ProbeCache {\n'
assert text.count(marker) == 1
text = text.replace(marker, marker+'''    pub fn lab_memory_snapshot(&self) -> (usize, usize, usize) {
        let now = Instant::now();
        let cache = self.cache.lock();
        (cache.len(), cache.values().filter(|(expires, _)| *expires > now).count(),
            128 - self.slots.available_permits())
    }

''')
path.write_text(text)
path = destination/'src/main.rs'
text = path.read_text()
marker = '    let state = state::AppState::default().await?;\n'
assert text.count(marker) == 1
text = text.replace(marker,marker+'''    tokio::spawn({
        let state = state.clone();
        async move {
            loop {
                let (entries, live, in_flight) = state.dualstack_probes.lab_memory_snapshot();
                println!("LAB_MEMORY {}", serde_json::json!({
                    "at": std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64(),
                    "entries": entries, "live": live, "in_flight": in_flight
                }));
                tokio::time::sleep(std::time::Duration::from_secs(1)).await;
            }
        }
    });
''')
path.write_text(text)
observed = json.loads(subprocess.check_output(['python3',str(base/'lab/bootstrap-source.py'),str(destination)]))
changed = [name for name,value in observed['hashes'].items() if identity['hashes'].get(name) != value]
assert sorted(changed) == ['src/dualstack_network.rs','src/main.rs']
manifest = dict(product=identity['fingerprint'],observed=observed['fingerprint'],changed=changed,
    product_binary=hashlib.sha256(saved_binary.read_bytes()).hexdigest())
(base/'network-validation/observer-source.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest))
