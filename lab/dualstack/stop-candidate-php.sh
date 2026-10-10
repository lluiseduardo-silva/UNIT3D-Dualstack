#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
# Fecha a entrada; SIGTERM solicita drenagem antes da liberacao da lease.
for name in unit3d-ds-nginx unit3d-ds-php unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        docker stop -t 130 "$name"
        code=$(docker inspect -f '{{.State.ExitCode}}' "$name")
        if test "$name" = unit3d-ds-coordinator && test "$code" != 0; then
            echo "Coordenador encerrou com codigo $code; journal pendente deve ser recuperado." >&2
            exit 1
        fi
        docker rm "$name"
    fi
done
