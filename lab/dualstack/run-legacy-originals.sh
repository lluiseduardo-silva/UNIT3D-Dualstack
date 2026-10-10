#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
phase=${1:?Use php, rust-start ou rust-finish}
case "$phase" in php|rust-start|rust-finish) ;; *) exit 2 ;; esac
if test "$phase" != rust-finish && docker container inspect unit3d-ds-legacy-rust >/dev/null 2>&1; then
    echo 'Encerre o Rust original antes de outra fase.' >&2
    exit 1
fi
for name in unit3d-ds-php unit3d-ds-worker unit3d-ds-flush unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre e drene $name antes do ensaio." >&2
        exit 1
    fi
done
php_lab() {
    docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
        -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" unit3d-ds-php:baseline "$@"
}
if test "$phase" = php; then
    test "$(cat "$base/originals/php.commit")" = 8b88f4c8182eb3d3912ffef425c3224dcfd596f4
    php_lab php /lab/legacy-new.php preflight
    php_lab php /lab/initialize-journal-test.php
    php_lab php /lab/legacy-new.php seed
    mkdir -p "$base/originals/UNIT3D/bootstrap/cache" "$base/originals/UNIT3D/storage/framework/"{cache,sessions,views} "$base/originals/UNIT3D/storage/logs"
    docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
        -v "$base/originals/UNIT3D:/app" -v "$base/repos/UNIT3D/vendor:/app/vendor:ro" \
        -v "$base/repos/UNIT3D/.env:/app/.env:ro" -v "$base/lab:/lab:ro" \
        unit3d-ds-php:baseline php /lab/legacy-php-original.php
    php_lab php /lab/legacy-new.php php-resume
    echo LEGACY_PHP_ROUNDTRIP_PASSED
elif test "$phase" = rust-start; then
    test "$(cat "$base/originals/rust.commit")" = fcd189e9aebf07a12a1f8cc39500819c3870925b
    php_lab php /lab/legacy-new.php rust-preflight
    python3 - <<'PY'
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
base = Path('/opt/unit3d-dualstack')
values = dict(line.split('=', 1) for line in (base/'repos/UNIT3D-Announce/.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
url = urlsplit(values['DATABASE_URL'])
values['DATABASE_URL'] = urlunsplit((url.scheme, url.netloc, '/unit3d_dualstack_journal_test', url.query, url.fragment))
values.update(LISTENING_IP_ADDRESS='::', LISTENING_PORT='8080', ANNOUNCE_MIN_ENFORCED='0',
    IS_CONNECTIVITY_CHECK_ENABLED='false', REQUIRE_PEER_CONNECTIVITY='false', IS_ANNOUNCE_LOGGING_ENABLED='false',
    USER_RECEIVE_SEED_LIST_RATE_LIMITS='1=10000', USER_RECEIVE_LEECH_LIST_RATE_LIMITS='1=10000')
values.pop('LISTENING_UNIX_SOCKET', None)
values.pop('REVERSE_PROXY_CLIENT_IP_HEADER_NAME', None)
target = base/'rust-legacy.env'
target.touch(mode=0o600, exist_ok=True)
target.write_text(''.join(k+'='+v+'\n' for k,v in values.items()))
target.chmod(0o600)
PY
    docker run --rm --network host -e SQLX_OFFLINE=true \
        -v "$base/originals/UNIT3D-Announce:/app" -v unit3d-ds-cargo:/usr/local/cargo/registry \
        -w /app "$RUST_IMAGE" cargo build --locked --release
    # git archive nao inclui .env; criar o mountpoint antes do bind somente leitura.
    touch "$base/originals/UNIT3D-Announce/.env"
    docker run -d --name unit3d-ds-legacy-rust --network host --stop-signal=SIGTERM --stop-timeout=180 \
        -v "$base/originals/UNIT3D-Announce:/app:ro" -v "$base/rust-legacy.env:/app/.env:ro" \
        -w /app "$RUST_IMAGE" ./target/release/unit3d-announce
    for attempt in $(seq 1 30); do
        if curl -fsS --max-time 1 http://172.29.92.10:8080/announce/health/ping >/dev/null; then
            echo 'PASS Rust 0.3.1 original iniciado; executar legacy-original-http.py na VM clientes'
            exit 0
        fi
        sleep 1
    done
    echo 'Rust original nao ficou pronto; consultar logs privados.' >&2
    exit 1
else
    docker stop -t 180 unit3d-ds-legacy-rust >/dev/null
    test "$(docker inspect -f '{{.State.ExitCode}}' unit3d-ds-legacy-rust)" = 0
    docker logs unit3d-ds-legacy-rust 2>&1 | grep -Fx 'Graceful shutdown succeeded'
    docker rm unit3d-ds-legacy-rust >/dev/null
    php_lab php /lab/legacy-new.php rust-reconcile
    docker run --rm --network host --env-file "$base/database.env" -e SQLX_OFFLINE=true -e DUALSTACK_LEGACY_TESTS=1 \
        -v "$base/repos/UNIT3D-Announce:/app" -v unit3d-ds-cargo:/usr/local/cargo/registry \
        -w /app "$RUST_IMAGE" cargo test --locked --release --test dualstack_legacy -- --include-ignored --nocapture
    echo LEGACY_RUST_ROUNDTRIP_PASSED
fi
