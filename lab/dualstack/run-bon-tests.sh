#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
mode=${1:-functional}
for name in unit3d-ds-php unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes do ensaio de BON." >&2; exit 1
    fi
done
common=(--rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test
    -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro")
case "$mode" in
    functional)
        docker run "${common[@]}" -e DUALSTACK_BON_TESTS=1 -e DUALSTACK_VIEW_TESTS=1 -e DUALSTACK_PREFERENCE_TESTS=1 \
            unit3d-ds-php:baseline vendor/bin/pest tests/Integration/DualstackBonConnectivityTest.php \
            tests/Integration/DualstackEndpointViewTest.php tests/Integration/DualstackPeerCountTest.php \
            tests/Integration/DualstackExternalTrackerTest.php --colors=never --fail-on-skipped
        docker run "${common[@]}" -e DUALSTACK_BON_ALLOCATION_TESTS=1 unit3d-ds-php:baseline \
            vendor/bin/pest tests/Integration/DualstackBonAllocationTest.php --colors=never --fail-on-skipped
        docker run "${common[@]}" -e DUALSTACK_HIGHSPEED_TESTS=1 unit3d-ds-php:baseline \
            vendor/bin/pest tests/Integration/DualstackHighspeedTest.php --colors=never --fail-on-skipped
        docker run "${common[@]}" unit3d-ds-php:baseline php artisan view:cache
        docker run "${common[@]}" unit3d-ds-php:baseline php /lab/check-site-consumers.php
        ;;
    contention|legacy-control)
        legacy=0
        if [ "$mode" = legacy-control ]; then legacy=1; fi
        docker run "${common[@]}" -e DUALSTACK_BON_TESTS=1 -e DUALSTACK_BON_CONTENTION_TESTS=1 \
            -e DUALSTACK_BON_LEGACY_CONTROL="$legacy" unit3d-ds-php:baseline \
            vendor/bin/pest tests/Integration/DualstackBonContentionTest.php --colors=never --fail-on-skipped
        ;;
    *) echo "Use functional, contention ou legacy-control." >&2; exit 2 ;;
esac
