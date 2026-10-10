#!/usr/bin/env bash
set -euo pipefail
base=/opt/unit3d-dualstack
test "$(hostname)" = unit3d-ds-tracker
# Primeiro retirar a entrada; depois terminar os consumidores e realizar o flush final.
for name in unit3d-ds-nginx unit3d-ds-worker unit3d-ds-php unit3d-ds-flush unit3d-ds-rust; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        docker stop --timeout 60 "$name"
        docker inspect "$name" --format '{{.Name}} exit={{.State.ExitCode}}' >> "$base/results/stops.txt"
        docker rm "$name"
    fi
done
for command in auto:upsert_peers auto:upsert_histories auto:upsert_announces; do
    docker run --rm --network host -v "$base/repos/UNIT3D:/app" \
        unit3d-ds-php:baseline php artisan "$command" --no-ansi
done
