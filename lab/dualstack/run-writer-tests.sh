#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
for name in unit3d-ds-php unit3d-ds-nginx unit3d-ds-rust unit3d-ds-worker unit3d-ds-flush unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes da suite do escritor." >&2; exit 1
    fi
done
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
    -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" unit3d-ds-php:baseline php /lab/initialize-journal-test.php
for test in run-rust-contract run-rust-mysql run-bon-rust-tests run-refund-rust-tests run-handoff run-deletion-tests run-rust-network-tests run-writer-config-tests; do
    bash "$base/lab/$test.sh"
done
echo DUALSTACK_WRITER_VALIDATION_PASSED
