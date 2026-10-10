#!/usr/bin/env python3
"""Identidade comparavel Windows/Linux dos fontes Rust e testes executados."""
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
paths = [root/'Cargo.toml', root/'Cargo.lock']
for directory in ['src', 'tests']:
    paths += sorted((root/directory).rglob('*.rs'))
hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in paths}
fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
print(json.dumps(dict(algorithm='sha256', normalization='LF', fingerprint=fingerprint, hashes=hashes), indent=2))
