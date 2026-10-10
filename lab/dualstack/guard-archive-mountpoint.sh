#!/usr/bin/env bash
# Impede que qualquer gerador crie resultados no SSD se o VirtioFS estiver ausente.
set -euo pipefail
role=${1:?tracker, data ou clients}
case "$role" in tracker|data|clients) ;; *) exit 2;; esac
[[ $EUID == 0 && $(hostname) == "unit3d-ds-$role" ]]
target=/mnt/unit3d-archive
[[ $(findmnt -n -o SOURCE --mountpoint "$target") == "unit3d-ds-$role" ]]
umount "$target"
trap 'mount "$target"' EXIT
[[ -z $(find "$target" -mindepth 1 -print -quit) ]]
chattr +i "$target"
if mkdir "$target/fallback-must-fail" 2>/dev/null; then
    rmdir "$target/fallback-must-fail"
    echo 'ERRO: destino aceita fallback no SSD' >&2
    exit 1
fi
mount "$target"
trap - EXIT
[[ $(cat "$target/.unit3d-archive") == "unit3d-ds-$role" ]]
printf '{"role":"%s","ssd_fallback_blocked":true,"remounted":true}\n' "$role"
