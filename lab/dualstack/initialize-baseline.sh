#!/usr/bin/env bash
set -euo pipefail
base=/opt/unit3d-dualstack
test "$(hostname)" = unit3d-ds-tracker
mkdir -p "$base/private"
chmod 700 "$base/private"
# O FPM precisa ler o checkout; segredos ficam limitados a root e ao grupo do FPM.
chgrp -R 33 "$base/repos/UNIT3D"
chmod -R g+rX "$base/repos/UNIT3D"
chmod 640 "$base/repos/UNIT3D/.env"
chmod -R g+rwX "$base/repos/UNIT3D/storage" "$base/repos/UNIT3D/bootstrap/cache"
run_php() {
    docker run --rm --network host -v "$base/repos/UNIT3D:/app" \
        -v "$base/lab:/lab:ro" -v "$base/private:/private" unit3d-ds-php:baseline "$@"
}
run_php php artisan package:discover --no-ansi
run_php php artisan migrate --force --no-ansi
run_php php /lab/seed-baseline.php
chown lab:lab "$base/private/fixture.json"
chmod 711 "$base/private"
