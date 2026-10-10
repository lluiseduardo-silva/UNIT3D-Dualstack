#!/usr/bin/env bash
set -euo pipefail
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
test "$(hostname)" = unit3d-ds-data
test -e /var/lib/cloud/unit3d-dualstack-ready
mkdir -p "$base/results"
umask 077
if ! test -s "$base/database.env"; then
    python3 - <<'PY'
import secrets
from pathlib import Path
Path('/opt/unit3d-dualstack/database.env').write_text(
    'MYSQL_ROOT_PASSWORD=' + secrets.token_hex(24) + '\n'
    'MYSQL_DATABASE=unit3d_baseline\nMYSQL_USER=unit3d_lab\n'
    'MYSQL_PASSWORD=' + secrets.token_hex(24) + '\n')
PY
fi
docker pull "$MYSQL_IMAGE"
docker pull "$REDIS_IMAGE"
docker run -d --name unit3d-ds-mysql --restart no \
    --env-file "$base/database.env" -p 172.29.92.20:3306:3306 \
    -v unit3d-ds-mysql:/var/lib/mysql "$MYSQL_IMAGE" \
    --transaction-isolation=REPEATABLE-READ --innodb-lock-wait-timeout=10
docker run -d --name unit3d-ds-redis --restart no \
    -p 172.29.92.20:6379:6379 -v unit3d-ds-redis:/data \
    "$REDIS_IMAGE" redis-server --appendonly yes
docker image inspect "$MYSQL_IMAGE" "$REDIS_IMAGE" --format '{{json .RepoDigests}}' > "$base/results/data-images.jsonl"
docker version --format '{{json .}}' > "$base/results/docker-version.json"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
