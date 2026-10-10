#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
mode=${1:-all}
case "$mode" in all|php) ;; *) echo 'Use all ou php.' >&2; exit 2 ;; esac
for name in unit3d-ds-php unit3d-ds-worker unit3d-ds-flush unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator unit3d-ds-legacy-rust; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre e drene $name antes do ensaio." >&2
        exit 1
    fi
done
php_lab() {
    docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
        -e DUALSTACK_JOURNAL_TESTS=1 -e DUALSTACK_TEST_BIND_IPV4=172.29.92.10 \
        -e DUALSTACK_TEST_BIND_IPV6=fd42:756e:6974:92::10 \
        -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" \
        unit3d-ds-php:baseline "$@"
}
php_lab php /lab/handoff-php.php preflight
php_lab php /lab/initialize-journal-test.php
php_lab vendor/bin/pest tests/Integration/DualstackLegacyTest.php tests/Integration/DualstackJournalTest.php --colors=never --stop-on-failure --fail-on-skipped
if test "$mode" = all; then
    php_lab php /lab/initialize-journal-test.php
    bash "$base/lab/run-rust-mysql.sh"
fi
echo DUALSTACK_LEGACY_RECONCILIATION_PASSED
