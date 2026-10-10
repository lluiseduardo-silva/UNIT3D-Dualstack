#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
action=${1:?Use start ou stop}
backend=${2:?Use php ou rust}
variant=${3:?Use original, legacy-fixed ou candidate}
legacy_flush=${4:-}
case "$legacy_flush" in ''|100|3000) ;; *) echo 'Intervalo legado de controle invalido.' >&2; exit 2 ;; esac
case "$action:$backend:$variant" in start:php:original|start:php:legacy-fixed|start:php:candidate|start:rust:original|start:rust:candidate|stop:php:original|stop:php:legacy-fixed|stop:php:candidate|stop:rust:original|stop:rust:candidate) ;; *) exit 2 ;; esac
source_dir="$base/repos"
test "$variant" = candidate || source_dir="$base/originals"
common=(--network host -e APP_ENV=local -e DB_DATABASE=unit3d_dualstack_journal_test
    -e DUALSTACK_TRACE_TRANSITIONS=false -e DUALSTACK_ENABLED=false
    -v "$source_dir/UNIT3D:/app" -v "$base/lab:/lab:ro")
if test "$variant" != candidate; then
    test "$(cat "$base/originals/php.commit")" = 8b88f4c8182eb3d3912ffef425c3224dcfd596f4
    test "$(cat "$base/originals/rust.commit")" = fcd189e9aebf07a12a1f8cc39500819c3870925b
    python3 - <<'PY'
from pathlib import Path
import hashlib, json, tomllib
base = Path('/opt/unit3d-dualstack')
digests = {}
for project, filename in [('UNIT3D', 'composer.lock'), ('UNIT3D-Announce', 'Cargo.lock')]:
    original = (base/'originals'/project/filename).read_text()
    candidate = (base/'repos'/project/filename).read_text()
    if filename == 'Cargo.lock':
        old, new = tomllib.loads(original), tomllib.loads(candidate)
        # A feature tornou direta uma dependencia ja travada transitivamente.
        # Nenhuma versao, checksum ou outro pacote pode mudar neste comparativo.
        root = next(p for p in new['package'] if p['name'] == 'unit3d-announce')
        root['dependencies'].remove('serde_json')
        assert old == new, 'Dependencias Rust alem da adicao direta de serde_json divergiram'
    else:
        assert original == candidate, 'Lockfiles divergentes: '+project
    digests[filename] = {'original': hashlib.sha256(original.encode()).hexdigest(),
                         'candidate': hashlib.sha256(candidate.encode()).hexdigest()}
print(json.dumps({'dependency_versions_verified': digests, 'rust_change': 'existing serde_json becomes direct'}))
PY
    common+=(-v "$base/repos/UNIT3D/vendor:/app/vendor:ro" -v "$base/repos/UNIT3D/.env:/app/.env:ro")
    if test "$variant" = legacy-fixed; then
        # Controle adicional: tag original com somente os dois consumidores corrigidos.
        for command in AutoUpsertPeers AutoUpsertHistories; do
            common+=(-v "$base/repos/UNIT3D/app/Console/Commands/$command.php:/app/app/Console/Commands/$command.php:ro")
        done
    fi
fi
if test "$action" = stop; then
    if test "$backend" = php && test "$variant" = candidate; then
        exec bash "$base/lab/stop-candidate-php.sh"
    fi
    for name in unit3d-ds-nginx unit3d-ds-php unit3d-ds-worker unit3d-ds-flush unit3d-ds-rust; do
        if docker container inspect "$name" >/dev/null 2>&1; then
            docker stop -t 180 "$name"
            code=$(docker inspect -f '{{.State.ExitCode}}' "$name")
            test "$code" = 0 || { echo "$name encerrou com codigo $code" >&2; exit 1; }
            docker rm "$name"
        fi
    done
    if test "$backend" = php; then
        docker run --rm "${common[@]}" unit3d-ds-php:baseline php artisan queue:work --stop-when-empty --tries=3 --timeout=90
        for command in auto:upsert_peers auto:upsert_histories auto:upsert_announces; do
            docker run --rm "${common[@]}" unit3d-ds-php:baseline php artisan "$command" --no-ansi
        done
    fi
    exit 0
