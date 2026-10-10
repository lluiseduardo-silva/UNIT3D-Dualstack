#!/usr/bin/env python3
"""Espera limitada pelo listener nas duas familias, sem emitir announces."""
import json
import socket
import time

assert socket.gethostname() == 'unit3d-ds-clients'
started = time.monotonic()
deadline = started + 180
targets = ['172.29.92.10', 'fd42:756e:6974:92::10']
while time.monotonic() < deadline:
    try:
        for target in targets:
            with socket.create_connection((target, 8080), timeout=1):
                pass
    except OSError:
        time.sleep(.25)
    else:
        print(json.dumps(dict(status='ready', families=[4, 6], waited_seconds=time.monotonic()-started)))
        break
else:
    print(json.dumps(dict(status='readiness_timeout', seconds=180)))
    raise SystemExit(1)
