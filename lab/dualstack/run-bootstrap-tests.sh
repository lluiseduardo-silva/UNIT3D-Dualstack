#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
for name in unit3d-ds-php unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes do teste de bootstrap." >&2; exit 1
    fi
done
negative=${1:-0}
case "$negative" in 0|1) ;; *) exit 2 ;; esac
docker run --rm --network host --env-file "$base/database.env" -e SQLX_OFFLINE=true \
    -e DUALSTACK_MYSQL_TESTS=1 -e DUALSTACK_EXPECT_ORPHAN="$negative" \
    -v "$base/repos/UNIT3D-Announce:/app" -v unit3d-ds-cargo:/usr/local/cargo/registry \
    -w /app "$RUST_IMAGE" cargo test --locked --release --test dualstack_bootstrap -- --include-ignored --nocapture
