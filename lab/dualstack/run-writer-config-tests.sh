#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
for name in unit3d-ds-rust unit3d-ds-php unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then exit 1; fi
done
temporary=$(mktemp -d /tmp/unit3d-writer-config.XXXXXX)
trap 'rm -f "$temporary/env" "$temporary/log"; rmdir "$temporary"' EXIT
for batch in 0 501 invalid; do
    python3 - "$base" "$temporary/env" "$batch" <<'PY'
from pathlib import Path
import sys
base,target,batch=sys.argv[1:]
text=(Path(base)/'repos/UNIT3D-Announce/.env').read_text()
lines=[line for line in text.splitlines() if not line.startswith(('DUALSTACK_ENABLED=','DUALSTACK_BATCH_SIZE='))]
Path(target).write_text('\n'.join(lines)+f'\nDUALSTACK_ENABLED=true\nDUALSTACK_BATCH_SIZE={batch}\n')
Path(target).chmod(0o600)
PY
    set +e
    timeout 10 docker run --rm --network host -v "$base/repos/UNIT3D-Announce:/app:ro" \
        -v "$temporary/env:/app/.env:ro" -w /app "$RUST_IMAGE" ./target/release/unit3d-announce > "$temporary/log" 2>&1
    code=$?
    set -e
    test "$code" != 0 && test "$code" != 124
    grep -q DUALSTACK_BATCH_SIZE "$temporary/log"
    echo "PASS DUALSTACK_BATCH_SIZE=$batch recusado na configuracao"
done
