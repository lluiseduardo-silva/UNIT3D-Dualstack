#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
for name in unit3d-ds-php unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes de executar a suite destrutiva do banco de ensaio." >&2
        exit 1
    fi
done
# Credenciais somente no ambiente do container, nunca em argumentos ou resultados.
docker run --rm --network host --env-file "$base/database.env" -e SQLX_OFFLINE=true -e DUALSTACK_MYSQL_TESTS=1 \
    -v "$base/repos/UNIT3D-Announce:/app" -v unit3d-ds-cargo:/usr/local/cargo/registry \
    -w /app "$RUST_IMAGE" cargo test --locked --release --test dualstack_mysql -- --include-ignored --nocapture
