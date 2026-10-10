#!/usr/bin/env bash
# Run only on the Proxmox node. access.pub must contain a PUBLIC SSH key.
set -euo pipefail
base=/root/unit3d-dualstack
mkdir -p "$base"
exec 9>"$base/provision.lock"
flock -n 9 || { echo 'Outro provisionamento deste laboratorio esta em andamento.' >&2; exit 1; }
test -s "$base/access.pub"
test -s "$base/manifest.json"
command -v qm >/dev/null
test -c /dev/kvm

# Never adopt an existing VM, CT or bridge from another project.
for id in 120 121 122; do
    test ! -e "/etc/pve/qemu-server/$id.conf" || { echo "VM $id ja existe; interrompido." >&2; exit 1; }
    test ! -e "/etc/pve/lxc/$id.conf" || { echo "CT $id ja existe; interrompido." >&2; exit 1; }
done
if ip link show vmbr92 >/dev/null 2>&1; then
    test "$(cat /sys/class/net/vmbr92/ifalias)" = unit3d-dualstack || { echo 'vmbr92 pertence a outro projeto.' >&2; exit 1; }
fi
python3 - <<'PY'
import json, subprocess
resources = json.loads(subprocess.check_output(['pvesh', 'get', '/nodes/proxmox/status', '--output-format', 'json']))
available = int(next(line.split()[1] for line in open('/proc/meminfo') if line.startswith('MemAvailable:'))) * 1024
assert available >= 28 * 1024**3, 'Menos de 28 GiB disponiveis; nao provisionar.'
assert resources['cpuinfo']['cpus'] >= 12, 'Menos de 12 CPUs; nao provisionar.'
storage = json.loads(subprocess.check_output(['pvesh', 'get', '/nodes/proxmox/storage/local-lvm/status', '--output-format', 'json']))
assert storage['avail'] >= 58 * 1024**3, 'Menos de 58 GiB disponiveis no storage; nao provisionar.'
PY

image=noble-server-cloudimg-amd64.img
if ! test -f "$base/image-verified"; then
    curl --fail --location --connect-timeout 15 --max-time 120 -o "$base/SHA256SUMS" https://cloud-images.ubuntu.com/noble/current/SHA256SUMS
    curl --fail --location --connect-timeout 15 --max-time 900 -o "$base/$image" "https://cloud-images.ubuntu.com/noble/current/$image"
    (cd "$base" && grep " \*$image$" SHA256SUMS | sha256sum --check --status)
    sha256sum "$base/$image" > "$base/image-verified"
fi
sha256sum --check --status "$base/image-verified"

# Add only a disconnected bridge. No host address, uplink, forwarding or NAT.
if ! ip link show vmbr92 >/dev/null 2>&1; then
    ip link add vmbr92 type bridge
    ip link set vmbr92 alias unit3d-dualstack
fi
ip link set vmbr92 up

# Keep existing storage content types and only enable cloud-init snippets.
content=$(pvesh get /storage/local --output-format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["content"])')
printf '%s\n' "$content" > "$base/local-storage-content.before"
case ",$content," in
    *,snippets,*) ;;
    *) pvesm set local --content "$content,snippets" ;;
esac
mkdir -p /var/lib/vz/snippets
python3 - <<'PY'
import json
from pathlib import Path
base = Path('/root/unit3d-dualstack')
key = (base / 'access.pub').read_text().strip()
assert key.startswith(('ssh-ed25519 ', 'ssh-rsa ', 'ecdsa-sha2-')), 'Chave publica invalida'
for vm in json.loads((base / 'manifest.json').read_text())['proxmox']['vms']:
    path = Path('/var/lib/vz/snippets') / f'unit3d-dualstack-{vm["id"]}.yaml'
    assert not path.exists(), f'Snippet ja existe: {path}'
    config = {
        'hostname': vm['name'], 'manage_etc_hosts': True,
        'ssh_pwauth': False, 'disable_root': True,
        'users': [{'name': 'lab', 'groups': 'sudo', 'shell': '/bin/bash', 'lock_passwd': True,
                   'sudo': ['ALL=(ALL) NOPASSWD:ALL'], 'ssh_authorized_keys': [key]}],
        'package_update': True,
        'packages': ['qemu-guest-agent', 'docker.io', 'git', 'python3', 'curl', 'ca-certificates'],
        'runcmd': [['systemctl', 'enable', '--now', 'qemu-guest-agent'],
                   ['systemctl', 'enable', '--now', 'docker'],
                   ['touch', '/var/lib/cloud/unit3d-dualstack-ready']],
    }
    path.write_text('#cloud-config\n' + json.dumps(config, indent=2) + '\n')
PY

for spec in '120 tracker 24 10' '121 data 16 20' '122 clients 12 30'; do
    read -r id role disk suffix <<< "$spec"
    qm create "$id" --name "unit3d-ds-$role" --cores 4 --memory 8192 --balloon 0 \
        --cpu host --ostype l26 --scsihw virtio-scsi-pci --agent enabled=1 \
        --net0 virtio,bridge=vmbr0 --net1 virtio,bridge=vmbr92 \
        --serial0 socket --vga serial0 --onboot 0 --tags 'unit3d;dualstack;lab' \
        --description 'Laboratorio UNIT3D dualstack. Proprietario: chat/worktree 2ca3. Nenhum dado de producao.'
    qm disk import "$id" "$base/$image" local-lvm >/dev/null
    qm set "$id" --scsi0 "local-lvm:vm-$id-disk-0,discard=on" \
        --ide2 local-lvm:cloudinit --boot order=scsi0 \
        --ipconfig0 ip=dhcp \
        --ipconfig1 "ip=172.29.92.$suffix/24,ip6=fd42:756e:6974:92::$suffix/64" \
        --cicustom "user=local:snippets/unit3d-dualstack-$id.yaml"
    qm disk resize "$id" scsi0 "${disk}G"
    qm start "$id"
done
qm list
