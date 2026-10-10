#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
for name in unit3d-ds-php unit3d-ds-worker unit3d-ds-flush unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes do ensaio de handoff." >&2
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
rust_phase() {
    docker run --rm --network host --env-file "$base/database.env" -e SQLX_OFFLINE=true \
        -e DUALSTACK_HANDOFF_TESTS=1 -e DUALSTACK_HANDOFF_PHASE="$1" \
        -v "$base/repos/UNIT3D-Announce:/app" -v unit3d-ds-cargo:/usr/local/cargo/registry \
        -w /app "$RUST_IMAGE" cargo test --locked --release --test dualstack_handoff -- --include-ignored --nocapture
}
php_lab php /lab/handoff-php.php preflight
php_lab php /lab/apply-handoff-schema.php
php_lab php /lab/apply-cleanup-schema.php
php_lab php /lab/apply-removal-schema.php
php_lab php /lab/apply-legacy-schema.php
php_lab vendor/bin/pest tests/Integration/DualstackJournalTest.php --colors=never --stop-on-failure --fail-on-skipped
php_lab php /lab/initialize-journal-test.php
bash "$base/lab/run-rust-mysql.sh"
php_lab php /lab/initialize-journal-test.php
php_lab php /lab/handoff-php.php pending
rust_phase pending
php_lab php /lab/handoff-php.php drain
rust_phase resume
php_lab php /lab/handoff-php.php resume
rust_phase verify
echo DUALSTACK_HANDOFF_PASSED
