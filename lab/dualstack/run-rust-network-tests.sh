#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
docker run --rm -e SQLX_OFFLINE=true -v "$base/repos/UNIT3D-Announce:/app" -v unit3d-ds-cargo:/usr/local/cargo/registry -w /app "$RUST_IMAGE" cargo test --locked --release --bin unit3d-announce
