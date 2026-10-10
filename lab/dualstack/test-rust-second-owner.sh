#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
test "$(docker inspect --format '{{.State.Running}}' unit3d-ds-rust)" = true
set +e
timeout 15s docker run --rm --network host -v "$base/repos/UNIT3D-Announce:/app:ro" -v "$base/rust-candidate.env:/app/.env:ro" -w /app "$RUST_IMAGE" ./target/release/unit3d-announce > "$base/results/rust-http-second-owner.txt" 2>&1
status=$?
set -e
test "$status" = 1
grep -F 'Outro backend possui o swarm' "$base/results/rust-http-second-owner.txt" >/dev/null
echo 'PASS segundo processo recusado antes de servir HTTP'
