#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
for name in unit3d-ds-php unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator unit3d-ds-bon-rust-test; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes do ensaio BON/Rust." >&2; exit 1
    fi
done
docker run --rm -e SQLX_OFFLINE=true -v "$base/repos/UNIT3D-Announce:/app" \
    -v unit3d-ds-cargo:/usr/local/cargo/registry -w /app "$RUST_IMAGE" \
    cargo test --locked --release --test dualstack_bon --no-run
signals=$(mktemp -d /tmp/unit3d-bon-signals.XXXXXX)
trap 'docker rm -f unit3d-ds-bon-rust-test >/dev/null 2>&1 || true; rmdir "$signals" 2>/dev/null || true' EXIT
docker run -d --name unit3d-ds-bon-rust-test --network host --env-file "$base/database.env" \
    -e SQLX_OFFLINE=true -e DUALSTACK_BON_TESTS=1 -v "$base/repos/UNIT3D-Announce:/app" \
    -v unit3d-ds-cargo:/usr/local/cargo/registry -v "$signals:/signals" -w /app "$RUST_IMAGE" \
    cargo test --locked --release --test dualstack_bon -- --include-ignored --nocapture >/dev/null
set +e
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
    -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" -v "$signals:/signals" \
    unit3d-ds-php:baseline php /lab/bon-rust-consumer.php
php_exit=$?
rust_exit=$(docker wait unit3d-ds-bon-rust-test)
docker logs unit3d-ds-bon-rust-test
set -e
test "$php_exit" = 0
test "$rust_exit" = 0
# Sinais contem somente flags deste ensaio; preservar em caso de falha.
rm "$signals/prepared" "$signals/ready" "$signals/go" "$signals/rust-done"
