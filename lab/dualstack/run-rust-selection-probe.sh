#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
peers=${1:?Populacao esperada}
case "$peers" in 1000|54000|100000) ;; *) exit 2 ;; esac
for name in unit3d-ds-rust unit3d-ds-php unit3d-ds-coordinator; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Encerre $name antes do diagnostico." >&2; exit 1
    fi
done
placeholder="$base/repos/UNIT3D-Announce/examples/dualstack_selection_probe.rs"
test ! -e "$placeholder" || { echo 'O destino temporario do probe ja existe.' >&2; exit 1; }
# O bind aninhado pode deixar um arquivo vazio no checkout. Remover somente o
# placeholder criado nesta execucao, nunca um exemplo preexistente.
trap 'if test -f "$placeholder" && ! test -s "$placeholder"; then rm -- "$placeholder"; fi' EXIT
docker run --rm --network host --env-file "$base/database.env" -e SQLX_OFFLINE=true \
    -e DUALSTACK_SELECTION_PROBE=1 -e PROBE_EXPECTED_PEERS="$peers" \
    -v "$base/repos/UNIT3D-Announce:/app" \
    -v "$base/lab/rust-selection-probe.rs:/app/examples/dualstack_selection_probe.rs:ro" \
    -v unit3d-ds-cargo:/usr/local/cargo/registry -w /app "$RUST_IMAGE" \
    cargo run --locked --release --example dualstack_selection_probe