fi
for name in unit3d-ds-nginx unit3d-ds-php unit3d-ds-worker unit3d-ds-flush unit3d-ds-rust unit3d-ds-coordinator unit3d-ds-legacy-rust; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes do benchmark." >&2; exit 1
    fi
done
# O cache e dedicado ao laboratorio. Reaquecer igualmente em cada versao.
docker run --rm "${common[@]}" unit3d-ds-php:baseline php artisan cache:clear --no-ansi
if test "$backend" = php; then
    if test "$variant" = candidate; then
        common+=(-e DUALSTACK_ENABLED=true -e DUALSTACK_ALLOW_PRIVATE_ADDRESSES=true)
        docker run -d --name unit3d-ds-coordinator --stop-signal=SIGTERM "${common[@]}" \
            unit3d-ds-php:baseline php artisan dualstack:work
    else
        docker run -d --name unit3d-ds-worker --stop-signal=SIGTERM "${common[@]}" unit3d-ds-php:baseline \
            php artisan queue:work --sleep=1 --tries=3 --timeout=90
        docker run -d --name unit3d-ds-flush --stop-signal=SIGTERM "${common[@]}" unit3d-ds-php:baseline php /lab/flush-baseline.php
    fi
    docker run -d --name unit3d-ds-php "${common[@]}" \
        -v "$base/lab/php-fpm.conf:/usr/local/etc/php-fpm.d/zz-lab.conf:ro" unit3d-ds-php:baseline
    docker run -d --name unit3d-ds-nginx --network host \
        -v "$base/lab/nginx.conf:/etc/nginx/nginx.conf:ro" "$NGINX_IMAGE"
else
    python3 - "$variant" "$legacy_flush" <<'PY'
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import sys
base = Path('/opt/unit3d-dualstack')
values = {key.strip(): value.strip() for line in (base/'repos/UNIT3D-Announce/.env').read_text().splitlines()
          if '=' in line and not line.lstrip().startswith('#') for key, value in [line.split('=', 1)]}
url = urlsplit(values['DATABASE_URL'])
values['DATABASE_URL'] = urlunsplit((url.scheme, url.netloc, '/unit3d_dualstack_journal_test', url.query, url.fragment))
values.update(LISTENING_IP_ADDRESS='::', LISTENING_PORT='8080', ANNOUNCE_MIN_ENFORCED='0',
    DUALSTACK_ENABLED='true' if sys.argv[1] == 'candidate' else 'false', DUALSTACK_ALLOW_PRIVATE_ADDRESSES='true',
    IS_CONNECTIVITY_CHECK_ENABLED='false', REQUIRE_PEER_CONNECTIVITY='false', IS_ANNOUNCE_LOGGING_ENABLED='false',
    USER_RECEIVE_SEED_LIST_RATE_LIMITS='1=10000', USER_RECEIVE_LEECH_LIST_RATE_LIMITS='1=10000', NUMWANT_MAX='25')
if sys.argv[2]:
    assert sys.argv[1] == 'original', 'Controle de flush exclusivo do Rust original'
    values['FLUSH_INTERVAL_MILLISECONDS'] = sys.argv[2]
values.pop('LISTENING_UNIX_SOCKET', None)
values.pop('REVERSE_PROXY_CLIENT_IP_HEADER_NAME', None)
target = base/'rust-benchmark.env'
target.touch(mode=0o600, exist_ok=True)
target.write_text(''.join(k+'='+v+'\n' for k,v in values.items()))
target.chmod(0o600)
PY
    docker run --rm --network host -e SQLX_OFFLINE=true -v "$source_dir/UNIT3D-Announce:/app" \
        -v unit3d-ds-cargo:/usr/local/cargo/registry -w /app "$RUST_IMAGE" cargo build --locked --release
    touch "$source_dir/UNIT3D-Announce/.env"
    docker run -d --name unit3d-ds-rust --network host --stop-signal=SIGTERM --stop-timeout=180 \
        -v "$source_dir/UNIT3D-Announce:/app:ro" -v "$base/rust-benchmark.env:/app/.env:ro" \
        -w /app "$RUST_IMAGE" ./target/release/unit3d-announce
fi
echo "Benchmark iniciado: $backend $variant; verificar readiness antes da carga."
