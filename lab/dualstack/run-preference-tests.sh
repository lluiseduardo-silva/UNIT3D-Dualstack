#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
for name in unit3d-ds-php unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes de validar preferencias no banco de ensaio." >&2
        exit 1
    fi
done
mapfile -t files < "$base/lab/preference-php-files.txt"
docker run --rm -v "$base/repos/UNIT3D:/app" unit3d-ds-php:baseline vendor/bin/pint "${files[@]}"
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test -e DUALSTACK_PREFERENCE_TESTS=1 \
    -v "$base/repos/UNIT3D:/app" unit3d-ds-php:baseline \
    vendor/bin/pest tests/Integration/DualstackPeerCountTest.php tests/Integration/DualstackExternalTrackerTest.php --colors=never --fail-on-skipped
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
    -v "$base/repos/UNIT3D:/app" unit3d-ds-php:baseline php artisan view:cache
tar -cf "$base/results/php-preference-formatted.tar" -C "$base/repos/UNIT3D" "${files[@]}"
chmod 644 "$base/results/php-preference-formatted.tar"
