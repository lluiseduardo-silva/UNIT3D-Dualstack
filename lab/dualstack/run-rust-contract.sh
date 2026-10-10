#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
docker run --rm --network host -e SQLX_OFFLINE=true \
    -e DUALSTACK_PEER_FIXTURES=/lab/fixtures/peer-v1.json \
    -e DUALSTACK_CONTRACT_TRACE=/results/peer-contract-rust.json \
    -v "$base/repos/UNIT3D-Announce:/app" -v unit3d-ds-cargo:/usr/local/cargo/registry \
    -v "$base/lab:/lab:ro" -v "$base/results:/results" -w /app "$RUST_IMAGE" \
    cargo test --locked --release --test dualstack_contract -- --include-ignored --nocapture
docker run --rm -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" \
    unit3d-ds-php:baseline php /lab/export-peer-contract.php > "$base/results/peer-contract-php.json"
