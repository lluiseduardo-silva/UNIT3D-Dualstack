#!/usr/bin/env bash
set -euo pipefail
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
test "$(hostname)" = unit3d-ds-tracker
test -e /var/lib/cloud/unit3d-dualstack-ready
test -s "$base/database.env"
umask 077
mkdir -p "$base/repos" "$base/results"
if ! test -d "$base/repos/UNIT3D/.git"; then
    git clone --branch v9.2.0 --single-branch https://github.com/HDInnovations/UNIT3D.git "$base/repos/UNIT3D"
fi
if ! test -d "$base/repos/UNIT3D-Announce/.git"; then
    git clone --branch v0.3.1 --single-branch https://github.com/Roardom/UNIT3D-Announce.git "$base/repos/UNIT3D-Announce"
fi
test "$(git -C "$base/repos/UNIT3D" rev-parse HEAD)" = 8b88f4c8182eb3d3912ffef425c3224dcfd596f4
test "$(git -C "$base/repos/UNIT3D-Announce" rev-parse HEAD)" = fcd189e9aebf07a12a1f8cc39500819c3870925b
docker build -f "$base/lab/Dockerfile.php" -t unit3d-ds-php:baseline "$base/lab"
docker pull "$NGINX_IMAGE"
docker pull "$RUST_IMAGE"
python3 - <<'PY'
import base64, secrets
from pathlib import Path
base = Path('/opt/unit3d-dualstack')
credentials = dict(line.split('=', 1) for line in (base / 'database.env').read_text().splitlines())
config = (base / 'repos/UNIT3D/.env.example').read_text()
values = {
    'APP_NAME': 'UNIT3D-dualstack-lab', 'APP_ENV': 'testing', 'APP_DEBUG': 'false',
    'APP_KEY': 'base64:' + base64.b64encode(secrets.token_bytes(32)).decode(),
    'APP_URL': 'http://172.29.92.10:8080',
    'DB_CONNECTION': 'mysql', 'DB_HOST': '172.29.92.20', 'DB_PORT': '3306',
    'DB_DATABASE': credentials['MYSQL_DATABASE'], 'DB_USERNAME': credentials['MYSQL_USER'],
    'DB_PASSWORD': credentials['MYSQL_PASSWORD'], 'REDIS_HOST': '172.29.92.20',
    'REDIS_PASSWORD': 'null', 'CACHE_STORE': 'redis', 'QUEUE_CONNECTION': 'redis',
    'SCOUT_DRIVER': 'null', 'MAIL_MAILER': 'log', 'BROADCAST_CONNECTION': 'log',
}
lines = [line for line in config.splitlines() if line.split('=', 1)[0] not in values]
lines.extend(f'{key}={value}' for key, value in values.items())
(base / 'repos/UNIT3D/.env').write_text('\n'.join(lines) + '\n')
config = (base / 'repos/UNIT3D-Announce/.env.example').read_text()
values = {
    'DATABASE_URL': 'mysql://' + credentials['MYSQL_USER'] + ':' + credentials['MYSQL_PASSWORD'] + '@172.29.92.20:3306/' + credentials['MYSQL_DATABASE'],
    'APIKEY': secrets.token_hex(24), 'LISTENING_IP_ADDRESS': '127.0.0.1', 'LISTENING_PORT': '6969',
    'REVERSE_PROXY_CLIENT_IP_HEADER_NAME': 'X-Real-IP',
}
lines = [line for line in config.splitlines() if line.split('=', 1)[0] not in values]
lines.extend(f'{key}={value}' for key, value in values.items())
(base / 'repos/UNIT3D-Announce/.env').write_text('\n'.join(lines) + '\n')
PY
docker run --rm --network host -v "$base/repos/UNIT3D:/app" unit3d-ds-php:baseline \
    composer install --no-interaction --prefer-dist --no-scripts --no-progress
docker image inspect unit3d-ds-php:baseline "$NGINX_IMAGE" "$RUST_IMAGE" --format '{{.Id}} {{json .RepoDigests}}' > "$base/results/tracker-images.txt"
docker run --rm unit3d-ds-php:baseline php --version > "$base/results/php-version.txt"
docker run --rm "$RUST_IMAGE" rustc --version > "$base/results/rust-version.txt"
docker run --rm --network host -v "$base/repos/UNIT3D-Announce:/app" -v unit3d-ds-cargo:/usr/local/cargo/registry \
    -w /app -e SQLX_OFFLINE=true "$RUST_IMAGE" cargo build --release --locked
printf 'Dependencias e binarios originais preparados. Proximo passo: schema e fixtures.\n'
