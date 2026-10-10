#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
for name in unit3d-ds-php unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes do ensaio destrutivo de ciclo de limpeza." >&2
        exit 1
    fi
done
common=(--network host -e APP_ENV=local -e DB_DATABASE=unit3d_dualstack_journal_test -e DUALSTACK_ENABLED=true \
    -e DUALSTACK_ALLOW_PRIVATE_ADDRESSES=true -e CACHE_PREFIX=dualstack-cleanup-lifecycle \
    -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro")
php_lab() { docker run --rm "${common[@]}" unit3d-ds-php:baseline php "$@"; }
php_lab /lab/cleanup-lifecycle.php preflight
php_lab /lab/initialize-journal-test.php
php_lab /lab/cleanup-lifecycle.php pending
docker run --rm --network host --env-file "$base/database.env" -e SQLX_OFFLINE=true \
    -e DUALSTACK_HANDOFF_TESTS=1 -e DUALSTACK_HANDOFF_PHASE=pending \
    -v "$base/repos/UNIT3D-Announce:/app" -v unit3d-ds-cargo:/usr/local/cargo/registry \
    -w /app "$RUST_IMAGE" cargo test --locked --release --test dualstack_handoff -- --include-ignored --nocapture
php_lab artisan dualstack:work --once
php_lab /lab/cleanup-lifecycle.php verify-once
docker run -d --name unit3d-ds-coordinator --stop-signal=SIGTERM "${common[@]}" unit3d-ds-php:baseline php artisan dualstack:work >/dev/null
cleanup() { docker stop -t 130 unit3d-ds-coordinator >/dev/null; }
trap cleanup EXIT
php_lab /lab/cleanup-lifecycle.php live
docker stop -t 130 unit3d-ds-coordinator >/dev/null
code=$(docker inspect -f '{{.State.ExitCode}}' unit3d-ds-coordinator)
echo "Coordenador apos SIGTERM: exit=$code"
test "$code" = 0
docker rm unit3d-ds-coordinator >/dev/null
trap - EXIT
php_lab /lab/cleanup-lifecycle.php verify-stop
echo CLEANUP_LIFECYCLE_PASSED
