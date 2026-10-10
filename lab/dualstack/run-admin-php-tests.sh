#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
files=(app/Services/Dualstack/ExternalTorrent.php app/Services/Unit3dAnnounce.php app/Http/Controllers/ExternalTorrentController.php tests/Integration/DualstackExternalTrackerTest.php)
docker run --rm -v "$base/repos/UNIT3D:/app" unit3d-ds-php:baseline vendor/bin/pint "${files[@]}"
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
    -v "$base/repos/UNIT3D:/app" unit3d-ds-php:baseline \
    vendor/bin/pest tests/Integration/DualstackExternalTrackerTest.php --colors=never --fail-on-skipped
tar -cf "$base/results/php-admin-formatted.tar" -C "$base/repos/UNIT3D" "${files[@]}"
chmod 644 "$base/results/php-admin-formatted.tar"
