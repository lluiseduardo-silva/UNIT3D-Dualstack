#!/usr/bin/env bash
set -euo pipefail
role=${1:?tracker, data ou clients}
case "$role" in tracker|data|clients) ;; *) exit 2;; esac
[[ $EUID == 0 && $(hostname) == "unit3d-ds-$role" ]]
tag=unit3d-ds-$role
target=/mnt/unit3d-archive
modprobe virtiofs
mkdir -p -m 700 "$target"
test -e /etc/fstab.unit3d-storage-before || cp /etc/fstab /etc/fstab.unit3d-storage-before
line="$tag $target virtiofs defaults,nosuid,nodev,noexec,nofail 0 0"
if grep -q ' /mnt/unit3d-archive ' /etc/fstab; then
    grep -Fxq "$line" /etc/fstab
else
    printf '\n%s\n' "$line" >>/etc/fstab
fi
systemctl daemon-reload
mountpoint -q "$target" || mount "$target"
[[ $(findmnt -n -o SOURCE --mountpoint "$target") == "$tag" ]]
[[ $(findmnt -n -o FSTYPE --mountpoint "$target") == virtiofs ]]
[[ $(cat "$target/.unit3d-archive") == "$tag" ]]
mkdir -p -m 700 "$target/results"
python3 - "$target" <<'PY'
import hashlib,json,os,pathlib,sys
p=pathlib.Path(sys.argv[1]); data=os.urandom(1048576)
f=p/'mount-probe.bin'
with f.open('wb') as out:
    out.write(data);out.flush();os.fsync(out.fileno())
fd=os.open(p,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
assert f.read_bytes()==data
print(json.dumps({'mount':str(p),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'fsync':True}))
PY
findmnt --mountpoint "$target"
