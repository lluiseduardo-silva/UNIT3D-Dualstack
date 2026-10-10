#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-clients
ip -4 addr show dev eth1 | grep -q '172.29.92.30/24'
if ! ip -6 addr show dev eth1 | grep -q 'fd42:756e:6974:92::31/64'; then
    ip -6 addr add fd42:756e:6974:92::31/64 dev eth1
fi
