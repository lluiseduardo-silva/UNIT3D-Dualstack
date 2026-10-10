#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
seconds=${1:?Duracao em segundos}
label=${2:?Identificador da captura}
[[ "$seconds" =~ ^[0-9]+$ && "$label" =~ ^[a-z0-9-]+$ ]]
test "$seconds" -ge 1 && test "$seconds" -le 60
umask 077
pid=$(docker inspect -f '{{.State.Pid}}' unit3d-ds-rust)
test "$pid" -gt 1
target="/opt/unit3d-dualstack/private/$label.perf.data"
test ! -e "$target"
# Pilhas podem conter dados privados: manter perf.data exclusivamente na VM.
perf record -q -e cpu-clock -F 997 --call-graph dwarf -p "$pid" -o "$target" -- sleep "$seconds"
perf report --stdio --no-children -g none --sort symbol --percent-limit 1 -i "$target"
