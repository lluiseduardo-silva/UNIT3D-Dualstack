#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-clients
state=/opt/unit3d-dualstack/refund-load-sources
case "${1:-add}" in
    add)
        test ! -e "$state" || { echo 'Lista existente: remova os aliases deste ensaio primeiro.' >&2; exit 1; }
        ip -4 addr show dev eth1 | grep -q '172.29.92.30/24'
        touch "$state"
        for number in $(seq 100 171); do
            ipv4="172.29.92.$number/32"
            ipv6="fd42:756e:6974:92::$number/128"
            # Only record addresses successfully added by this invocation.
            ip -4 addr add "$ipv4" dev eth1
            echo "4 $ipv4" >> "$state"
            ip -6 addr add "$ipv6" dev eth1 nodad
            echo "6 $ipv6" >> "$state"
        done
        echo '144 enderecos de laboratorio adicionados, 72 por perfil.'
        ;;
    remove)
        test -f "$state"
        while read -r family address; do
            case "$family:$address" in 4:172.29.92.1??/32|6:fd42:756e:6974:92::1??/128) ;; *) exit 1 ;; esac
            ip "-$family" addr del "$address" dev eth1
        done < "$state"
        rm "$state"
        echo 'Aliases deste ensaio removidos.'
        ;;
    *) exit 2 ;;
esac
