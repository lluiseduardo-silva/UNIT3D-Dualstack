#!/usr/bin/env bash
set -euo pipefail
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
test "$(hostname)" = unit3d-ds-tracker
mode=${1:?Informe php ou rust}
case "$mode" in php|rust) ;; *) exit 2;; esac
for name in unit3d-ds-php unit3d-ds-worker unit3d-ds-flush unit3d-ds-nginx unit3d-ds-rust; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Container $name existente; encerre e drene o baseline anterior antes de continuar." >&2
        exit 1
    fi
done
if test "$mode" = php; then
    docker run -d --name unit3d-ds-php --network host \
        -v "$base/repos/UNIT3D:/app" \
        -v "$base/lab/php-fpm.conf:/usr/local/etc/php-fpm.d/zz-lab.conf:ro" \
        unit3d-ds-php:baseline
    docker run -d --name unit3d-ds-worker --network host \
        -v "$base/repos/UNIT3D:/app" unit3d-ds-php:baseline \
        php artisan queue:work --sleep=1 --tries=3 --timeout=90
    docker run -d --name unit3d-ds-flush --network host \
        -v "$base/repos/UNIT3D:/app" -v "$base/lab:/lab:ro" \
        unit3d-ds-php:baseline php /lab/flush-baseline.php
else
    docker run -d --name unit3d-ds-rust --network host \
        -v "$base/repos/UNIT3D-Announce:/app" -w /app \
        "$RUST_IMAGE" /app/target/release/unit3d-announce
fi
docker run -d --name unit3d-ds-nginx --network host \
    -v "$base/lab/nginx.conf:/etc/nginx/nginx.conf:ro" "$NGINX_IMAGE"
