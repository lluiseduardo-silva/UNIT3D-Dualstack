#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
mode=${1:-resume}
case "$mode" in fresh|resume) ;; *) echo 'Use fresh ou resume.' >&2; exit 2 ;; esac
for name in unit3d-ds-php unit3d-ds-worker unit3d-ds-flush unit3d-ds-nginx unit3d-ds-rust unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Container $name existente; encerre o ensaio anterior antes de iniciar." >&2
        exit 1
    fi
done
common=(--network host -e APP_ENV=local -e DB_DATABASE=unit3d_dualstack_journal_test -e DUALSTACK_ENABLED=true -e DUALSTACK_ALLOW_PRIVATE_ADDRESSES=true -e DUALSTACK_TRACE_TRANSITIONS=true -v "$base/repos/UNIT3D:/app")
if test "$mode" = fresh; then
    docker run --rm "${common[@]}" -v "$base/lab:/lab:ro" unit3d-ds-php:baseline php /lab/initialize-journal-test.php
fi
docker run -d --name unit3d-ds-coordinator --stop-signal=SIGTERM "${common[@]}" unit3d-ds-php:baseline php artisan dualstack:work
docker run -d --name unit3d-ds-php "${common[@]}" \
    -v "$base/lab/php-fpm.conf:/usr/local/etc/php-fpm.d/zz-lab.conf:ro" unit3d-ds-php:baseline
docker run -d --name unit3d-ds-nginx --network host \
    -v "$base/lab/nginx.conf:/etc/nginx/nginx.conf:ro" "$NGINX_IMAGE"
