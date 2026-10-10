#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-data
# Banco exclusivo dos ensaios de DDL. Nenhum banco original e removido.
docker exec -i unit3d-ds-mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot' <<'SQL'
CREATE DATABASE IF NOT EXISTS unit3d_dualstack_schema_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL ON unit3d_dualstack_schema_test.* TO 'unit3d_lab'@'%';
SQL
