#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
for name in unit3d-ds-php unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes do contrato de historico." >&2; exit 1
    fi
done
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test -e DUALSTACK_HISTORY_TESTS=1 \
    -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" unit3d-ds-php:baseline \
    vendor/bin/pest tests/Integration/DualstackHistoryContractTest.php --colors=never --fail-on-skipped
docker run --rm --network host --env-file "$base/database.env" -e SQLX_OFFLINE=true -e DUALSTACK_HISTORY_TESTS=1 \
    -v "$base/repos/UNIT3D-Announce:/app" -v "$base/lab:/lab:ro" -v unit3d-ds-cargo:/usr/local/cargo/registry \
    -w /app "$RUST_IMAGE" cargo test --locked --release --test dualstack_history -- --include-ignored --nocapture
