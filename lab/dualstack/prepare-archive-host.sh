#!/usr/bin/env bash
set -euo pipefail
[[ $(hostname) == proxmox && $EUID == 0 ]]
test -x /usr/libexec/virtiofsd
base=storage_pool/unit3d-dualstack
backup=/root/unit3d-dualstack-storage-before
mkdir -p -m 700 "$backup"
# All guests must be stopped by the operator after draining their services.
for id in 120 121 122; do
    qm config "$id" | grep -q 'tags:.*dualstack.*lab.*unit3d'
    [[ $(qm status "$id") == 'status: stopped' ]]
    test -e "$backup/$id.conf" || cp "/etc/pve/qemu-server/$id.conf" "$backup/$id.conf"
done
if ! zfs list "$base" >/dev/null 2>&1; then
    zfs create -o quota=300G -o reservation=300G -o compression=lz4 \
        -o atime=off -o sync=standard -o exec=off -o setuid=off -o devices=off "$base"
fi
[[ $(zfs get -H -p -o value quota "$base") == 322122547200 ]]
[[ $(zfs get -H -p -o value reservation "$base") == 322122547200 ]]
chmod 700 "/$base"
for spec in 120:tracker 121:data 122:clients; do
    id=${spec%:*}; role=${spec#*:}; tag=unit3d-ds-$role
    zfs list "$base/$role" >/dev/null 2>&1 || zfs create "$base/$role"
    chmod 700 "/$base/$role"
    printf '%s\n' "$tag" >"/$base/$role/.unit3d-archive"
    if ! pvesh get "/cluster/mapping/dir/$tag" --output-format json >/dev/null 2>&1; then
        pvesh create /cluster/mapping/dir --id "$tag" \
            --map "node=proxmox,path=/$base/$role" \
            --description "Arquivo exclusivo do laboratorio UNIT3D VM $id"
    fi
    pvesh get "/cluster/mapping/dir/$tag" --output-format json |
        python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["map"] == ["node=proxmox,path="+sys.argv[1]],d' "/$base/$role"
    current=$(qm config "$id" | sed -n 's/^virtiofs0: //p')
    [[ -z $current || $current == "dirid=$tag,cache=auto" || $current == "$tag,cache=auto" ]]
    qm set "$id" --virtiofs0 "dirid=$tag,cache=auto"
done
zfs list -p -r "$base"
