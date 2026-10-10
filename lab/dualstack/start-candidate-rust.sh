#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
mode=${1:-resume}
profile=${2:-direct}
case "$mode" in fresh|resume) ;; *) echo 'Use fresh ou resume.' >&2; exit 2 ;; esac
case "$profile" in direct|proxy) ;; *) echo 'Use direct ou proxy.' >&2; exit 2 ;; esac
for name in unit3d-ds-php unit3d-ds-worker unit3d-ds-flush unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes de iniciar o ensaio Rust." >&2
        exit 1
    fi
done
if test "$mode" = fresh; then
    docker run --rm --network host -e APP_ENV=local -e DB_DATABASE=unit3d_dualstack_journal_test \
        -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" \
        unit3d-ds-php:baseline php /lab/initialize-journal-test.php
fi
# Deriva a configuracao privada sem imprimir credenciais ou muda-las no baseline.
python3 - "$profile" <<'PY'
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit
base = Path('/opt/unit3d-dualstack')
values = dict(line.split('=', 1) for line in (base/'repos/UNIT3D-Announce/.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
url = urlsplit(values['DATABASE_URL'])
values['DATABASE_URL'] = urlunsplit((url.scheme, url.netloc, '/unit3d_dualstack_journal_test', url.query, url.fragment))
values.update(LISTENING_IP_ADDRESS='::', LISTENING_PORT='8080', DUALSTACK_ENABLED='true',
    DUALSTACK_ALLOW_PRIVATE_ADDRESSES='true', DUALSTACK_TRUSTED_PROXIES='',
    ANNOUNCE_MIN_ENFORCED='0', IS_CONNECTIVITY_CHECK_ENABLED='false', REQUIRE_PEER_CONNECTIVITY='false',
    IS_ANNOUNCE_LOGGING_ENABLED='false',
    USER_RECEIVE_SEED_LIST_RATE_LIMITS='1=10000', USER_RECEIVE_LEECH_LIST_RATE_LIMITS='1=10000')
values.pop('LISTENING_UNIX_SOCKET', None)
if sys.argv[1] == 'proxy':
    values.update(LISTENING_IP_ADDRESS='127.0.0.1', LISTENING_PORT='6969',
        DUALSTACK_TRUSTED_PROXIES='127.0.0.1/32', IS_CONNECTIVITY_CHECK_ENABLED='true',
        REQUIRE_PEER_CONNECTIVITY='true', REVERSE_PROXY_CLIENT_IP_HEADER_NAME='X-Real-IP',
        DUALSTACK_CONNECTIVITY_CACHE_ENTRIES='16', DUALSTACK_CONNECTIVITY_CACHE_TTL='1')
target = base/'rust-candidate.env'
target.touch(mode=0o600, exist_ok=True)
target.write_text(''.join(k+'='+v+'\n' for k,v in values.items()))
target.chmod(0o600)
PY
docker run --rm --network host -e SQLX_OFFLINE=true \
    -v "$base/repos/UNIT3D-Announce:/app" -v unit3d-ds-cargo:/usr/local/cargo/registry \
    -w /app "$RUST_IMAGE" cargo build --locked --release
docker run -d --name unit3d-ds-rust --network host --stop-signal=SIGTERM --stop-timeout=180 \
    -v "$base/repos/UNIT3D-Announce:/app:ro" -v "$base/rust-candidate.env:/app/.env:ro" \
    -w /app "$RUST_IMAGE" ./target/release/unit3d-announce
if test "$profile" = proxy; then
    docker run -d --name unit3d-ds-nginx --network host \
        -v "$base/lab/nginx-rust.conf:/etc/nginx/nginx.conf:ro" "$NGINX_IMAGE"
fi
for attempt in $(seq 1 30); do
    if curl -fsS --max-time 1 http://172.29.92.10:8080/announce/health/ping >/dev/null; then
        echo 'Rust HTTP pronto nas duas familias.'
        exit 0
    fi
    sleep 1
done
echo 'Rust nao ficou pronto; consultar logs locais sem divulgar segredos.' >&2
exit 1
