# Núcleo dualstack — implementação em andamento

Base fixa: 0.3.1, commit `fcd189e9aebf07a12a1f8cc39500819c3870925b`.

`src/dualstack/peer.rs` contém a função pura de transição, exportada pela library.
Um peer possui dois slots privados de endpoint, um por família. O mesmo caminho
de código trata substituição, stop por origem, expiração, revisão de probe,
referência cumulativa, conclusão e reinício de sessão. Contadores financeiros
usam `u64`, intermediário `u128` para percentuais e strings decimais em JSON.
Os contadores retornados são a contribuição de um peer; totais do swarm precisam
ser agregados em um tipo mais largo.

O módulo ainda **não está conectado ao handler HTTP, stores ou filas da 0.3.1**.
Não existe configuração que habilite dualstack no binário neste checkpoint.
A integração precisa confirmar transição e enfileiramento na mesma seção de
sincronização, persistir referência e efeitos na mesma transação MySQL e aplicar
o controle compartilhado de proprietário/geração antes de liberar a entrada.

## Coordenador e persistência — codec corrigido e suíte MySQL aprovada

`coordinator.rs` acrescenta estado compartilhado, fila limitada e consumidor em
lotes. Referência, versões, limite de peers e reserva da fila são atualizados
na mesma seção de sincronização, sem I/O nela. `persistence.rs` acrescenta a
lease SQL com geração, bootstrap por streaming e transação que reúne peers,
endpoints, histórico, créditos e contadores. Os lotes permanecem na fila até a
confirmação do commit. `serde_json` passou de dependência de testes para produção,
mantendo a versão 1.0.149 e o lockfile.

O primeiro ensaio falhou na reentrega: `epoch` tentava ler `TIMESTAMP` como
`Option<NaiveDateTime>` (`DATETIME`). A correção usa `Option<DateTime<Utc>>`
para essas colunas e preserva `NaiveDateTime` para `completed_at`, que é DATETIME.
Não altera tipos SQL, lockfile ou regras de contabilidade.

Após a correção, a suíte passou no MySQL 8.0.46 / Rust 1.99.0: um teste de
integração com oito blocos sequenciais. Verifica crédito 200 na sequência
1.000/1.000/1.100/1.050/1.200, reentrega sem reaplicação, restart com dois
endpoints, recusa da geração antiga, stop parcial, limite da fila, rollback
integral, quatro threads com 401 transições e zero SQL durante `publish`,
expiração independente, três peers/seis endpoints e precisão em `u64::MAX`.

A regressão adicional persiste datas preenchidas de conclusão e probe, repete
o lote e recarrega o coordenador. Confirma igualdade dos endpoints e timestamps,
uma conclusão, crédito de upload/download 100/100 e seedtime 30 após continuar
a sessão. A data do probe não substitui o relógio contábil `swarm_updated_at`.

Também foram corrigidos dois problemas da preparação/asserção do teste: o
contador legado `seeders` é `INT` com sinal, e a injeção de falha passou a usar
um CHECK temporário no histórico. O teste exige a violação MySQL 3819 desse
CHECK antes de conferir o rollback; não aceita um erro arbitrário. Isso evita
as restrições de protocolo e privilégio global do CREATE TRIGGER com binlog,
sem ampliar permissões ou alterar a configuração do servidor.

Reprodução no laboratório, com as credenciais no ambiente e sem tracker ativo:

```sh
DUALSTACK_MYSQL_TESTS=1 SQLX_OFFLINE=true \
  cargo test --locked --release --test dualstack_mysql \
  -- --include-ignored --nocapture
```

O teste usa exclusivamente `unit3d_dualstack_journal_test` em `172.29.92.20` e
exige REPEATABLE-READ, lock wait de 10 s, `MYSQL_USER` e `MYSQL_PASSWORD`.
Ele limpa somente esse banco de ensaio. O script de coordenação
`lab/dualstack/run-rust-mysql.sh` verifica o hostname e recusa containers ativos.

Evidências no repositório de coordenação: `results/rust/mysql-timestamp-regression.txt`
e `results/rust/mysql-after-timestamp-fix.json`, sob `lab/dualstack/`.
O CHECK de ensaio é removido antes das asserções de rollback; o snapshot final
confirma sua ausência e a lease liberada. O script continua restrito ao laboratório.

**A etapa 4 permanece incompleta.** Faltam integracao HTTP,
probes, retenção, API/admin e integração HTTP. O bootstrap guarda metadados de
versão/conclusão dos históricos; seu custo de memória ainda precisa ser medido.
Não habilitar este componente no binário antes da integração e seus testes.

### Falhas, limites de espera e supervisão

Aquisição, renovação e liberação da lease têm timeout de 3 s; bootstrap, 120 s;
cada transação de persistência, 15 s; encerramento completo, 120 s. Um timeout
de aquisição com resultado de commit desconhecido pode exigir aguardar a lease
de 30 s expirar. Nunca forçar outra geração durante essa espera.

O retry usa `MySqlDatabaseError::number()` para deadlock 1213 e lock wait 1205,
além de I/O, aquisição de conexão e timeout de persistência. São três tentativas
no total, com pausas de 50/100 ms. A versão transacional protege a reentrega de
resultado de commit desconhecido. Erros permanentes não são repetidos. A falha
final fecha a entrada e preserva o backlog; `retry_count` e
`deadlock_retry_count` expõem os retries sem registrar payloads.

