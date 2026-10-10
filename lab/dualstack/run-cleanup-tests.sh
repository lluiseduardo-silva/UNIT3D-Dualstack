#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
for name in unit3d-ds-php unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes do ensaio destrutivo no banco de testes." >&2
        exit 1
    fi
done
mapfile -t files < "$base/lab/cleanup-php-files.txt"
docker run --rm -v "$base/repos/UNIT3D:/app" unit3d-ds-php:baseline vendor/bin/pint "${files[@]}"
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
    -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" unit3d-ds-php:baseline php /lab/apply-cleanup-schema.php

docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
    -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" unit3d-ds-php:baseline php /lab/apply-removal-schema.php
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test -e DUALSTACK_JOURNAL_TESTS=1 \
    -e DUALSTACK_TEST_BIND_IPV4=172.29.92.10 -e DUALSTACK_TEST_BIND_IPV6=fd42:756e:6974:92::10 \
    -v "$base/repos/UNIT3D:/app" unit3d-ds-php:baseline \
    vendor/bin/pest tests/Integration/DualstackCleanupTest.php tests/Integration/DualstackJournalTest.php --colors=never --fail-on-skipped
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
    -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" unit3d-ds-php:baseline php /lab/check-site-writers.php
tar -cf "$base/results/php-cleanup-formatted.tar" -C "$base/repos/UNIT3D" "${files[@]}"
chmod 644 "$base/results/php-cleanup-formatted.tar"
