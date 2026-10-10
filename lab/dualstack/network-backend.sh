#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
action=${1:?}; backend=${2:?}; profile=${3:-product}
case "$action:$backend:$profile" in start:php:product|stop:php:product|start:rust:product|stop:rust:product|start:rust:observed|stop:rust:observed) ;; *) exit 2 ;; esac
if test "$action" = stop; then
    if docker container inspect unit3d-ds-probe >/dev/null 2>&1; then
        docker stop -t 15 unit3d-ds-probe >/dev/null
        test "$(docker inspect -f '{{.State.ExitCode}}' unit3d-ds-probe)" = 0
        docker rm unit3d-ds-probe >/dev/null
    fi
    exec bash "$base/lab/benchmark-backend.sh" stop "$backend" candidate
fi
test -z "$(docker ps -aq)"
test "$(df -B1 --output=avail / | tail -1)" -gt 2147483648
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
    -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" unit3d-ds-php:baseline php /lab/initialize-journal-test.php
directory="$base/network-validation"
python3 - "$backend" <<'PY'
from pathlib import Path
import sys
base=Path('/opt/unit3d-dualstack')
inner='''server {
    listen 127.0.0.1:6969;
    location / {
        include /etc/nginx/fastcgi_params;
        fastcgi_param SCRIPT_FILENAME /app/public/index.php;
        fastcgi_param REMOTE_ADDR $remote_addr;
        fastcgi_pass 127.0.0.1:9000;
    }
}''' if sys.argv[1]=='php' else ''
text='''events { worker_connections 1024; }
http {
    log_format safe '$time_iso8601 $ssl_protocol $remote_addr $status $request_time';
    access_log /dev/stdout safe;
    error_log /dev/stderr crit;
    server {
        listen 172.29.92.10:8443 ssl;
        listen [fd42:756e:6974:92::10]:8443 ssl;
        server_name tracker.lab;
        ssl_certificate /tls/server.crt;
        ssl_certificate_key /tls/server.key;
        ssl_protocols TLSv1.2 TLSv1.3;
        location / {
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header Forwarded "";
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header Host $host;
            proxy_pass http://127.0.0.1:6969;
            proxy_connect_timeout 2s;
            proxy_read_timeout 5s;
        }
    }
INNER
}
'''
(base/'network-validation/nginx.conf').write_text(text.replace('INNER',inner))
PY
common=(--network host -e APP_ENV=local -e DB_DATABASE=unit3d_dualstack_journal_test \
    -e DUALSTACK_ENABLED=true -e DUALSTACK_ALLOW_PRIVATE_ADDRESSES=true -e DUALSTACK_TRACE_TRANSITIONS=false \
    -e DUALSTACK_TRUSTED_PROXIES=127.0.0.1/32 -e DUALSTACK_REQUIRE_CONNECTIVITY=true \
    -e DUALSTACK_CONNECTIVITY_CACHE_ENTRIES=16 -e DUALSTACK_CONNECTIVITY_CACHE_TTL=2 \
    -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" -v "$directory/announce-base.php:/network/announce-base.php:ro" \
    -v "$directory/announce.php:/app/config/announce.php:ro")
if test "$backend" = php; then
    docker run -d --name unit3d-ds-coordinator --stop-signal=SIGTERM "${common[@]}" unit3d-ds-php:baseline php artisan dualstack:work
    docker run -d --name unit3d-ds-php "${common[@]}" -v "$base/lab/php-fpm.conf:/usr/local/etc/php-fpm.d/zz-lab.conf:ro" unit3d-ds-php:baseline
    docker run -d --name unit3d-ds-probe --stop-signal=SIGTERM "${common[@]}" unit3d-ds-php:baseline php artisan dualstack:probe
else
    python3 - <<'PY'
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
base=Path('/opt/unit3d-dualstack')
values={k.strip():v.strip() for line in (base/'repos/UNIT3D-Announce/.env').read_text().splitlines() if '=' in line and not line.lstrip().startswith('#') for k,v in [line.split('=',1)]}
url=urlsplit(values['DATABASE_URL'])
values['DATABASE_URL']=urlunsplit((url.scheme,url.netloc,'/unit3d_dualstack_journal_test',url.query,url.fragment))
values.update(LISTENING_IP_ADDRESS='127.0.0.1',LISTENING_PORT='6969',DUALSTACK_ENABLED='true',
    DUALSTACK_ALLOW_PRIVATE_ADDRESSES='true',DUALSTACK_TRUSTED_PROXIES='127.0.0.1/32',
    REVERSE_PROXY_CLIENT_IP_HEADER_NAME='X-Real-IP',ANNOUNCE_MIN_ENFORCED='0',
    IS_CONNECTIVITY_CHECK_ENABLED='true',REQUIRE_PEER_CONNECTIVITY='true',IS_ANNOUNCE_LOGGING_ENABLED='false',
    DUALSTACK_CONNECTIVITY_CACHE_ENTRIES='16',DUALSTACK_CONNECTIVITY_CACHE_TTL='2',PEER_EXPIRY_INTERVAL='3',
    USER_RECEIVE_SEED_LIST_RATE_LIMITS='1=10000',USER_RECEIVE_LEECH_LIST_RATE_LIMITS='1=10000')
values.pop('LISTENING_UNIX_SOCKET',None)
target=base/'network-validation/rust.env'
target.touch(mode=0o600,exist_ok=True)
target.write_text(''.join(k+'='+v+'\n' for k,v in values.items()))
target.chmod(0o600)
PY
    source_dir="$base/repos/UNIT3D-Announce"
    test "$profile" = product || source_dir="$base/experiments/network-memory"
    if test "$profile" = product; then
        docker run --rm -e SQLX_OFFLINE=true -v "$source_dir:/app" -v unit3d-ds-cargo:/usr/local/cargo/registry -w /app "$RUST_IMAGE" cargo build --locked --release
    else
        test -x "$source_dir/target/release/unit3d-announce"
    fi
    docker run -d --name unit3d-ds-rust --network host --stop-signal=SIGTERM --stop-timeout=180 \
        -v "$source_dir:/app:ro" -v "$directory/rust.env:/app/.env:ro" -w /app "$RUST_IMAGE" ./target/release/unit3d-announce
fi
docker run --rm --network host -v "$directory/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$directory/tls:/tls:ro" "$NGINX_IMAGE" nginx -t
docker run -d --name unit3d-ds-nginx --network host -v "$directory/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$directory/tls:/tls:ro" "$NGINX_IMAGE"
for n in $(seq 1 30); do
    if curl --silent --output /dev/null --cacert "$directory/tls/ca.crt" --max-time 2 https://172.29.92.10:8443/announce/health/ping; then exit 0; fi
    sleep 1
done
exit 1
