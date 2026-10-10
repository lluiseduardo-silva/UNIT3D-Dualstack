#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
source "$base/lab/images.env"
original="$base/experiments/lease-recovery"
candidate="$base/experiments/statement-cache-b"
cache=/mnt/unit3d-archive/builds/statement-cache-b
test -z "$(docker ps --format '{{.Names}}')"
test "$(sha256sum "$original/target/release/unit3d-announce" | cut -d ' ' -f1)" = 25a9860c6caad0d78e2c3f8073f6ecd6822c05cbcd1b45773d0994a7df6d6833
case "${1:-}" in
  prepare)
    test ! -e "$candidate"
    test ! -e "$cache"
    test "$(df --output=avail -B1 /mnt/unit3d-archive | tail -1)" -gt 32212254720
    python3 - "$base/lab/capacity-cache-manifest.json" <<'PY'
import hashlib,json,sys
from pathlib import Path
m=json.loads(Path(sys.argv[1]).read_text())
assert hashlib.sha256(Path('/tmp/capacity-cache-source.tar.gz').read_bytes()).hexdigest()==m['source']['archive_sha256']
PY
    mkdir -p "$candidate" "$cache/target"
    tar -xzf /tmp/capacity-cache-source.tar.gz -C "$candidate"
    python3 - "$candidate" "$base/lab/capacity-cache-manifest.json" <<'PY'
import hashlib,json,sys
from pathlib import Path
base=Path(sys.argv[1]); manifest=json.loads(Path(sys.argv[2]).read_text())
p=base/'src/dualstack/persistence.rs'; raw=p.read_bytes()
assert not (base/'.env').exists()
assert hashlib.sha256(raw).hexdigest()==manifest['source']['persistence_a_sha256']
assert raw.count(b'q.build().')==8
changed=raw.replace(b'q.build().',b'q.build().persistent(false).')
assert hashlib.sha256(changed).hexdigest()==manifest['source']['persistence_b_sha256']
p.write_bytes(changed)
PY
    # Cache vazio para uma compilação reproduzível e independente do target A.
    ;;
  unit|contract|build)
    test -d "$candidate/src"
    test -d "$cache/target"
    # O arquivo de logs permanece noexec; somente este bind temporário executa
    # build scripts e proc macros, e é desmontado inclusive em caso de falha.
    mkdir -p "$candidate/build-cache"
    ! mountpoint -q "$candidate/build-cache"
    mount --bind "$cache/target" "$candidate/build-cache"
    trap 'umount "$candidate/build-cache"' EXIT
    mount -o remount,bind,exec,nosuid,nodev "$candidate/build-cache"
    if test "$1" = unit; then
      args=(test --locked --release --lib --bins --test dualstack_contract -- --nocapture)
    elif test "$1" = contract; then
      args=(test --locked --release --test dualstack_contract -- --include-ignored --nocapture)
    else
      args=(build --locked --release)
    fi
    docker run --rm --name unit3d-cache-build \
      -e SQLX_OFFLINE=true -e DUALSTACK_PEER_FIXTURES=/lab/fixtures/peer-v1.json \
      -v "$candidate:/app" -v "$candidate/build-cache:/app/target" \
      -v unit3d-ds-cargo:/usr/local/cargo/registry -v "$base/lab:/lab:ro" \
      -w /app "$RUST_IMAGE" cargo "${args[@]}"
    if test "$1" = build; then
      mkdir -p "$candidate/target/release"
      cp "$cache/target/release/unit3d-announce" "$candidate/target/release/unit3d-announce"
      # O bind de configuração precisa deste ponto já existente no diretório ro.
      if ! test -e "$candidate/.env"; then install -m 600 /dev/null "$candidate/.env"; fi
      test ! -s "$candidate/.env"
      sha256sum "$candidate/target/release/unit3d-announce"
    fi
    ;;
  *) exit 2 ;;
esac
test "$(sha256sum "$original/target/release/unit3d-announce" | cut -d ' ' -f1)" = 25a9860c6caad0d78e2c3f8073f6ecd6822c05cbcd1b45773d0994a7df6d6833
