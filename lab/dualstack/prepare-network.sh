#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
directory="$base/network-validation"
mkdir -p "$directory/tls"
chmod 700 "$directory/tls"
if ! test -f "$directory/tls/server.crt"; then
    umask 077
    openssl req -x509 -newkey rsa:2048 -nodes -days 7 -subj /CN=UNIT3D-Lab-CA \
        -keyout "$directory/tls/ca.key" -out "$directory/tls/ca.crt" >/dev/null 2>&1
    openssl req -newkey rsa:2048 -nodes -subj /CN=tracker.lab \
        -keyout "$directory/tls/server.key" -out "$directory/tls/server.csr" >/dev/null 2>&1
    printf '%s\n' 'subjectAltName=DNS:tracker.lab,IP:172.29.92.10,IP:fd42:756e:6974:92::10' \
        'basicConstraints=CA:FALSE' 'keyUsage=digitalSignature,keyEncipherment' \
        'extendedKeyUsage=serverAuth' > "$directory/tls/server.ext"
    openssl x509 -req -in "$directory/tls/server.csr" -CA "$directory/tls/ca.crt" \
        -CAkey "$directory/tls/ca.key" -CAcreateserial -days 7 -extfile "$directory/tls/server.ext" \
        -out "$directory/tls/server.crt" >/dev/null 2>&1
fi
openssl verify -CAfile "$directory/tls/ca.crt" "$directory/tls/server.crt"
openssl x509 -in "$directory/tls/server.crt" -noout -fingerprint -sha256 -dates
cp "$base/repos/UNIT3D/config/announce.php" "$directory/announce-base.php"
cat > "$directory/announce.php" <<'PHP'
<?php
$config = require '/network/announce-base.php';
$config['connectable_check'] = true;
$config['connectable_check_interval'] = 3;
return $config;
PHP
chmod 644 "$directory/announce.php" "$directory/announce-base.php"
