#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
test -z "$(docker ps -q --filter name=unit3d-ds-rust)"
python3 "$base/lab/prepare-memory-observer.py"
# Reutiliza apenas artefatos Cargo; nao duplica gigabytes de dependencias.
# O executavel original e restaurado mesmo se a compilacao falhar.
restore() { cp "$base/network-validation/product-unit3d-announce" "$base/repos/UNIT3D-Announce/target/release/unit3d-announce"; }
trap restore EXIT
docker run --rm -e SQLX_OFFLINE=true -e CARGO_TARGET_DIR=/build \
    -v "$base/experiments/network-memory:/app" -v "$base/repos/UNIT3D-Announce/target:/build" \
    -v unit3d-ds-cargo:/usr/local/cargo/registry -w /app "$RUST_IMAGE" cargo build --locked --release
mkdir -p "$base/experiments/network-memory/target/release"
cp "$base/repos/UNIT3D-Announce/target/release/unit3d-announce" "$base/experiments/network-memory/target/release/unit3d-announce"
sha256sum "$base/experiments/network-memory/target/release/unit3d-announce"
