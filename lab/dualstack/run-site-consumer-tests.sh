#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
for name in unit3d-ds-php unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes do ensaio de consumidores." >&2; exit 1
    fi
done
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test -e DUALSTACK_CONSUMER_TESTS=1 \
    -v "$base/repos/UNIT3D:/app" unit3d-ds-php:baseline \
    vendor/bin/pest tests/Integration/DualstackSiteConsumersTest.php tests/Integration/DownloadRefundTest.php --colors=never --fail-on-skipped