`Coordinator::run` renova a cada 5 s em uma future independente do escritor,
persiste lotes a cada 100 ms e verifica expiração a cada 60 s, continuando lotes
de expiração quando necessário. Falha do escritor ou da renovação encerra o
loop e fecha a entrada. O sinal de parada fecha a entrada e drena com renovação
ativa. O chamador precisa supervisionar essa future; ela ainda não foi ligada
ao lifecycle do binário HTTP.

A suíte real passou em 17 blocos: os oito anteriores e nove adicionais de
timeout, retry, deadlock e supervisão. O teste força locks de linhas, observa
esperas InnoDB e recebe o erro 1213 real; dois lock waits seguidos confirmam
crédito somente na terceira tentativa. O esgotamento mantém duas transições
pendentes e recusa publicação. Após 12 s o supervisor ainda aceita announces;
quando a renovação bloqueia, interrompe o escritor sem perder a fila. Drenagem
normal e posterior à remoção de falha confirmam crédito 100 exatamente uma vez.
Evidência: `lab/dualstack/results/rust/mysql-failures.txt` na coordenação.

### Troca de proprietário com o PHP

A migração UNIT3D `2026_10_08_000003_add_dualstack_handoff_state.php` acrescenta
`tracker_ownership.php_journal_drained`, inicialmente falso. Cada aquisição PHP
o reinicia. Ao liberar a lease, PHP fecha produtores e verifica journal/filas
legadas em uma operação Redis; só depois confirma drenagem no SQL da mesma
geração. Uma liberação antiga não pode certificar outra geração.

Rust recusa `Coordinator::open` com `PendingPhpJournal` se o último proprietário
era PHP e a drenagem não foi confirmada. A recusa não avança geração. Após crash
PHP, recuperar/drenar primeiro com PHP, mesmo quando sua lease já expirou.
Não editar o marcador manualmente. Isso não adiciona Redis ao runtime Rust.
Continuar exigindo pausa/drenagem de escritores legados durante a implantação.

O laboratório validou recusa com duas mensagens pendentes, recuperação PHP,
PHP → Rust → PHP → Rust, com dois endpoints restaurados e créditos acumulados
100/200/300. O stop IPv6 no PHP preservou IPv4 no restart Rust. Os ensaios usam
os coordenadores diretamente; não comprovam ainda troca pelo HTTP integrado.
Evidências: `lab/dualstack/results/rust/handoff-initial.txt` e
`mysql-after-handoff.json`; regressão PHP completa: 27 testes / 474 asserções,
sem skips em `lab/dualstack/results/journal/handoff-php-full.txt`.

### Seleção e resposta compacta

`response.rs` usa um índice de peers por torrent mantido junto das transições
e refeito no bootstrap. Calcula totais lógicos e por família antes de limitar
a lista, aplicando TTL e política de conectividade por endpoint. A seleção
exclui o próprio usuário, prioriza seeders quando solicitados e limita peers
lógicos; cada selecionado entrega ambos os endpoints elegíveis. As restrições
de lista não zeram as estatísticas. `numwant=0` retorna listas vazias com totais.

A codificação inclui `peers` e `peers6`, comprimentos em bytes, totais únicos e
campos ordenados. O laboratório confirmou payload de até 24 bytes por peer
dualstack selecionado, igualdade byte a byte do bencode, TTL independente sem
limpeza física, preservação do caminho conectável, índice após restart e zero
SQL durante seleção/codificação. A suíte passou nos 18 blocos, registrada em
`lab/dualstack/results/rust/mysql-response.txt`. Ainda é API de biblioteca;
não há handler HTTP usando esse fluxo neste checkpoint.

## Verificação do contrato

O repositório de coordenação guarda `lab/dualstack/fixtures/peer-v1.json`.
Executar com um caminho explícito; a aplicação não depende desse arquivo nem do
PHP em execução:

```sh
DUALSTACK_PEER_FIXTURES=/caminho/peer-v1.json \
DUALSTACK_CONTRACT_TRACE=/tmp/peer-contract-rust.json \
SQLX_OFFLINE=true cargo test --locked --release --test dualstack_contract \
  -- --include-ignored --nocapture
```

Sem `--include-ignored`, o teste que exige a fixture externa fica explicitamente
ignorado. Os demais testes de endereço, precisão e rotação executam normalmente.
O laboratório passou nos cinco testes, incluindo 12 casos / 51 operações da
fixture e 10 mil trocas de IPv6. A comparação com o PHP verificou os snapshots
completos, deltas, endpoints e quatro visões dos contadores após cada operação.
Isso valida o núcleo; não comprova persistência, concorrência, HTTP, uso de memória
sob carga ou performance do tracker Rust integrado.

`serde_json` foi inicialmente declarado como dependência de desenvolvimento na mesma versão
1.0.149 já presente no lockfile. Nenhuma dependência foi atualizada. O build
Rust 1.99.0 mantém o aviso preexistente de depreciação em `src/stats.rs:226`.
