#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-data
docker exec -i unit3d-ds-mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot' <<'SQL'
CREATE DATABASE IF NOT EXISTS unit3d_dualstack_journal_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL ON unit3d_dualstack_journal_test.* TO 'unit3d_lab'@'%';
-- Leitura de INNODB_METRICS para o gate de contencao, somente neste MySQL isolado.
GRANT PROCESS ON *.* TO 'unit3d_lab'@'%';
SQL
