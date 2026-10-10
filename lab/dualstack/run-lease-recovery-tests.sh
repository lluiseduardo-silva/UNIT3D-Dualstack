#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
test -d "$base/experiments/lease-recovery"
test -z "$(docker ps --format '{{.Names}}')"
case "${1:-}" in
  unit) args=(test --locked --release --lib --bins --test dualstack_contract -- --nocapture) ;;
  mysql) args=(test --locked --release --test dualstack_mysql -- --include-ignored --nocapture) ;;
  contract) args=(test --locked --release --test dualstack_contract -- --include-ignored --nocapture) ;;
  build) args=(build --locked --release) ;;
  *) exit 2 ;;
esac
docker run --rm --network host --env-file "$base/database.env" \
  -e SQLX_OFFLINE=true -e DUALSTACK_MYSQL_TESTS=1 \
  -e DUALSTACK_TEST_DATABASE=unit3d_dualstack_recovery_test \
  -e DUALSTACK_PEER_FIXTURES=/lab/fixtures/peer-v1.json \
  -v "$base/experiments/lease-recovery:/app" \
  -v unit3d-ds-cargo:/usr/local/cargo/registry -v "$base/lab:/lab:ro" \
  -w /app "$RUST_IMAGE" cargo "${args[@]}"
