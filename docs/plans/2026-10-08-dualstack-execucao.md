# Execução do plano dualstack

Estado atual: **núcleo, persistência, HTTP, retenção e API administrativa Rust
validados; adaptador UNIT3D, preferência visual, resolução auto e contadores REST
integrados. Limpezas e exclusões coordenadas, telas locais e busca administrativa
validadas. Conectividade vigente no BON corrigida e validada funcionalmente.
Disputa de locks BON/gravadores corrigida e validada nos dois backends e no modo
legado. Histórico/seedtime aprovados no contrato compartilhado. Etapa 5 funcional
fechada; seedboxes, clientes do perfil e demais consumidores adaptados.
Falhas preexistentes em estatísticas de clientes e reembolso de múltiplos
torrents corrigidas; gate adicional aprovado, inclusive contenção nos dois
backends e ensaios HTTP curtos. Retorno às tags originais e reconciliação offline
validados. Clientes reais: oito cenários em cada backend, incluindo dualstack,
falha de cada família e conferência financeira após stopped: 16 aprovados.
Bloqueio Transmission → qBittorrent localizado no bind do libtorrent 2.0.10;
harness corrigido, causa e regressão comprovadas. Performance completa,
churn prolongado e janela de perda abrupta pendentes. A calibração encontrou
perda de registros na fila do PHP original; diagnóstico e correção localizada
dos consumidores legados comprovados sob carga. Calibração distribuída aprovada;
concentração Rust reprovada no limite de latência. Correção localizada reduziu
a regressão de aproximadamente 51% para 25–28%, ainda acima dos 10% aceitos.
Controle sem listas confirmou custo adicional de aproximadamente 24%.
Próxima alteração de maior impacto aguarda decisão baseada no diagnóstico.
BON por família fora da entrega**.
Atualização: 8 de outubro de 2026. Os pontos de parada anteriores abaixo são
históricos; a última retomada está registrada ao final do documento.

## Etapa 1 — preparação e diagnóstico funcional

- Repositórios independentes em `repos/UNIT3D` e `repos/UNIT3D-Announce`, nas
  duas revisões aprovadas. Branch `feat/dualstack` em ambos e na coordenação.
- VMs 120, 121 e 122 novas no Proxmox, com rede isolada IPv4/IPv6.
- PHP 8.4.26, Rust 1.99.0, MySQL 8.0.46 e Redis 7.2.16; digests registrados.
- Binário Rust original compilado com lockfile; Composer instalado com lockfile.
- Gerador determinístico, fixtures sintéticas e 12 passos reais por backend.
- Confirmados overwrite de endereço, reação ao segundo `started`, stop global
  e crédito final de 200 bytes em ambas as ordens de famílias.
- `verify-baseline.py` passou para PHP e Rust. Nenhum job falho no baseline.

Evidências e reprodução em `lab/dualstack/README.md` e
`lab/dualstack/results/baseline/`. Esses resultados são funcionais; não são
benchmark, validação concorrente ou transferência BitTorrent real.

## Etapa 2 — trabalho escrito e resultado

No UNIT3D foram acrescentados, no checkpoint `55e192ef76844c6377b611c312563343f774213b`:

- `config/dualstack.php`, desativado por padrão;
- migração aditiva com `peer_ips`, versão/sessão, contadores por família,
  preferências separadas e opções BON adicionais;
- `EndpointAddress`, com normalização de IPv4 mapeado e validação de origem;
- `dualstack:backfill --offline`, com lotes, retomada por identidade, preservação
  de endpoints já existentes e dos totais legados;
- teste de integração de schema contra MySQL real.

A migração foi aplicada no banco isolado `unit3d_baseline` em 742,14 ms.
O formatter do projeto foi executado nos cinco arquivos. A suíte foi executada
com a imagem PHP do baseline, em rede real com MySQL:

```sh
docker run --rm --network host -e DUALSTACK_MYSQL_TESTS=1 \
  -v /opt/unit3d-dualstack/repos/UNIT3D:/app unit3d-ds-php:baseline \
  vendor/bin/pest tests/Integration/DualstackSchemaTest.php --colors=never
```

Resultado: **1 failed, 7 passed (35 assertions)**. Log integral:
`lab/dualstack/results/schema/schema-tests.txt`.

```text
SQLSTATE[23000]: Integrity constraint violation: 1062
Duplicate entry 'excepturi' for key 'chat_statuses.chat_statuses_color_unique'
tests/Integration/DualstackSchemaTest.php:26
```

A falha aconteceu na criação do usuário pelo novo teste, antes da verificação
de FK/cascata. `User::factory()` também cria um ChatStatus; a unicidade de Faker
não garante ausência de colisão com dados já existentes no banco do laboratório.
A factory está em `database/factories/ChatStatusFactory.php:37`. Isso torna a
fixture do novo teste inadequada para esse banco; não demonstra defeito na FK.

Passaram: limite por família, duas famílias em um peer, três casos de constraints
família/tamanho, retomada de backfill sem sobrescrever endpoint/totais, endereço
mapeado e bloqueios de origem, separação entre `auto` e resolução.

Ainda não verificados nesta etapa: FK/cascata, reexecução da migração depois de
interrupção de DDL, backfill em escala e o contrato executável completo comum aos
dois backends. O schema não foi retirado depois da falha; é aditivo e permaneceu
somente no laboratório. Nenhuma rotina de announce usa as novas tabelas ainda.

## Ponto de retomada do primeiro checkpoint (resolvido abaixo)

Corrigir **a fixture do novo teste**, fornecendo ChatStatus determinístico ou
reutilizando um registro controlado, sem alterar a factory original global.
Reexecutar a verificação completa da etapa 2 e fechar seus critérios antes de
iniciar o processamento standalone. Na primeira execução, a correção não foi
aplicada, respeitando a instrução de parar quando uma verificação falhar.

Etapas 3–6 pendentes: contabilidade/fila atômica PHP, endpoints/persistência Rust,
integração/interface/BON, propriedade exclusiva, migração operacional, handoff e
rollback. Também pendentes matriz completa, clientes reais, carga e soak.

As VMs permanecem disponíveis. Os containers de announce, workers e proxy foram
encerrados; MySQL e Redis ficam no laboratório. Não houve alteração de produção,
push ou publicação. O checkout Rust permanece sem modificações.

## Checkpoint e retomada autorizada

O usuário autorizou continuar o desenvolvimento e solicitou commit do estado
atual, antes da correção da fixture. O commit do UNIT3D é
`55e192ef76844c6377b611c312563343f774213b`; ele preserva a falha conhecida acima.
O repositório de coordenação registra, em commit separado, laboratório, plano,
resultados e este documento. O Rust continua na revisão original
`fcd189e9aebf07a12a1f8cc39500819c3870925b`, sem commit vazio.

Commit de coordenação desse checkpoint: `8d71651a1795b784c06d16f6f7912d273c32183b`.

## Progresso após a retomada

A fixture foi corrigida no commit UNIT3D
`8952bc0fb9260704ac48ecc61c096217ad748d75`: o novo teste fornece um ChatStatus
controlado ao UserFactory, sem alterar a factory global. A suíte passou no mesmo
MySQL real: **8 testes, 38 assertions**, incluindo FK composta e cascata.
Log: `lab/dualstack/results/schema/schema-tests-resumed.txt`.

Em seguida foi criado o banco exclusivo `unit3d_dualstack_schema_test`, separado
do baseline, para verificar interrupções de DDL e retomada da migração. O ensaio
está em `lab/dualstack/validate-schema.php`; interrompe após instruções DDL e
reexecuta `up()` duas vezes. Também contém um ensaio de backfill de 54 mil linhas,
que **não chegou a ser executado**, pois a verificação anterior falhou.

### Nova falha confirmada

Quando a interrupção ocorre após `CREATE TABLE peer_ips`, antes dos comandos
adicionais de FK e índices, a retomada encontra a tabela existente e pula o bloco
`Schema::create`. Ela acrescenta os CHECKs, mas não recupera FK ou índices.
O bloco está em
`repos/UNIT3D/database/migrations/2026_10_08_000001_expand_dualstack_schema.php:25`.

O catálogo MySQL confirmou:

| Schema | Constraints de peer_ips | Índices |
|---|---|---|
| `unit3d_baseline`, migração normal | PK, FK composta, 2 CHECKs | PRIMARY, leitura por torrent/família, expiração |
| `unit3d_dualstack_schema_test`, retomada | PK e 2 CHECKs; **FK ausente** | **somente PRIMARY** |

Evidências: `lab/dualstack/results/schema/ddl-recovery-evidence.json` contém
`information_schema`, índices e `SHOW CREATE TABLE` dos dois bancos. O log do
ensaio é `schema-recovery-scale.txt`. O processo PHP com o handler Laravel
retornou código zero mesmo imprimindo a exceção; a validação foi considerada
**falha** pela assertion e pelo catálogo, não aprovada pelo exit code.

### Próxima ação e limites atuais

Corrigir a migração para garantir a presença da FK e de cada índice também
quando a tabela já existe. A verificação precisa igualmente emitir status/exit
de falha explícito, independente do handler de exceções da aplicação. Reexecutar
a suíte, as fronteiras de interrupção e o backfill antes de fechar a etapa 2.
Essas correções ainda não foram aplicadas, seguindo a parada exigida pelo plano.

Não foi iniciada a etapa 3. Nenhum processamento de announce ou contabilidade foi
alterado, e o Rust continua intacto na tag fixada. O schema incompleto existe
somente no banco separado de ensaio; o schema do baseline manteve FK e índices.
VMs e MySQL/Redis continuam disponíveis; serviços de announce estão parados.
Os commits são locais, sem push ou alterações de produção.

## Retomada de 8 de outubro — schema aprovado e núcleo PHP

A autorização para continuar permitiu corrigir a retomada de DDL. A migração
garante FK e cada índice independentemente da existência prévia de `peer_ips`.
Commit UNIT3D: `cf1f72406` (`database/migrations/2026_10_08_000001_expand_dualstack_schema.php`).

Verificações concluídas, no MySQL 8.0.46 real:

- Suíte de schema: **8 testes e 38 assertions** (`results/schema/schema-final.txt`).
- Interrupção após as instruções DDL 1, 4, 5, 6, 7, 9 e 14; duas retomadas em cada
  fronteira recuperaram PK, FK, dois CHECKs e índices.
- Backfill de **54.000 peers → 54.000 endpoints**, com lotes de 1.000 e 137.
  Os totais lógicos ficaram em 54.000; 27.000 por família. A repetição não duplicou
  registros. Tempos: 3,237 s e 6,500 s; pico do processo PHP: 109.576.192 bytes.
- Relatório completo: `lab/dualstack/results/schema/schema-recovery-fixed.txt`.
  Esses números medem schema/backfill; não são benchmark do processamento de announce.

O ensaio de schema agora retorna falha explícita mesmo com o handler Laravel.
Houve também uma correção no próprio gerador: identificadores SQL da fixture
precisam de crases porque `groups` é palavra reservada. Isso não alterou a feature.

### Contrato executável e persistência PHP

O contrato `lab/dualstack/fixtures/peer-v1.json` define 12 cenários e 51 operações,
com relógio controlado e contadores decimais exatos. O executor PHP passou em
**13 testes e 251 assertions**, incluindo precisão além de 2^53. Evidência:
`lab/dualstack/results/schema/peer-contract-php.txt`. A paridade Rust está pendente.

Os arquivos em `repos/UNIT3D/app/Services/Dualstack/` acrescentam:

- `Counter.php` e `PeerTransition.php`: referência única, endpoints limitados,
  substituição/stop/expiração por família e probe condicionado à revisão.
- `TransitionJournal.php` e `journal.lua`: comparação e troca atômica da referência
  e inclusão da transição no Redis Stream. Contadores não passam por floats Lua.
- `TransitionWriter.php`: lote transacional com peer, endpoints, histórico,
  contadores e crédito; versões impedem reaplicação e detectam lacunas.
- `TrackerLease.php`: proprietário PHP exclusivo, geração e bloqueio SQL contra
  escritores antigos. Heartbeat Redis de até 10 s; lease SQL de 30 s.
- `TrackerRecovery.php`: drenagem antes de carregar referências, reconstrução
  dos dois endpoints, reconciliação e expiração antes de liberar a entrada.

A segunda migração aditiva inclui metadados de protocolo, versão do histórico
e `tracker_ownership`. O Redis usado pelo journal exige `noeviction`; conexão e
leitura de announce têm timeout de 3 s configurável. Nada depende do Rust.

### Ensaios do journal

Banco separado: `unit3d_dualstack_journal_test`, sem alterar o baseline.
**9 testes, 126 assertions**, Redis 7.2.16 e MySQL 8.0.46, isolamento
REPEATABLE-READ e lock wait 10 s. Evidência:
`lab/dualstack/results/journal/journal-php-extended-metrics.txt`.

Cobertura executada:

- Sequência obrigatória 1.000/1.000/1.100/1.050/1.200: crédito 200, dois endpoints.
- Reentrega depois do commit e antes do ACK: reaplicação de crédito zero.
- Fila cheia: recusa sem avançar referência; contador acima de 2^53 preservado.
- Três peers dualstack: três unidades e seis endpoints; quarto recusado.
- Conclusão deduplicada e histórico preservado após stop parcial; seedtime único.
- Segundo proprietário recusado; escritor antigo impedido; restart restaura
  endpoints e referência confirmada sem reaplicar crédito.
- Quatro processos concorrentes, 41 transições aceitas, referência final 5.000,
  crédito 4.000 a partir de 1.000; nenhuma versão perdida.
- Falha injetada antes do commit: rollback integral; retry aplica o lote uma vez.
- Expiração de IPv4 depois do restart preserva IPv6 e o total lógico.
- Dois consumidores aplicando o mesmo lote em ordens diferentes: seis peers,
  crédito único e nenhuma variação em `lock_deadlocks`/`lock_timeouts`.

A primeira execução ampliada parou na instrumentação antes do último cenário:
`SHOW GLOBAL STATUS` não fornecia `Innodb_deadlocks` nesse MySQL. A coleta passou
a usar `information_schema.INNODB_METRICS`; `prepare-journal-test.sh` concede
PROCESS ao usuário exclusivo do laboratório para essa leitura. O log anterior
foi preservado em `journal-php-extended.txt`; não foi uma falha de contabilidade.

### Limites do checkpoint intermediário (antes da integração HTTP)

Este núcleo ainda **não está conectado ao HTTP**, ao scheduler ou aos jobs
legados. `DUALSTACK_ENABLED` permanece falso. A etapa 3 não está aprovada como
standalone completo. Ainda faltam integração do announce, seleção/resposta dos
peers, conectividade assíncrona limitada, desligamento dos escritores antigos,
retenção e os demais ensaios de falha. As etapas 4–6, interface/BON/preferências,
paridade Rust, clientes reais, carga, soak e rollback continuam pendentes.

As VMs permanecem disponíveis, com MySQL/Redis. Nenhuma implantação em produção,
push ou atualização das bases fixadas foi feita. O Rust segue inalterado.

## Checkpoint atual — announce PHP e manutenção integrados

Commits locais do UNIT3D, na branch `feat/dualstack`:

| Commit | Conteúdo |
|---|---|
| `cf1f724064665955b895bd03623ee166c66f5337` | Retomada de FK/índices depois de DDL interrompido |
| `646725e93f860b13f5e1cc0fa270aacd3161fba7` | Transições, journal, persistência, recuperação, resposta e testes |
| `fe9139a4132757e81880ebcc0c4145f19a133474` | Integração HTTP, coordenador, probes e suspensão dos escritores legados |

`AnnounceController` usa `StandaloneAnnounce` quando a feature está habilitada.
O novo fluxo mantém as validações existentes de usuário/grupo/torrent, aplica os
fatores de crédito uma vez e registra a transição antes da resposta. A lista usa
peers únicos elegíveis e carrega os endpoints em lote. Os parâmetros `ip`, `ipv4`
e `ipv6` não cadastram endereços; proxies precisam ser configurados explicitamente.

`dualstack:work` recupera o estado antes de abrir a entrada, persiste o journal,
expira cada família e retira peers inativos após a retenção de 172.800 s. A
retirada fecha a entrada temporariamente e drena as transições antes de apagar
qualquer referência. Os comandos antigos de peer/histórico ficam suspensos no
modo dualstack; jobs legados pendentes são recusados, exigindo drenagem prévia.

`dualstack:probe` verifica TCP fora do processamento HTTP e do coordenador.
O cache possui limite de entradas, expiração e proteção por revisão; uma falha
IPv6 preserva a conectividade IPv4. Isso ainda não comprova handshake ou
transferência BitTorrent, que pertencem à validação com clientes reais.

### Evidência atual

- **15 testes / 239 assertions** na suíte de journal com MySQL/Redis reais.
  Além da cobertura anterior: resposta com `numwant`, retenção com reativação
  pendente, TCP em IPv4/IPv6 reais, cache limitado durante rotação de portas,
  recuperação de mensagens não confirmadas e recusa sem heartbeat.
  Log: `lab/dualstack/results/journal/journal-php-fencing.txt`.
- **30 passos HTTP aprovados**, com Rust ausente: duas ordens de famílias,
  contadores atrasados, crédito 200 na sequência obrigatória, `numwant=0/1`,
  stop parcial/repetido, headers/parâmetros forjados, quatro clientes HTTP
  concorrentes, troca para IPv6 de origem `fd42:756e:6974:92::31`, stop do
  endereço antigo, limite de três peers e incremento exato de um byte até
  `18446744073709551615`. Origem secundária adicionada somente à `eth1` da VM 122.
  Log: `lab/dualstack/results/standalone/candidate-php-http-extended.json`.
- **27 transições confirmadas** exportadas com usuário, torrent, `HEX(peer_id)`,
  família, evento, versões e deltas; sem passkeys. As outras três operações são
  dois stops ignorados e a recusa do quarto peer.
  Log: `lab/dualstack/results/standalone/candidate-transition-trace.json`.
- Restart do coordenador: geração 2 → 3, quatro peers carregados; referências,
  endpoints, créditos e backlog idênticos antes/depois.
  Logs: `candidate-before-restart.json` e `candidate-after-restart.json`.
- Encerramento com SIGTERM concluiu a drenagem e retornou zero.
  Log: `lab/dualstack/results/standalone/candidate-graceful-stop.txt`.

Os ensaios anteriores permanecem preservados. O primeiro HTTP comparou saldo
final com 200, mas havia copiado um saldo inicial de 200 do baseline: a variação
observada já era a correta. A preparação passou a zerar saldos somente no banco
do candidato. O primeiro ensaio de encerramento usava `APP_ENV=testing`, que
desativa os handlers Laravel, e SIGQUIT herdado da imagem FPM; terminou com 137 e
backlog zero. O serviço do laboratório passou a usar `APP_ENV=local` e SIGTERM,
e o encerramento foi revalidado. O formato de access log FPM exclui a URI.

### Pendências e próxima sequência

Não considerar a feature inteira concluída nem pronta para ativação real.
`DUALSTACK_ENABLED` segue falso por padrão; foi ativado somente nos containers
de ensaio, já encerrados. Antes de fechar a etapa 3, completar a injeção de
indisponibilidade dos serviços MySQL/Redis e os casos sobrepostos de
announce/expiração/stop, distinguindo perda assíncrona de crédito confirmado.
A suíte já cobre rollback transacional, reentrega, expiração, lease e concorrência,
mas esses ensaios não substituem todos os cenários de falha do plano.

Depois: implementar o Rust na revisão fixada, executar paridade e integrar
API/admin, BON, preferência visual e jobs do site. Ainda faltam handoff entre
backends, os dois rollbacks, clientes BitTorrent reais, performance e soak de
seis horas. Não há resultado que aprove p95/p99, throughput ou memória sob carga.
Não foi feita alteração no Rust, push, publicação ou implantação em produção.

O manifesto atual está em `lab/dualstack/checkpoint-php.json`; o manifesto inicial
`checkpoint.json` foi mantido como histórico. As instruções do modo PHP estão
em `docs/dualstack-standalone.md`.

## Retomada — falhas reais e encerramento da etapa 3

Commit UNIT3D: `c25e4c3a7e91e1dd9f452dad5b410b33a65740aa`.
Nenhuma alteração no processamento PHP foi necessária nesta rodada.

- Journal: **24 testes / 449 assertions**, sem skips. As seis ordens de
  announce/expiração/stop e três processos simultâneos convergiram para um peer
  ativo, somente o IPv6 renovado e crédito 200. A morte real do consumidor com
  SIGKILL antes do commit deixou SQL sem efeitos; depois do commit e antes do
  ACK, a reentrega preservou o crédito sem reaplicar incrementos.
- Serviços: **29 passos aprovados**. MySQL e Redis foram interrompidos
  separadamente, com uma transição HTTP já aceita ainda no journal. O coordenador
  saiu com erro, o announce durante a indisponibilidade foi recusado e uma nova
  geração recuperou a fila. Reenviar os mesmos contadores não criou crédito.
  Resultado final: referência 1.400, crédito 400, um peer e dois endpoints,
  contadores 1/1/1 e backlog zero. Encerramento posterior com drenagem aprovado.
- O teste de Redis usa `docker stop`, que sincroniza o AOF. Não representa perda
  de dados de AOF ainda não sincronizados, desligamento do host nem um ensaio de
  durabilidade sob carga. SIGKILL foi aplicado ao consumidor PHP, nas duas
  fronteiras de commit. A janela assíncrona sob carga continua sem medição.

Evidências: `results/journal/journal-php-crash-overlap.txt` e
`results/standalone/candidate-php-service-faults.json`, sob `lab/dualstack/`.
Scripts `fault-services-php.py`, `fault-announce.py` e `fault-state.php` registram
somente campos permitidos, sem passkeys, credenciais ou respostas HTTP brutas.

Este resultado permite avançar para o Rust. As integrações de site, o handoff,
os rollbacks, clientes BitTorrent reais, performance e soak seguem pendentes;
não há aprovação da feature completa nem autorização de produção.

## Etapa 4 — primeiro incremento Rust

Núcleo em `repos/UNIT3D-Announce/src/dualstack/peer.rs`, com slots limitados de
endpoints, transição pura, contabilidade `u64`, fatores financeiros sem floats,
expiração por família, stop por origem e probes condicionados à revisão.
Os contadores são contribuições do peer lógico, incluindo as quatro variantes
por família. A serialização mantém referências financeiras em strings decimais.

Verificação no mesmo runtime Rust 1.99.0 do baseline, `cargo test --locked
--release --test dualstack_contract -- --include-ignored --nocapture`:

- **5 testes aprovados, zero falhas e zero ignorados** no comando do laboratório;
- **12 casos / 51 operações** da fixture compartilhada;
- snapshots completos de PHP e Rust iguais em todas as operações, incluindo
  deltas, metadados, endpoints, estado agregado e contadores com/sem exigência
  de conectividade, com/sem filtro temporal;
- rotação de 10 mil IPv6 sem exceder dois endpoints, incremento exato até
  `u64::MAX`, fatores financeiros com overflow recusado e política de origem.

Evidências: `lab/dualstack/results/contract/`, incluindo os dois traces completos,
log de compilação/testes e `parity.json`. `compare-peer-contract.py` compara
todos os campos, validando também quantidade e ordem das operações. Os mapas
vazios do PHP são normalizados como objetos JSON na exportação.

Nenhuma dependência foi atualizada: `serde_json` 1.0.149 já existia no lockfile e
foi promovido a dependência direta somente de testes. O aviso de depreciação em
`src/stats.rs:226` é preexistente e permanece fora desta mudança. A imagem mínima
não incluía rustfmt; o componente da toolchain 1.99.0 foi instalado apenas no
container efêmero de formatação.

**Etapa 4 ainda não aprovada:** o handler HTTP e as filas originais ainda não
usam o núcleo novo. Próxima sequência: conectar o peer lógico aos stores,
coordenar transição e backlog na mesma seção de sincronização e implementar
persistência MySQL em lotes com versão e geração do proprietário. Depois,
bootstrap, limpeza, resposta, cache de probes e encerramento, seguidos da mesma
matriz de concorrência/falhas executada no PHP. Não afirmar suporte dualstack do
binário Rust antes dessas verificações. Manifesto: `checkpoint-rust-core.json`.

## Etapa 4 — coordenador Rust e falha no primeiro ensaio MySQL

Escrito neste incremento:

- `src/dualstack/coordinator.rs`: estado, versões, índices de slots, fila
  limitada, publicação sem I/O, snapshot do lote sem removê-lo da fila,
  fechamento da entrada, expiração e drenagem;
- `src/dualstack/persistence.rs`: aquisição e renovação da lease SQL, geração
  do proprietário, bootstrap por streaming, reconciliação de contadores e
  persistência transacional em lotes. Locks: proprietário compartilhado,
  usuários, torrents, históricos e peers, ordenados como no PHP;
- suíte opt-in com MySQL real e scripts de execução/inspeção do laboratório.

O núcleo ainda não foi ligado ao HTTP, aos stores ou ao scheduler originais.
A integração depende da aprovação deste consumidor e do fechamento do handoff
com o journal PHP. `serde_json` foi movido para dependência de produção sem
alterar a versão ou o lockfile. Nenhuma migração ou fonte PHP foi alterada.

### Resultado e ponto de parada

`cargo check --locked --lib` passou. O teste de integração compilou em release,
mas **falhou na segunda chamada a `persist_batch`**, que deveria reconhecer a
reentrega das cinco transições e retornar zero. Erro observado:

```text
ColumnDecode: created_at
Option<chrono::naive::datetime::NaiveDateTime> (DATETIME)
is not compatible with SQL type TIMESTAMP
```

O helper `epoch` em `src/dualstack/persistence.rs:53` usa o tipo incompatível.
O catálogo real confirma `history.created_at`, `updated_at` e `swarm_updated_at`
como TIMESTAMP; `completed_at` é DATETIME. O loader original da tag já lê
`peers.updated_at` como `DateTime<Utc>` em `src/store/torrent.rs:93`.
Correção indicada para a retomada: usar os codecs correspondentes no Rust,
preservando os tipos existentes no schema. Não foi aplicada após a falha.

Snapshot somente leitura depois do erro:

| Campo | Observado |
|---|---|
| Backend/geração | Rust / 92, lease expirada |
| Peer/histórico | uma linha cada, versão 5 |
| Referência upload | 1.200 |
| Crédito usuário / histórico real | 200 / 200 |
| Endpoints | IPv4 `192.0.2.30`, IPv6 `2001:db8::30` |
| Seeders total / IPv4 / IPv6 | 1 / 1 / 1 |
| Trigger de injeção de falha | ausente; cenário ainda não alcançado |

A primeira aplicação foi confirmada por inteiro; a leitura da reentrega
falhou e o crédito observado permaneceu 200. Isso **não aprova idempotência**,
restart nem os demais cenários escritos. A sequência foi interrompida conforme
o plano. O processo de teste terminou; não há tracker ativo no laboratório.

Evidências em `lab/dualstack/results/rust/`:
`coordinator-check.txt`, `mysql-coordinator-initial.txt` e
`mysql-after-replay-failure.json`. Reprodução: `run-rust-mysql.sh` na VM tracker,
com os serviços de dados ativos e sem containers de tracker. O teste é destrutivo
somente para o banco isolado `unit3d_dualstack_journal_test`.

### Revisão do incremento contra o plano

Não houve alteração das decisões de identidade, contabilidade, reseed ou BON.
As bases fixadas permanecem ancestrais das branches. A implementação do
coordenador está incompleta e a etapa 4 continua sem aprovação. Antes de ligar
o HTTP, também é necessário cobrir classificação de erros para retry, timeouts
de aquisição/renovação, supervisão e recusa de handoff com fila PHP pendente.
O custo de guardar metadados dos históricos no bootstrap precisa ser medido.
Não há evidência nova de performance, transferência BitTorrent ou implantação.

## Etapa 4 — correção de datas e retomada da suíte MySQL

Retomada autorizada pelo pedido “Faça a correção”. O helper `epoch` agora lê
TIMESTAMP como `Option<DateTime<Utc>>`; `completed_at` continua sendo lido como
`Option<NaiveDateTime>`, correspondente ao DATETIME real. Nenhuma migração,
dependência, regra contábil ou fonte do UNIT3D/PHP foi alterada.

A suíte avançou e expôs problemas do próprio ensaio, antes de alcançar as
asserções seguintes. Foram corrigidos sem mudar os resultados esperados:

- `seeders` legado é INT com sinal; sua leitura no teste passou de `u32` para
  `i32`. Os contadores por família permanecem `u32`; esperado 1/1/1.
- CREATE TRIGGER não passou pelo protocolo preparado (1295) e, depois da
  troca de protocolo, foi recusado por falta de privilégio global com binlog
  ativo (1419). A injeção agora usa um CHECK temporário `uploaded = 0` no
  histórico vazio. O lote de teste tenta gravar crédito 100 e deve receber
  especificamente a violação 3819 de `dualstack_test_fail`, depois de escrever
  peers/endpoints dentro da transação. O CHECK é removido antes de verificar
  rollback/retry. Não foram concedidas permissões nem alterado o servidor.

### Verificação executada

MySQL 8.0.46 real, REPEATABLE-READ, lock wait 10 s e Rust 1.99.0, com as mesmas
imagens fixadas do laboratório. Build release com `--locked` aprovado. A suíte
é **um teste de integração com oito blocos sequenciais**, todos aprovados:

| Bloco | Resultado observado |
|---|---|
| Contabilidade, reentrega e restart | Cinco transições, crédito 200, reentrega aplica zero, dois endpoints restaurados; geração antiga recusada e stop parcial preserva IPv6 |
| Backlog | Fila cheia recusa publicação sem avançar referência/versão; após drenagem, crédito 100 |
| Falha SQL | Violação CHECK 3819 deixa peers, endpoints, histórico e crédito zerados; duas transições continuam pendentes e retry confirma crédito 100 |
| Concorrência | Quatro threads, 401 transições, crédito 4.000; contador de consultas cresce somente pela própria consulta de medição |
| Expiração | IPv6 expira e IPv4 permanece |
| Limites | Três peers dualstack, seis endpoints; quarto peer recusado |
| Precisão | Referência `u64::MAX`, delta/crédito exatamente 1 |
| Regressão de datas | TIMESTAMP e DATETIME preenchidos sobrevivem à reentrega e restart; probe preservado, conclusão única, crédito upload/download 100/100 e seedtime 30 |

A regressão usa relógio explícito para separar os timestamps de announce,
conclusão e probe. Depois de recarregar, verifica que seedtime continua usando
`swarm_updated_at`, sem perder o intervalo coberto pela checagem de conectividade.
O snapshot final registra versões de peer/histórico 6, referência 1.100/100,
crédito 100/100, dois endpoints, contadores 1/1/1, uma conclusão e lease liberada.
Trigger e CHECK de ensaio estão ausentes. A duração de 0,48 s da suíte não é
medição de performance do tracker. O aviso preexistente em `src/stats.rs:226`
permanece fora do escopo.

Evidências em `lab/dualstack/results/rust/`:

- `mysql-timestamp-fixed-test-codec.txt`, `mysql-codecs-fixed-trigger-protocol.txt`
  e `mysql-codecs-fixed-trigger-privileges.txt`: obstáculos intermediários do ensaio;
- `mysql-timestamp-fixed-existing-suite.txt`: sete blocos originais aprovados;
- `mysql-timestamp-regression.txt`: suíte final com oito blocos aprovada;
- `mysql-after-timestamp-fix.json`: inspeção somente leitura após a suíte.

### Limite deste checkpoint e próximo item

A correção remove o bloqueio de codec e verifica os cenários acima. A etapa 4
**não está concluída**: o coordenador ainda não recebe announces pelo HTTP e
os testes exercitam sua biblioteca diretamente. Próximo item: cobertura e
tratamento de falhas do coordenador, incluindo classificação de erros para retry,
timeouts de aquisição/renovação, supervisão da lease e recusa de troca de backend
com fila PHP pendente. Integração HTTP, probes em rede, retenção, API/admin,
performance e clientes BitTorrent reais continuam pendentes.

Revisão final contra o escopo: mudanças de produção restritas ao codec; demais
alterações são teste, inspeção e documentação. Sem mudança de identidade,
crédito ou contadores esperados; sem push ou implantação em produção. O manifesto
`lab/dualstack/checkpoint-rust-timestamps.json` identifica as revisões deste checkpoint.

## Etapa 4 — falhas e supervisão do coordenador Rust

O usuário autorizou a continuidade automática para o próximo item quando testes
e validações passarem. Permanecem os checkpoints locais, o registro de evidências
e a parada diante de falha de critério, sem push ou produção.

Implementados limites de espera de 3 s para adquirir/renovar/liberar a lease,
120 s para bootstrap/encerramento e 15 s por tentativa de persistência. O retry
agora lê o número MySQL, em vez de comparar SQLSTATE com 1205/1213. Mantém três
tentativas com backoff 50/100 ms e idempotência por versão; falha final fecha
a entrada e conserva a fila. Contadores de retries/deadlocks ficam disponíveis.

O supervisor de biblioteca renova a cada 5 s independentemente da persistência,
consome lotes a cada 100 ms, verifica expiração a cada 60 s e drena ao receber
o sinal de encerramento. Falha de qualquer loop fecha a entrada. Ainda não está
ligado ao lifecycle HTTP do binário.

Verificação no mesmo MySQL 8.0.46: **17 blocos em um teste de integração**, sem
skips, aprovados. Nove blocos novos forçaram aquisição/renovação/liberação
bloqueadas, dois lock waits antes do sucesso, esgotamento das três tentativas,
deadlock 1213 real, supervisão por 12 s, renovação bloqueada com escritor em voo
e erro SQL permanente. Conferidos zero crédito parcial, fila retida, entrada
recusada após falha e crédito 100 único depois da drenagem.

A instrumentação do teste exigiu ajustes: SHOW STATUS não admite o placeholder
usado e MySQL 8.0 não expôs `Innodb_deadlocks` nessa consulta. O ensaio usa
`Innodb_row_lock_current_waits`/`Innodb_row_lock_waits` e registra o erro 1213
recebido pelo coordenador. Não mudou critérios nem concedeu privilégios globais.
Logs intermediários: `mysql-failures-metric-syntax.txt` e
`mysql-failures-metric-unavailable.txt`; resultado final: `mysql-failures.txt`,
todos sob `lab/dualstack/results/rust/`. A duração de 30,42 s é da suíte funcional.

Próximo item autorizado: comprovar drenagem PHP antes da aquisição pelo Rust e
validar a troca nos dois sentidos, preservando referências, endpoints e créditos.

## Etapa 4 — troca PHP/Rust com confirmação de drenagem

A migração aditiva `000003` acrescenta `php_journal_drained` ao proprietário SQL,
com padrão falso e retomada sem alterar geração/identidade. PHP reinicia o
marcador em cada aquisição. Na liberação, um Lua fecha produtores, remove o
heartbeat e verifica journal/filas legadas; o resultado é gravado junto da
liberação SQL, condicionado à identidade/geração. Um processo antigo não pode
certificar o novo. Com mensagens pendentes ou Redis indisponível, não há
confirmação; a recuperação pelo PHP deve preceder a troca.

Rust recusa o último proprietário PHP sem drenagem confirmada, antes de mudar
geração. Não consulta Redis nem acrescenta SQL ao announce. A implantação ainda
exige parar escritores legados; o marcador não autoriza misturar versões antigas.

Validação executada com `lab/dualstack/run-handoff.sh` e fixtures isoladas:

- migração executada duas vezes sem reiniciar geração/proprietário;
- três casos PHP novos: pendência impede certificação, geração antiga não altera
  a nova e filas legadas também impedem certificação;
- regressão Rust: 17 blocos aprovados;
- PHP produz duas mensagens e fecha; Rust recusa sem avançar geração/crédito;
- PHP recupera/drena, confirma crédito 100 e dois endpoints;
- Rust restaura e credita somente mais 100;
- PHP restaura, credita mais 100 e para somente IPv6;
- Rust restaura IPv4 e referência 1.300; novo announce 1.300 não credita novamente.

Evidências: `results/rust/handoff-initial.txt` e `mysql-after-handoff.json` sob
`lab/dualstack/`. O ensaio inicial PHP deixou dois testes de rede em skip por
falta das variáveis de bind. Esses casos foram executados na regressão completa:
**27 testes / 474 asserções, zero skips**, em `results/journal/handoff-php-full.txt`.
O script reproduzível agora fornece IPv4/IPv6 reais e exige `--fail-on-skipped`.
Pint passou nos três arquivos PHP modificados.

Este checkpoint confirma o contrato entre coordenadores, não a integração HTTP
do Rust. Sem mudanças no protocolo/contabilidade esperados e sem novas dependências.
Próximo item: seleção de peers por torrent, contadores temporais, resposta compacta
com ambos endpoints e `numwant` lógico, seguido da conexão ao handler HTTP.

## Etapa 4 — seleção e resposta compacta Rust

O coordenador mantém um índice de peers por torrent, reconstruído no bootstrap
e atualizado na mesma seção das transições. A seleção percorre somente aquele
torrent, calcula contadores lógicos/por família antes do truncamento e filtra
TTL/conectividade por endpoint. Retorna ambos os caminhos de cada peer escolhido,
exclui o próprio usuário e respeita a preferência por seeders/listas permitidas.
O encoder gera bencode com comprimentos em bytes e estatísticas estáveis mesmo
quando a lista está vazia ou há aviso.

Verificação: **18 blocos Rust/MySQL aprovados**. O bloco novo cobre `numwant`
0/1/2, valor maior que a população, limite de 24 bytes por peer dualstack,
igualdade byte a byte do bencode com texto UTF-8, contadores não truncados,
exclusão do próprio usuário, isolamento por torrent, TTL sem limpeza física,
índice após restart, falha de uma família sem ocultar a conectável e ausência
de SQL durante seleção/codificação. Usa o TTL padrão de 7.200 s com relógio de
ensaio, mantendo folga para o bootstrap real. Evidência:
`lab/dualstack/results/rust/mysql-response.txt`.

Os novos arquivos foram formatados com rustfmt; lockfiles permanecem intactos.
A implementação é de biblioteca, ainda sem entrada HTTP. Prosseguir para ligar
o handler, configuração de origem/proxies e lifecycle supervisionado do servidor.


## Retomada — handler HTTP Rust e ciclo de vida do processo

Checkpoint Rust `3894750cb95729c7410bc2f55c978492e9beab81`, ainda na etapa 4.
O handler dualstack usa origem observada, validações existentes e fatores de
crédito uma vez por delta lógico. Não popula as filas financeiras legadas.
O saldo do torrent integra a transação; conclusões avançam dentro do mutex do
coordenador. O bootstrap lê `times_completed` como INT com sinal, conforme a tag.

Primeira execução: erro de codec ao tentar ler esse INT como `u32`, antes de
aceitar announces. Evidência preservada em `http-bootstrap-initial.txt`.
Corrigido o leitor dentro da mesma etapa; nenhum critério foi relaxado.
Fatores de crédito preservam o intervalo u8 permitido pela configuração original,
inclusive 255%, com intermediário u128 e erro explícito de overflow.

Validações:

- Suíte MySQL: 18 blocos aprovados, incluindo saldo/reentrega, concorrência,
  falhas, expiração e supervisor. `rust-http-mysql.txt`.
- Contrato puro: 5 testes, 12 casos / 51 operações. `rust-http-contract.txt`.
- Testes do binário: 19 aprovados, incluindo proxies explícitos, cache limitado,
  expiração e limite de conexões TCP em voo. `rust-http-network.txt`.
- Mesmo gerador HTTP do PHP: 30 passos aprovados com binds IPv4/IPv6 reais,
  oito announces concorrentes, uint64 e origens forjadas ignoradas.
  `rust-http-contract.json`.
- SIGTERM real: código 0, lease liberada, endpoints e créditos preservados.
  Restart em geração maior, contadores repetidos sem novo crédito e incremento
  de 100 creditado uma vez nas duas famílias. `rust-http-{before,stopped,resumed}.json`.
- Segundo processo real recusado antes de abrir HTTP: `rust-http-second-owner.txt`.

Todos os resultados acima estão em `lab/dualstack/results/rust/`. O snapshot
`mysql-after-http.json` confirma o estado final sem proprietário ativo. O aviso
`fetch_update` do Rust 1.99 vem de `src/stats.rs` da base e permanece separado.

Revisão diff versus plano: origem confiável, contabilidade compartilhada,
resposta compacta, supervisão e encerramento estão integrados. Não há consultas
SQL no handler dualstack; publicação e seleção continuam em memória. A API
administrativa ainda representa o formato legado e será tratada na etapa 5.
Retenção de peers inativos, cobertura HTTP ampliada de conectividade/proxy,
clientes BitTorrent reais, rollbacks e benchmarks seguem pendentes. Nenhuma
implantação em produção ou push foi realizada.


## Retomada — retenção confirmada no Rust

Checkpoint `e5529f79a22623208a073b8361e39ad062a02ceb`. A retenção segue
`INACTIVE_PEER_TTL` da tag (21 dias por padrão), com mínimo de 7200 s no modo
dualstack. Reserva apenas as identidades candidatas, exclui qualquer peer com
transição pendente, verifica versão/geração e remove SQL antes da referência
em memória. Nenhum mutex do swarm permanece adquirido durante I/O.

A suíte MySQL passou com **21 blocos**. Os três novos blocos verificam limite
de lote; preservação de ativo/recente/histórico; reconexão sem duplicar crédito
ou conclusão; announce durante DELETE bloqueado; e cancelamento com rollback,
entrada fechada e retomada por novo bootstrap. Crédito final esperado preservado.
Evidências: `lab/dualstack/results/rust/rust-retention.txt` e
`mysql-after-retention.json`. O segundo confirma lease liberada.

Revisão diff versus plano: a exclusão física só ocorre após confirmação das
transições e não altera o histórico financeiro. São mantidos metadados compactos
de versão/conclusão por usuário/torrent para deduplicação; sua memória ainda será
medida no benchmark. Próximos itens: probes/proxy no HTTP real e representação
administrativa dualstack entre os projetos. As etapas 5 e 6 seguem abertas.


## Retomada — proxy e conectividade TCP no HTTP

O checkpoint Rust de retenção passou também pelo servidor real atrás do nginx,
com `REQUIRE_PEER_CONNECTIVITY=true`. Nove passos comprovaram: IPv6 fechado
preserva IPv4; abertura IPv6 publica ambos; troca para porta IPv4 fechada mantém
IPv6; recuperação IPv4 restaura os dois. Houve três conexões TCP IPv4 e uma IPv6
aceitas pelos listeners da VM clientes. Crédito final: 100, sem multiplicação
pelos probes. O proxy sobrescreveu headers forjados com a origem real.

Sete origens inválidas foram recusadas no extrator HTTP, incluindo unspecified,
multicast e link-local nas duas famílias. Reload que tenta desativar dualstack
retorna 409; a política original restaurada retorna 200. Encerramento final do
binário: código 0. Evidências `rust-http-connectivity.json` e
`rust-http-boundaries.json` em `lab/dualstack/results/rust/`.

Para reproduzir: `start-candidate-rust.sh fresh proxy`, com `nginx-rust.conf`,
seguido de `rust-http-connectivity.py` na VM clientes e
`rust-http-boundaries.py` (sudo) na VM tracker. O perfil reduz cache para 16
entradas/1 s apenas no laboratório. Não constitui teste de handshake/transferência
BitTorrent. Próximo item: contrato administrativo e adaptador do UNIT3D.


## Retomada — API administrativa integrada ao UNIT3D

Checkpoints:

- Rust: `1fabed68f88ddd754074d4f3ae7bd185a9412225`.
- UNIT3D: `8cedf6404d7c65e2a0eb5fb9c1da51a7eaf678ac`.

O endpoint autenticado `capabilities` declara schema 1 quando dualstack está
ativo. O torrent administrativo mostra uma linha por identidade, endpoints
vigentes, estado agregado, contadores lógicos e por família, versões e tráfego
uint64 em strings decimais. Peers inativos permanecem até a retenção. O índice
por torrent inclui esses peers; seleção pública continua aplicando atividade,
visibilidade, TTL e política de conectividade. A remoção física limpa o índice.

O adaptador PHP reconhece explicitamente esse contrato e aceita o legado como
não dualstack. Endereços novos não dependem da projeção de compatibilidade.
Valores fora do contrato são recusados. A tela preserva acesso a IPs para o
próprio usuário e moderação, e carrega usuários/grupos/privacidade em lote.
O cliente HTTP administrativo agora tem timeouts de conexão e de resposta.

Verificações:

- **22 blocos MySQL** aprovados no Rust; o novo bloco valida identidade entre
  usuários, uint64, inativos, contadores e snapshot após restart.
- **13 testes PHP / 27 asserções**: leitura nova/legada, oito contratos inválidos,
  ausência de backend sem requests e renderização de endpoints conforme permissão.
- Os **30 passos HTTP reais** passaram novamente após alterar o índice.
- Integração real PHP -> Rust: **6 peers / 11 endpoints**, uint64 máximo exato,
  contadores de usuário corretos e **4 consultas** no controller para carregar
  quatro usuários. Refresh administrativo com contadores desatualizados não
  sobrescreveu o estado corrente. Template principal compilado; parcial de IPs
  renderizado nos testes de permissão. Não foi feita revisão visual da página inteira.
- Fatores atualizados via UNIT3D: double upload + freeleech resultou em crédito
  200/0; retorno aos fatores normais resultou em 100/100, apesar dos announces nas
  duas famílias. Testes HTTP reais com SQL final verificado.

Evidências em `lab/dualstack/results/rust/`: `rust-admin-mysql.txt`,
`php-admin-tests.txt`, `php-rust-admin.json`, `rust-admin-http-contract.json`,
`rust-http-free-double.json`, `rust-http-normal-factors.json` e
`mysql-after-admin.json`. Último encerramento Rust: SIGTERM com código 0; lease
liberada. Nenhum container de tracker ficou ativo.

Revisão final diff versus plano: apenas contrato administrativo, projeção de
contadores, leitor/tela correspondente e cobertura associada. A sincronização
de metadados do torrent foi tornada atômica para não expor remoção intermediária.
As bases fixadas foram preservadas, sem atualização de versões de dependências.
O Cargo.lock conserva a adição anterior de serde_json como dependência direta
(já resolvida em 1.0.149 na tag); estes checkpoints não alteraram lockfiles.
Sem push ou produção.

### Próximos itens autorizados

1. Preferência visual `ipv4|ipv6|sum|auto`, resolução diária e contadores novos
   nas APIs públicas, preservando regras de reseed/graveyard e totais legados.
2. Revisar todos os consumidores/rotinas do site e ampliar testes de paridade,
   incluindo BON e seedtime existentes sem multiplicação por endpoint.
3. Ensaiar rollback para versão original, clientes BitTorrent reais e benchmarks
   de latência/throughput/memória, incluindo carga prolongada. Não há aprovação
   de performance nem validação de transferência BitTorrent nesta entrega.

A continuidade desses itens já foi autorizada pelo usuário, condicionada aos
respectivos testes e verificações. Não solicitar nova autorização por item.

## Revisão de escopo — BON, 08/10/2026

O usuário retirou BON por família da entrega obrigatória. A exceção seria um
complemento opcional das regras existentes, como incentivo a IPv6, se a base já
estivesse pronta. A inspeção confirmou preparação parcial, sem recurso utilizável:

- `repos/UNIT3D/database/migrations/2026_10_08_000001_expand_dualstack_schema.php:76`
  acrescenta os quatro contadores de torrent; as linhas 91–92 ampliam os enums
  das regras BON, sem criar regras nem mudar valores de pagamento.
- `repos/UNIT3D/app/Console/Commands/AutoBonAllocation.php:60` e `:75` ainda
  mapeiam apenas as variáveis anteriores; `:110` agrega por usuário/torrent.
- `repos/UNIT3D/app/Http/Requests/Staff/StoreBonEarningRequest.php:47` e
  `repos/UNIT3D/app/Http/Requests/Staff/UpdateBonEarningRequest.php:46` não
  aceitam as quatro variáveis; os seletores administrativos também não as expõem.

Decisão aplicada ao plano: preservar remuneração e schema aditivo existentes,
sem implementar cálculo/editor BON por família nesta entrega. Os enums reservados
não representam suporte funcional e não devem ser usados para cadastrar regras
diretamente no banco. Os contadores por família continuam necessários para o
tracker, a interface e as APIs.

Um eventual incentivo precisará de elegibilidade por usuário/torrent e da
definição de uso IPv6 que se pretende premiar, sem uma segunda remuneração por
endpoint. A presença de IPv6 em outro peer do swarm não comprova uso pelo usuário.
Essa extensão fica como possibilidade futura, fora dos critérios de conclusão.
A regressão do BON atual e do seedtime permanece obrigatória nos dois backends.

Verificação desta revisão: inspeção do schema, alocador, validações e seletores;
revisão do diff contra a decisão do usuário e `git diff --check`. Alteração apenas
documental, sem nova execução de testes de runtime e sem alteração dos projetos
PHP/Rust. Resultados anteriores não são evidência de um incentivo IPv6 pronto.
O campo `next` de checkpoints históricos, inclusive `checkpoint-admin.json`,
registra a expectativa daquele momento; a lista atual acima substitui essa previsão.

## Etapa 5 — preferência visual, auto e contadores REST

Implementados seletor em configurações gerais, apresentação por observador e
resolução diária independente do Rust. A escolha e o resultado automático ficam
separados. A resolução privilegia seeding, considera apenas endpoints vigentes
e usa `sum` sem atividade. O comando usa lotes de 500 usuários; uma escrita SQL
por lote, sem tocar em créditos ou timestamps de usuários. O salvamento mantém
a autorização anterior e não aceita resolução automática fornecida pelo cliente.

As listas carregam as quatro colunas em suas projeções existentes. A apresentação
não altera atributos lógicos, filtros ou ordenação. A API REST preserva totais
e acrescenta famílias quando dualstack está ativo; o caminho de busca funciona
também com índice antigo mediante uma consulta agregada por página. O cache
separa o modo legado do novo contrato.

Validação no laboratório: **36 testes passaram, 220 asserções**, incluindo 23
casos novos e 13 regressões administrativas. MySQL real, Blade renderizado sem
SQL por contador e todas as views compiladas. BON existente permaneceu em 30
pontos por usuário/torrent com mais endpoints/peers, nos quatro modos visuais.
O teste de busca simula o motor e executa controller/cache/MySQL reais. A troca
da configuração de backend nos testes não é um novo ensaio HTTP de handoff.

Revisão final do diff versus plano: apresentação, preferência, job diário, API
e cobertura de preservação do BON; sem mudança de remuneração ou do processamento
de announce. Nenhuma migração ou dependência nova. Bases e lockfiles preservados.
Detalhes em `docs/dualstack-contadores.md`; execução reproduzível em
`lab/dualstack/run-preference-tests.sh` e resultado em
`lab/dualstack/results/php-preference-tests.txt`.

Próxima revisão: telas locais de peers/endpoints e operações do site que ainda
escrevam diretamente no swarm. Depois, completar paridade de consumidores,
rollback para as versões originais, clientes reais e benchmarks. A feature
completa ainda não está homologada.

## Etapa 5 — critério de escritor único falhou nas limpezas manuais

Após o checkpoint validado de preferências (`b949d3944` no UNIT3D e `5c5cf75`
na coordenação), a revisão dos próximos consumidores encontrou gravações diretas:

- `repos/UNIT3D/app/Http/Controllers/User/PeerController.php:66` exclui peers
  do usuário e depois altera o histórico; só recusa o modo de tracker externo.
- `repos/UNIT3D/app/Http/Controllers/Staff/FlushController.php:53` faz a mesma
  limpeza pelo painel administrativo, sem integração com o coordenador standalone.

Reprodução com MySQL real e `dualstack.enabled=true`, tracker externo desativado:
`lab/dualstack/check-site-writers.php` executou os dois controllers sobre fixtures
antigas, em transações revertidas. Nenhum coordenador estava rodando; o ensaio
confirma a escrita direta, não simula uma corrida com persistência em andamento.

| Ação | Peers antes/depois | Endpoints antes/depois | Histórico ativo antes/depois | Resultado |
|---|---|---|---|---|
| Limpeza do usuário | 1 → 0 | 2 → 0 | sim → não | falhou |
| Limpeza administrativa | 1 → 0 | 2 → 0 | sim → não | falhou |

A limpeza do usuário também consumiu uma das duas limpezas disponíveis. Tudo
foi revertido ao final de cada caso. Resultado bruto em
`lab/dualstack/results/site-writers.json`; processo encerrou com código **1**.
O critério é que o site não persista transições do swarm fora do coordenador
proprietário. Não foi demonstrada duplicação de crédito neste diagnóstico.

Conforme a instrução de parar ao falhar um critério, não avançar desta verificação
para telas locais, rollback ou performance. A correção necessária continua dentro
da etapa 5 aprovada: integrar/controlar as operações de limpeza pelo proprietário
e executar novamente este ensaio e as regressões de persistência. A inspeção
também localizou exclusões diretas ao remover torrents e usuários; esses caminhos
precisam da mesma revisão, mas não foram executados neste diagnóstico.

Os 36 testes de preferências/admin e suas 220 asserções continuam verdes; isso
não fecha a etapa 5 nem autoriza implantação. Não houve mudança de código para
contornar o critério, push ou operação em produção.

## Etapa 5 — correção das limpezas manuais autorizada e validada

O pedido “Pode fazer o ajuste” autorizou corrigir o critério acima. As ações de
usuário e administração agora gravam uma intenção durável em
`tracker_cleanup_requests`; apenas o coordenador PHP publica a transição interna
`flush` pelo journal existente. O MySQL confirma endpoints, referência, contadores
e histórico pelo mesmo consumidor de transições. O modo externo conserva a
recusa existente de limpeza; nenhuma API nova de limpeza foi adicionada ao Rust.

Pontos da implementação:

- Migração aditiva `2026_10_08_000004_add_dualstack_cleanup_requests.php`, aplicada
  duas vezes no ensaio, sem duplicação. Schema e lockfiles anteriores preservados.
- Corte fixo de 70 minutos para usuário e 120 minutos para administração,
  revalidado contra o endpoint corrente no CAS. Uma renovação concorrente não é
  removida pelo snapshot SQL antigo. Contadores de tráfego não são reiniciados.
- Admissão, cota e deduplicação por escopo pendente na mesma transação. Fila com
  limite configurável de 1000 solicitações; processamento de até 25 peers por
  iteração. Não há histórico ilimitado de solicitações concluídas.
- Encerramento de endpoints elegíveis, retenção do peer lógico e atualização do
  histórico pela agregação de usuário/torrent. Preservados caminho recente, outro
  peer ativo e referências contábeis. Nenhuma mudança de regra BON.
- Liberação da propriedade serializada com a admissão; pedidos pendentes impedem
  `php_journal_drained=true`. `--once` e SIGTERM drenam as solicitações com a
  entrada fechada. Um erro mantém a intenção para a geração seguinte.

### Falhas encontradas durante a correção

O primeiro ensaio expôs uma corrida real: o MySQL fixa `UTC_TIMESTAMP()` no início
do statement, antes de esperar o lock. A admissão podia observar esse horário
antigo após a liberação e aceitar um pedido quando a drenagem já fora certificada.
O ajuste consulta o relógio após adquirir o lock, revalida a lease depois da cota
e revoga a lease com `NULL` na liberação. A corrida entre processos passou com a
asserção original: pedido aceito implica drenagem não certificada.

A injeção inicial por trigger dependia de privilégio SUPER indisponível no
usuário de laboratório. Foi substituída por CHECK temporário no MySQL real,
removido no `finally`, mantendo a asserção de rollback de cota e intenção. Os
probes IPv4/IPv6 receberam os endereços reais do laboratório; a execução final
exige ausência de skips. Evidência inicial em `results/cleanup-initial.txt`.

O primeiro ensaio do daemon herdou `APP_ENV=testing`, que desativa os handlers de
sinais do Laravel, e terminou com código 137 após o timeout do Docker. O runner
foi corrigido para `APP_ENV=local`, como já exige o procedimento standalone,
sem alterar os handlers da aplicação. O preflight verifica ambiente/sinais e
ausência de proprietário, pedidos ou journal pendentes antes de recriar fixtures.
Evidência inicial em `results/cleanup-lifecycle-initial.txt`.

### Verificação final no laboratório isolado

| Verificação | Resultado |
|---|---|
| Limpeza e regressões do journal | **42 testes, 609 asserções, sem skips** |
| Preferências, API administrativa e BON existente | **36 testes, 220 asserções, sem skips** |
| Compilação Blade | todas as views compiladas |
| Diagnóstico original dos dois controllers | código **0**, sem escrita direta nem gasto de cota sem proprietário |
| Disputa de quatro processos pela mesma solicitação | um pedido e uma cota; métricas de deadlocks/timeouts sem incremento |
| Limpeza concorrente com announce | endpoint renovado preservado; crédito adicional de 100 uma única vez |
| Reentrega após commit e retomada em nova geração | referências e crédito confirmado preservados |
| PHP pendente com journal vazio → Rust | teste Rust real recusa a troca sem alterar geração ou crédito |
| `dualstack:work --once` | retoma pedido pendente, preserva IPv6 recente e referência |
| Daemon + novos announces + SIGTERM | crédito 100; saída **0**, fila vazia e drenagem certificada |

Ambiente: PHP 8.4.26, MySQL 8.0.46 e Redis 7.2.16 reais nas VMs isoladas,
somente banco `unit3d_dualstack_journal_test`. Os testes chamam controllers,
journal, consumidor e processos reais; o ciclo de limpeza não constitui um novo
ensaio HTTP completo nem transferência BitTorrent. Rust permaneceu inalterado;
executado apenas o caso de recusa de handoff necessário à nova fila. O warning
pré-existente de `fetch_update` no compilador Rust não foi alterado.

Reprodução em `lab/dualstack/run-cleanup-tests.sh` e
`lab/dualstack/run-cleanup-lifecycle.sh`. Resultados brutos em
`lab/dualstack/results/cleanup-tests.txt`, `cleanup-lifecycle.txt` e
`cleanup-preference-regression.txt`. A evidência antiga `site-writers.json` foi
preservada como histórico; o diagnóstico repetido está no novo log da suíte.

Revisão final do diff contra o ajuste aprovado: correção dos dois controllers,
fila durável, integração com o escritor existente, proteção da troca de backend,
testes e documentação. Sem divergência de escopo identificada. Não houve push,
implantação ou alteração de dados de produção. Os cenários de concorrência
novos e as regressões não substituem a matriz completa de performance.

O bloqueio específico das limpezas manuais está resolvido. Próximos itens da
etapa 5: exclusões de torrents/usuários que ainda alterem o swarm e telas locais
de peers/endpoints. Depois, completar consumidores, rollback para versões
originais, clientes reais e benchmarks. A feature completa ainda não está homologada.

Checkpoint PHP: `a8907d536d3d65e40e5da82c286c9a63ac3a4948`. Rust permanece em
`1fabed68f88ddd754074d4f3ae7bd185a9412225`. Manifesto de resultados e pendências:
`lab/dualstack/checkpoint-cleanup.json`. Ao finalizar, não restaram containers de
tracker, proprietário vigente ou solicitações pendentes no banco de ensaio.

## Etapa 5 — exclusões coordenadas validadas

Implementados os caminhos de exclusão individual e em lote de torrents,
exclusão de usuários e poda automática, nos dois backends. O marcador durável
`tracker_removal_state` é aditivo: 0 antes da confirmação, 1 depois de confirmar
as transições anteriores e 2 ao concluir a remoção. Novos announces são bloqueados
antes de capturar a fronteira do journal. A exclusão física usa lotes de 200,
com contadores lógicos e cascata de endpoints; reentrega antiga não recria estado.

PHP standalone mantém a referência no Redis e o consumidor existente. Rust usa
a sincronização do coordenador e o mesmo escritor de lotes; não acrescenta SQL
síncrono ao announce. O bootstrap restaura os bloqueios de entidades excluídas.
A capacidade `coordinated_deletion` impede executar a nova ação sobre um backend
antigo que ainda removeria estado sem coordenar. Restauração manual via SQL não
foi implementada como funcionalidade de administração.

Validação em PHP 8.4.26, Rust 1.99.0, MySQL 8.0.46 e Redis 7.2.16 no laboratório:

- **57 testes PHP / 746 asserções**, incluindo os quatro caminhos do site,
  crédito pendente, commit antes de reconhecimento, reentrega, rollback SQL,
  recuperação, conectividade positiva e concorrência real com lock de linha.
- **Seis blocos Rust**, cobrindo exclusão de usuário/torrent, crédito, reinício,
  isolamento de outros recursos, CHECK com falha, cancelamento sob lock e lotes
  limitados. Sem incremento dos contadores de deadlocks/timeouts no cenário.
- Regressão Rust anterior de **22 blocos** aprovada; regressão de preferências e
  API administrativa de **36 testes / 220 asserções** aprovada; Blade compilado.
- Contrato HTTP de **30 passos em cada backend**, seguido da exclusão pelo
  controller real: seis peers removidos, endpoints/histórico zerados, crédito e
  outro torrent preservados. Quatro novos requests por backend comprovaram
  recusa IPv4/IPv6 e continuidade com um peer e dois endpoints no outro torrent.
- Ambos os processos encerraram com SIGTERM e código zero. Containers de tracker
  removidos; bancos baseline e produção preservados.

Falhas de preparação encontradas e corrigidas sem relaxar asserções: CHECK do
MySQL não aceita a coluna auto_increment usada na primeira fixture; usuário de
sistema e grupos de poda ausentes; tokens clonados precisavam ser únicos; fixture
privada precisava habilitar explicitamente redes privadas; métrica COUNT Rust
retornava BIGINT assinado; fakes HTTP antigos precisavam ser descartados entre
os casos negativo e positivo. Apenas a evidência sanitizada foi salva.

O primeiro contrato HTTP parou após 20 passos porque a VM havia perdido o IPv6
secundário `::31`. Reaplicado `prepare-client-rotation.sh`, o contrato completo
passou sem mudar a implementação. Evidência preservada em
`results/deletion-php-missing-address.json`. O rustfmt não estava instalado na
imagem fixada; foram formatados somente os novos arquivos com o rustfmt local
1.9.0, sem alterar dependências, e os testes Rust passaram depois disso.

Reprodução: `run-deletion-tests.sh`, contrato `candidate-php.py`,
`deletion-operator.php` e `deletion-http.py`. Evidências em
`lab/dualstack/results/deletion-*`; `deletion-tests.txt` registra os 55 testes
anteriores à cobertura de exclusão em lote, e `deletion-bulk-final.txt` registra
a execução final de 57 testes e os seis blocos Rust.

Revisão final do diff contra o plano: exclusões passam pelo proprietário,
crédito e referências confirmados permanecem coerentes, migração aditiva e
capacidade explícita do backend. Sem divergência de escopo identificada.
A migração verifica coluna e índice separadamente para retomar DDL parcial.
Não houve push ou implantação. Performance e a janela assíncrona sob carga não
foram inferidas desses ensaios; continuam pendentes junto de rollback original,
clientes reais e revisão dos demais consumidores. Próximo incremento: telas
locais de peers e endpoints, com consultas em lote e permissões existentes.

Checkpoint PHP: `2e5b6ad2ba6d77132962ee2155781e9f3c5af20a`.
Checkpoint Rust: `4074ee4fba815a7e2dc9769f6d8f4e1cd41c9547`.

## Etapa 5 — endpoints nas telas de torrent e atividade do usuário

Concluído o primeiro incremento de telas locais: uma linha por peer lógico,
IPv4/IPv6 com porta e conectividade próprias, estado desconhecido explícito e
marcação de endpoint expirado pelo TTL. A seleção visual respeita os IPs
permitidos ao próprio usuário e à moderação; terceiros recebem campos ocultos.
O modo dualstack lê `peer_ips`, inclusive em filtros e ordenação, sem depender
 da projeção legada. A combinação IP/porta exige o mesmo endpoint.

A tela de torrent pagina 50 peers com ordem estável e carrega usuários, grupos,
privacidade e endpoints em lote. A atividade limita a página a 100 e adiciona
uma consulta para seus endpoints. Ordenar IP ou porta usa o menor valor entre
os endpoints registrados; a célula continua mostrando ambos. Endpoints
expirados ainda aguardando limpeza são identificados, sem afirmar conectividade.
O modo legado permanece disponível sem consulta a `peer_ips`.

Validação: **46 testes / 498 asserções**, sem skips, MySQL real. Inclui os 36
casos anteriores e dez novos: 1 versus 50 peers com exatamente sete consultas,
página de 53 peers limitada a 50/100 endpoints, identidade composta, filtro IPv6
normalizado, IP/porta de famílias distintas recusados, conectividade desconhecida,
TTL, modo legado, HTML real do torrent para dono/terceiro/moderador e renderização
Livewire com atualização do filtro. Todas as views Blade compiladas.

A primeira execução conjunta deixou o factory/cache estático do Blade apontando
para a aplicação anterior entre suítes. Corrigido somente o isolamento da nova
suíte com `Component::flushCache()` e `forgetFactory()`. Casos funcionais novos
já passavam; regressões voltaram a passar com as mesmas asserções. Evidências:
`results/endpoint-view-initial.txt` e `results/endpoint-view-tests.txt`.
Reprodução: `lab/dualstack/run-endpoint-view-tests.sh`.

Revisão final do incremento contra o plano: consultas em lote, paginação,
identidade lógica e permissões preservadas; sem mudança de contabilidade.
Este checkpoint não inclui a busca administrativa `PeerSearch` nem seus
agrupamentos; ela é o próximo incremento. Permanecem os demais consumidores,
rollback original, clientes reais e benchmarks. Rust permanece no checkpoint
de exclusões; nenhum processo Rust é necessário para renderizar estas telas.

## Etapa 5 — busca administrativa e agrupamentos validados

`PeerSearch` passa a consultar endpoints com dualstack ativo. Sem agrupamento,
continua uma linha por peer; IPv4/IPv6 não multiplicam tráfego ou tamanho. Filtros
por endereço, porta e compartilhamento consultam a mesma origem, e compartilhamento
exige usuários distintos. Conectividade desconhecida tem filtro e contagem próprios;
endpoints vencidos não tornam o peer ativo ou conectável.

Agrupamento por sessão usa usuário, agente e peer ID entre torrents, preservando
a unidade lógica. Por usuário/sessão, as células de IP/porta mostram quantidades
distintas. Por IP, cada peer aparece uma vez naquele endereço; um dualstack pode
aparecer em dois grupos. Essa semântica está descrita na tela e não altera as
contagens globais, BON ou contabilidade. Queries agrupam dados no MySQL; apenas
os endpoints da página sem agrupamento são carregados para exibição.

Validação consolidada: **54 testes / 568 asserções**, sem skips, MySQL real e
Blade compilado. Inclui agrupamentos, filtro por IPv6 secundário, sockets,
estado desconhecido, expiração, retorno legado, renderização Livewire dos quatro
modos e exatamente seis consultas com 1 ou 50 peers na lista administrativa.
Somar tráfego/tamanho por usuário ou sessão não duplica famílias. A quantidade
constante de consultas não substitui medição de custo/latência em grande escala.

Falha inicial corrigida: `get_object_vars($this)` avaliava também a propriedade
calculada `peers` no PHP 8.4, provocando recursão. Substituído por opções explícitas.
A saída do primeiro teste ficou presa na formatação do stack; encerrado somente
o container de teste identificado, e as transações foram revertidas. A repetição
passou mantendo as asserções. Logs `results/admin-endpoint-initial.txt` e
`results/admin-endpoint-tests.txt`; runner `run-endpoint-view-tests.sh`.

Revisão final do incremento contra o plano: contabilidade agregada por peer,
leitura dos endpoints, modo legado preservado e limites de página. Sem divergência
de escopo identificada. Pendentes: consolidar validação dos consumidores
(reseed, graveyard, histórico, BON/seedtime e estatísticas), retorno às versões
originais, clientes BitTorrent reais e benchmarks. Não houve push ou produção.

Checkpoint anterior das telas locais PHP: `6d689c42f1d23df09289279d0505cb526ad52803`.

Checkpoint PHP da busca administrativa: `0ff60498700dcf1bb54577151f75501631164722`.
Rust segue em `4074ee4fba815a7e2dc9769f6d8f4e1cd41c9547`.

## Etapa 5 — critério pendente na validação dos consumidores

Após os testes das telas passarem, iniciado o próximo item, sem pedir nova
confirmação. `lab/dualstack/check-site-consumers.php` chama os controllers reais
de reseed e ressurreição e o job real de BON, com MySQL real, sempre dentro de
transação revertida. Chat, notificações e jobs externos são simulados; nenhum
aviso foi enviado. O script recusa banco diferente ou proprietário vigente.

Resultado: **18 verificações passaram, duas falharam; código de saída 1**.

- Nos quatro modos visuais, reseed é permitido com dois seeders únicos e recusado
  com três; todos os seeders podem ser somente IPv6. A preferência não altera
  a regra de negócio.
- Nos quatro modos, ressurreição é recusada com um seeder IPv6 e aceita com zero
  seeders num torrent com mais de 30 dias, enviado por outro usuário.
- Com endpoint vigente e conectividade positiva, a regra sintética de BON
  concede os 10 pontos esperados, uma vez por usuário/torrent.
- Depois de expirar somente o endpoint IPv4 positivo, mantendo IPv6 vigente com
  conectividade desconhecida, o job ainda concede **10 em vez de 0**. O cenário
  representa o intervalo entre o TTL vencer e a limpeza periódica atualizar a
  projeção agregada. A regra existente exige `connectable = 1`.

Causa observada: `AutoBonAllocation.php` usa `MAX(peers.connectable)` sem
revalidar endpoints vigentes; a visualização de ganhos também lê essa projeção.
A repetição com `external_tracker.is_enabled=false/true` falha igualmente porque
ambas as instalações usam esse mesmo job PHP. **Não foi um novo teste do processo
Rust**: este diagnóstico valida o consumidor SQL compartilhado do site.

Evidência integral e sanitizada: `lab/dualstack/results/site-consumers.json`.
O primeiro mock de chat não respeitava o retorno `static` de `systemMessage`;
corrigido para retornar a própria instância antes das asserções funcionais.
Todos os dados do ensaio foram revertidos; não restam containers de tracker.

A execução parou neste critério, seguindo a instrução do plano: “Se um critério
falhar, a execução deverá parar naquela etapa e apresentar a evidência”. Não foi
alterada a remuneração para contornar o resultado nem ampliado o escopo. O BON
por família continua fora da entrega obrigatória. O próximo ajuste necessário
é usar a conectividade de endpoints vigentes no BON existente e na exibição dos
ganhos, mantendo uma remuneração por usuário/torrent. Depois, completar os
consumidores restantes, rollback original, clientes reais e performance.

Os checkpoints de exclusões e telas estão confirmados; a feature completa
continua sem homologação. Nenhum push, publicação ou alteração em produção.

## Etapa 5 — BON vigente corrigido; concorrência ainda pendente

O usuário autorizou corrigir o problema anterior. `BonPeers` passa a fornecer
uma linha por peer e deriva `connectable` com `EXISTS` sobre a identidade completa
e endpoints positivos ainda vigentes. É usado por `AutoBonAllocation` e pelas
consultas de ganhos/contagem de regras em `UserEarnings`. A contagem de regras
também agrega conectividade por usuário/torrent antes de avaliar a condição,
evitando divergência numa regra `connectable = 0` com peers de estados distintos.
Modo legado, remuneração e preferência visual foram preservados; BON por família
continua fora da entrega. Nenhuma alteração no código Rust neste incremento.

Validação funcional na VM 120, PHP 8.4.26 e MySQL 8.0.46 isolado:

- **29 testes novos / 357 asserções**: expiração parcial nas duas direções,
  limite exato do TTL, TTL configurado, estados desconhecido/negativo, projeção
  legada desatualizada, vários peers e isolamento por usuário/torrent. Condições
  positivas e negativas, variável `connectable`, append/multiply, pagamento
  único, seedtime preservado e modo legado sem ler endpoints.
- Suíte consolidada de ganhos, endpoints, preferências e adaptador externo:
  **83 testes / 925 asserções**, sem skips. Tela Livewire renderiza e atualiza;
  número de consultas constante com um ou cinquenta peers. Blade compilado.
- Script original, com as mesmas asserções: **20 verificações aprovadas**.
  Antes eram 18 aprovadas e duas falhas. A evidência antiga foi preservada.
  Nos dois modos de configuração, o endpoint positivo expirado concede zero.
  Trata-se do consumidor PHP compartilhado, sem executar outro processo Rust.

Reprodução: `run-bon-tests.sh functional`; logs `results/bon-functional.txt` e
`results/site-consumers-fixed.json`. Ensaios funcionais revertidos por transação.

Foi acrescentado um ensaio regular de contencão real porque a atualização do
saldo passa a ler endpoints. Quatro processos do `TransitionWriter` reaplicam
24 transições em lotes de um, disputando três usuários e dois torrents; outro
processo roda cinco alocações BON. O teste força cinco esperas simultâneas em
locks de usuários e lê `INNODB_METRICS`, com `REPEATABLE-READ` e timeout de dez
segundos. É uma execução isolada própria, sem incluir esse gate vermelho nas
evidências verdes anteriores.

**Esse gate falhou e interrompe o avanço da etapa.** Os cinco processos terminam
com sucesso e os créditos são exatos: 800 bytes de upload e 100 BON por usuário,
seis peers, 12 endpoints e journal vazio. Entretanto, houve **27 deadlocks novos**,
sem timeout novo. A mesma carga com a consulta BON legada, mantendo os gravadores
dualstack atuais, registrou **22 deadlocks**, também com créditos exatos. Isso
demonstra que a disputa também existe sem a nova leitura de endpoints; não prova
ausência de regressão de custo nem representa um baseline completo das tags.

O último deadlock do controle legado mostra a inversão: uma transação segura
`users` exclusivo e espera `torrents` exclusivo; o `UPDATE users` do BON segura
`torrents` compartilhado e espera `users` exclusivo. Extrato sanitizado em
`results/bon-locks.json`. Logs dos gates `results/bon-contention.txt` e
`results/bon-contention-legacy.txt`, ambos com saída 1. Não reduzir a asserção
nem tratar retries bem-sucedidos como aprovação da contenção.

A preparação do teste concorrente reinicia apenas fixtures no banco
`unit3d_dualstack_journal_test`. Regras e saldos BON foram restaurados, lease
liberada e stream de teste limpo. Durante a construção do harness, corrigidos
IDs sintéticos que colidiam por padding à direita e revisão incorreta do probe
IPv6. O teste agora exige probes aceitos e verifica a preparação. A leitura de
`INNODB_TRX` não expôs as cinco esperas durante o ensaio; o contador real
`lock_row_lock_current_waits` as demonstrou, sendo usado no gate definitivo.

Próximo ajuste necessário: compatibilizar a aquisição de locks da alocação BON
com a persistência coordenada e repetir o mesmo gate, preservando o cálculo e
os créditos. Não houve mudança dessa estratégia neste checkpoint. Permanecem
demais consumidores/seedtime, retorno às versões originais, clientes reais e
benchmarks. Nenhum push ou alteração em produção.

Revisão final única contra o plano: a correção usa endpoints vigentes, mantém
identidade e pagamento únicos, modo legado e independência do Rust. Sem regras
BON por família ou alteração da fórmula. A divergência em relação à conclusão
esperada da etapa é o gate de locks ainda vermelho; não houve avanço para outra
etapa nem ampliação da correção para a estratégia de persistência.

Commits PHP: correção `8a364e652530806779b172d0ead9c16e9c068f4f`;
reprodução da contenção `c3923a82ca4c22111172ac7e29dc88f07fbf2175`.
Rust permanece em `4074ee4fba815a7e2dc9769f6d8f4e1cd41c9547`.
Checkpoint consolidado: `lab/dualstack/checkpoint-bon.json`.

## Retomada autorizada — eliminar a disputa de locks do BON

O usuário autorizou perseguir e resolver as pendências. Primeiro incremento:
separar a consulta agregada de ganhos do comando que incrementa saldos, dentro
da mesma transação MySQL. A leitura será um SELECT comum, paginado por usuário;
a escrita tocará apenas `users`, em lotes limitados e ordem crescente de ID.
Não mudar regras, arredondamento final, TTL, seedtime, quantidade de pagamentos
nem o mecanismo de retry da transação completa. Valores decimais não passarão
por float no PHP. O mesmo comando atende standalone, Rust e modo legado.

Verificação: repetir os dois gates existentes sem relaxar créditos nem métricas
de deadlock/timeout, testar saldo fracionário, limite entre lotes, rollback e
retry integral. Rodar a regressão funcional e a concorrência contra o gravador
Rust real. A referência conceitual é a leitura consistente sem locks do MySQL:
[manual 8.0](https://dev.mysql.com/doc/refman/8.0/en/innodb-consistent-read.html).
A evidência decisiva será a execução no MySQL 8.0.46 do laboratório.

Passando esse incremento, seguir para consumidores e seedtime, depois rollback,
clientes reais e desempenho. Uma falha de aceitação interrompe a respectiva
etapa para registro, sem dispensar o critério ou mudar o escopo silenciosamente.

## Retomada — disputa BON/gravadores resolvida

`AutoBonAllocation` separa o SELECT agregado do UPDATE. A consulta mantém regras
e elegibilidade anteriores; pagina no máximo 500 usuários por lote. A escrita
usa CASE com parâmetros decimais e `ORDER BY id`, tocando somente `users`.
Todos os lotes permanecem numa única transação com o retry anterior. Não há
commit parcial nem conversão monetária para float em PHP. O instante SQL usado
por regras de idade é capturado uma vez por tentativa, antes dos lotes.

Resultados no MySQL 8.0.46, isolamento REPEATABLE-READ, timeout de lock de 10 s:

- **90 testes / 978 asserções** funcionais, sem skips: 83/925 anteriores e
  7/53 novos. A nova suíte usa 501 usuários para cruzar a fronteira do lote,
  injeta falha depois da segunda escrita, comprova rollback integral e retry
  sem pagamento duplicado, testa decimais junto ao meio centavo e avança o
  relógio SQL entre lotes sem mudar a idade usada na remuneração.
- **20/20** verificações dos consumidores e templates Blade compilados.
- Concorrência PHP com leitura dualstack: **1 teste / 50 asserções**, cinco
  esperas forçadas, zero novos deadlocks e timeouts. Consulta legada: mesmo
  resultado. Cada usuário recebe 800 bytes de upload e 100 BON, uma única vez.
- Concorrência Rust/PHP: teste Rust real com quatro tarefas reaplicando as
  mesmas 24 transições em lotes de um, junto ao comando PHP real de BON.
  Zero novos deadlocks/timeouts; mesmos créditos; seis peers, 12 endpoints,
  backlog drenado e proprietário liberado. Nenhuma alteração de produção no Rust.

O harness Rust inicialmente esperava cinco escritores SQL simultâneos. Isso
estava incorreto: `Coordinator::persist_batch` serializa as quatro tarefas com
seu mutex de persistência, resultando em um escritor Rust mais o job BON.
O gate agora exige as duas esperas reais; ausência de novos deadlocks/timeouts
e créditos esperados não foram alterados. Evidência inicial preservada em
`results/bon-rust-harness-initial.txt`. O aviso preexistente de depreciação em
`stats.rs` não foi alterado neste incremento.

Evidências finais: `results/bon-lock-fix-contention.txt`,
`results/bon-lock-fix-legacy-control.txt`, `results/bon-lock-fix-functional.txt`
e `results/bon-rust-contention-fixed.txt`. Os logs vermelhos anteriores foram
preservados. As suítes que preparam fixtures confirmadas limpam seus dados e
restauram regras/saldos; executá-las somente no banco isolado. Nenhum push ou
produção. Esses ensaios não substituem o benchmark da população completa.

Revisão final única deste incremento: cálculo, atomicidade, precisão e modo
legado preservados; escritor BON sem joins do swarm; ordem dos usuários alinhada
aos gravadores. Sem divergência de escopo. Critério de concorrência aprovado;
liberado o próximo item de consumidores/seedtime.

Commits: PHP `58b7d804e4f25be738abca194be573864e09f3e5` e teste Rust
`773dff0c4c514c03d5eece4b2c39da916f2561a9`.
Checkpoint: `lab/dualstack/checkpoint-bon-locks.json`.

## Contrato compartilhado — histórico e seedtime

`fixtures/history-v1.json` agora é executada pelos gravadores reais PHP e Rust,
contra MySQL; PHP também usa Redis real. As 23 operações cobrem dois peers com
quatro endpoints, paradas parciais, repetição de stopped, reinício após parada
total, completed duplicado, probe, intervalo acima do teto de seedtime,
expiração independente e transição de leecher para seeder.

Ambos mantiveram um histórico por usuário/torrent, seedtime final de 251 segundos
e uma conclusão. Cada lote foi reaplicado sem efeitos adicionais. O PHP passou
com 258 asserções; Rust passou o mesmo contrato. Não foi necessário alterar os
gravadores. Evidência: `results/history-contract.txt`; execução reproduzível em
`run-history-tests.sh`, com proteção de banco exclusivo e proprietário parado.

Na preparação do harness, a expectativa inicial de conclusão foi corrigida:
um peer que já começa seeder não ganha conclusão por repetir completed. Também
foi corrigido o tipo de leitura Rust de `times_completed` para INT com sinal,
conforme o schema. Nenhuma mudança das regras para acomodar o teste.

Revisão final única do incremento: paridade de histórico, referência e seedtime
conforme plano; fixture compartilhada, sem dependência de execução entre
backends. Sem divergência. Não é um novo ensaio de restart ou performance.

Próximos consumidores confirmados: `AutoHighspeedTag` consulta só `peers.ip`;
o quadro de clientes do perfil também agrupa pelo endereço legado. Adaptar
para endpoints vigentes, preservando identificação lógica, permissões,
contagens e funcionamento legado; validar em MySQL e templates reais.

## Consumidores — seedboxes e clientes do perfil

`AutoHighspeedTag` passa a localizar o IP cadastrado em qualquer endpoint vigente
de um seeder ativo. Usa a identidade composta completa, respeita o TTL configurado
e não aproveita a projeção obsoleta. O cadastro continua por IP, sem adicionar
exigência de conectividade positiva ou vínculo ao dono do peer. No modo legado,
a consulta anterior por endereço é preservada. O SELECT e o UPDATE foram
separados: escrita só em torrents, em ordem de ID e lotes de 500, transação com
retry. Não modifica contadores, peers ou `updated_at`.

O perfil mostra uma linha por peer lógico/torrent com endpoints associados,
25 linhas por página e links às telas de peers. Expirados aparecem identificados;
um peer sem qualquer endpoint vigente não entra na lista ativa. Checagens
desconhecidas continuam desconhecidas, sem consulta ao cache legado. Proprietário
e moderação mantêm acesso; terceiros não carregam endereços. A moderação conserva
o link de pesquisa por cada IP. `peer_id` não é exposto na serialização. Modo
legado mantém agrupamento e template anteriores.

Validação MySQL 8.0.46:

- **118 testes / 1.215 asserções**, 20 checks adicionais e Blade compilado.
- Novos 20 cenários de seedbox: famílias, limite exato de TTL, projeção obsoleta,
  identidades distintas, inelegibilidade, cadastro inválido, modo legado e
  fronteira de 501 torrents; exclusão lógica e status preservados.
- Perfil renderizado com dados reais: paginação, privacidade, integração do
  controller e exatamente três consultas para 1 ou 50 peers, incluindo o HTML.
- Concorrência ampliada com o job real de seedboxes: quatro gravadores mais um
  consumidor, cinco esperas forçadas por cenário. BON e seedbox aprovados nos
  modos dualstack e legado: **4 testes / 202 asserções**, nenhum deadlock ou
  timeout novo, crédito e contagens corretos.

Evidências `results/site-final-functional.txt`, `site-final-contention.txt` e
`site-final-legacy-control.txt`. O runner funcional passa a incluir seedboxes;
o concorrente executa ambos os consumidores. Os testes confirmados restauram
saldos, regras, cadastros de seedboxes e marcações anteriores. Não houve nova
execução de concorrência Rust neste incremento; o gate Rust/BON verde anterior
continua registrado separadamente. Nenhuma homologação visual completa no browser.

Revisão final única: diff conforme os consumidores previstos, sem remuneração
por família, exposição de IP a terceiros ou mudança de regra de reseed.
Nenhuma divergência. Próximo gate: consumidores de histórico e estatísticas,
antes do retorno à versão original, clientes reais e benchmark.

## Ponto de parada — consumidores de histórico e estatísticas

O runner `run-site-consumer-tests.sh` executou os controllers e comandos reais
com IPv4, IPv6 e dualstack em MySQL 8.0.46. Notificações, fila de mensagens,
chat e HTTP foram substituídos por fakes/mocks: nenhuma comunicação enviada.
As consultas de estatística executaram com o driver síncrono do Laravel para
compartilhar a transação revertida; não é teste do dispatcher de processos.

Resultado: **6 casos aprovados, 6 reprovados, 108 asserções**, correspondentes
a dois defeitos repetidos nas três configurações de famílias:

1. `app/Http/Controllers/StatsController.php:358`: a consulta agrupada por
   prefixo seleciona também `agent`, que não participa do agrupamento. MySQL
   com `ONLY_FULL_GROUP_BY` recusa com erro 1055. As consultas anteriores de
   rankings de seeding/leeching mantiveram as contagens esperadas.
2. `app/Console/Commands/AutoRefundDownload.php:70`: para dois torrents de
   1.000 bytes elegíveis ao reembolso integral, o histórico registra 2.000
   reembolsados, mas `users.downloaded` vai de 10.000 para 9.000, em vez de
   8.000. O UPDATE de múltiplas tabelas não soma os deltas de todos os históricos
   na linha compartilhada do usuário. Não depende da quantidade de endpoints.

Ambos os arquivos são idênticos, byte a byte, aos da base 9.2.0. Blobs no commit
fixado `8b88f4c8182eb3d3912ffef425c3224dcfd596f4` e no candidato:

- AutoRefundDownload: `ef9cadfc9b8f9bf39c1a7f379457de1ab44badd9`.
- StatsController: `68d561ce1ad5a0da1c7762245439de8d51822f08`.

Isso confirma origem anterior à feature no código executado; não foi um novo
baseline integral da tag original. Nenhuma das duas rotinas foi modificada
neste incremento. Evidência completa: `results/site-history-consumers.txt`.

Os casos verdes cobrem recompensa única de ressurreição no limiar do seedtime,
mesmo com dois peers e quatro endpoints, repetição do job sem novo prêmio,
e reembolso de um único torrent sem duplicação. O primeiro harness de reembolso
não recompunha o grupo do usuário após outros ensaios e não gerava linhas
elegíveis; isso foi corrigido na fixture, com asserção explícita do join com
grupos, antes de registrar o resultado acima. As transações foram revertidas.

Revisão final única: testes conforme os consumidores previstos, sem edição
silenciosa de regra financeira. O gate permanece vermelho; não houve avanço
para rollback, clientes reais ou performance após essa falha, conforme o
critério de parada do plano. Checkpoints verdes anteriores continuam válidos.

Correção proposta para o próximo incremento, separada da feature:

- Estatísticas: retirar o campo `agent` da projeção do grupo por prefixo, onde
  ele não é consumido; preservar o agrupamento por versão na outra consulta.
  Cobrir versões distintas do mesmo prefixo, contagens únicas e SQL estrito.
- Reembolso: tornar atômicos os valores por histórico e a soma por usuário,
  sem variável de sessão SQL. Preservar elegibilidade, teto, arredondamento
  de bytes e limite inferior de saldo; ordenar locks de usuários/históricos
  de forma compatível com os gravadores. Testar vários torrents, arredondamento,
  reentrega, rollback/retry e contenção real nos dois backends. Não executar
  correção retroativa de saldos sem procedimento separado e dados do operador.

Commits verdes deste trecho: PHP `c7f442392` (seedboxes) e `7d25a2ac1` (perfil);
contrato de histórico PHP `966764c42` e Rust `1fdb80b`. O checkpoint seguinte
registra a reprodução dos defeitos legados, não uma entrega homologada.

## Incremento autorizado — correções legadas e concorrência

O usuário aprovou a correção das duas rotinas e pediu simulação de alta
concorrência. Executar a proposta acima, com transações de até 100 históricos,
paginação pela chave composta e locks na ordem usuários → históricos. Reavaliar
elegibilidade e referência sob proteção, somar deltas inteiros no MySQL e
confirmar saldo e históricos juntos. Cada lote confirmado é idempotente; uma
interrupção entre lotes exige reexecutar o comando. Usar retry limitado com
backoff somente para conflitos transitórios. Nenhuma correção retroativa.

Verificação: SQL estrito e versões do mesmo cliente; múltiplos torrents,
arredondamento, saldo mínimo, filtros, repetição, fronteira de lote e rollback;
MySQL real com barreira forçando competição entre gravadores e múltiplas cópias
do reembolso, métricas do motor e contabilidade final. Cobrir PHP e Rust.
Depois, ensaiar carga HTTP controlada sem/com reembolso no laboratório, medir
RPS oferecido e efetivo, latência, erros e drenagem. Concorrência no banco não
equivale a milhares de announces HTTP por segundo. Registrar limites medidos
sem declarar homologação do benchmark completo ou produção.

## Resultado — reembolso, estatísticas e carga concorrente

Implementadas as duas correções autorizadas. Estatísticas mantêm agrupamento
por prefixo e versão com SQL estrito. O reembolso usa paginação por chave,
transações de até 100 históricos, locks usuários → históricos, referência
reavaliada após os locks, soma decimal dos deltas por usuário e atualização
atômica do saldo/históricos. Não usa `@delta`, não cria SQL no announce Rust
e não modifica os gravadores de announce. Retry: até cinco tentativas por lote,
com backoff de 25/50/100/200 ms, depois de rollback. Repetição não reaplica crédito.

A meta acumulada arredondada para bytes inteiros é a mesma nos dois lados da
contabilidade. A fórmula e os filtros foram mantidos; não se preserva a diferença
de um byte que o arredondamento independente do saldo e do histórico podia
produzir. Nenhum saldo antigo foi reconciliado retroativamente.

Validação final no MySQL 8.0.46, REPEATABLE-READ, timeout de lock de 10 segundos:

- **31 testes / 276 asserções** funcionais: versões de cliente, famílias,
  ressurreição, vários torrents, meio byte, valores grandes, filtros,
  saldo mínimo, delta negativo, 201 históricos do mesmo usuário, rollback,
  retomada e esgotamento de retry.
- PHP: **16 processos SQL**, oito gravadores e oito cópias do reembolso,
  16 esperas simultâneas comprovadas, 600 transições e 4.800 persistências,
  160 execuções do reembolso. Teste final: **1 teste / 1.138 asserções**
  (o total inclui asserções de prazo no loop de espera). Contabilidade exata.
- Rust: quatro tarefas compartilham **um gravador SQL** do coordenador;
  junto a oito jobs PHP houve nove esperas SQL comprovadas. 480 transições,
  1.920 persistências, 160 reembolsos. Backlog zerado e contabilidade exata.
- Nenhum novo deadlock ou timeout nos ensaios aprovados. Evidências em
  `results/refund-final-tests.txt` e `results/refund-rust-contention.txt`.

Carga HTTP: 5 segundos de aquecimento e 20 de medição por perfil, 36 peers,
72 endpoints, dois torrents, alternância de origens IPv4/IPv6 reais,
`numwant=0` e `completed` repetido para exercitar deduplicação. O evento permite
pressionar a contabilidade sem desligar o intervalo de announce do PHP.
O reembolso foi executado repetidamente durante a carga; no primeiro perfil
com reembolso de cada backend houve desconto real, seguido de reentregas.

| Backend/perfil | Sem reembolso (req/s) | Com reembolso (req/s) | p95 sem/com (ms) | p99 sem/com (ms) |
|---|---:|---:|---:|---:|
| Rust, alvo 1.000 | 1.000 | 1.000 | 0,234 / 0,236 | 0,262 / 0,264 |
| Rust, alvo 2.000 | 2.000 | 1.999,95 | 0,250 / 0,251 | 0,293 / 0,297 |
| PHP, alvo 1.000 | 213,4 | 209,4 | 211,916 / 210,587 | 223,117 / 221,957 |

Todas essas seis medições tiveram zero erro e crédito final correto. No PHP,
o gerador atingiu seu limite de 36 requests em voo e não ofereceu o restante da
meta; os 209,4 req/s são requests efetivamente aceitos, não 1.000. O throughput
foi 98,13% do controle. O usuário informou que o criador reportava cerca de
250 req/s: é referência externa fornecida pelo usuário, não baseline medido
nestas VMs. Os nossos 213,4/209,4 ficam cerca de 15%/16% abaixo dessa referência,
sem conclusão de regressão entre ambientes diferentes.

Pico amostrado de announces reconhecidos ainda não persistidos: até 221 no
Rust a 2.000 req/s e 28/27 no PHP sem/com reembolso; sem crescimento sustentado
nessa janela curta e tudo persistido na conferência final. Essa estimativa não
é telemetria interna da fila e não mede sua janela de perda em crash. O campo
`drain_seconds` desses arquivos mede a conferência depois do encerramento do
amostrador (até aproximadamente 500 ms depois dos workers), não a latência
total desde o último request.

Falhas do harness preservadas: configuração Rust pediu lote 1.000, acima do
máximo 500, antes de abrir o coordenador; corrigida para lote 500/480 transições.
O primeiro gerador PHP concentrou todos os requests em dois IPs e recebeu 429
pelo limite existente de 500/minuto/IP. Foi substituído por 72 origens reais por
perfil, sem desligar o limitador. A taxa de 309,4 do log reprovado incluía
tentativas recusadas e **não representa capacidade de announces aceitos**.
Aliases e containers dos ensaios foram encerrados; testes só usaram o banco
isolado. O baseline original permanece intacto.

Esses ensaios verificam interferência e correção sob disputa. Não substituem
a matriz original versus candidato com datasets de 1k/54k/100k peers, três
repetições longas, listas de peers e seis horas de churn. Sem homologação de
milhares de req/s para o PHP nessa configuração. Permanecem pendentes rollback
para versões originais, clientes BitTorrent com transferência e benchmark
completo. Detalhes operacionais em `docs/dualstack-reembolso-concorrencia.md`.

Revisão final única do incremento: diff conforme a correção autorizada e seus
ensaios, sem alterações adicionais nos gravadores, limites de IP, BON ou schema.
As diferenças de alcance da validação estão explícitas acima; benchmark completo
permanece pendente. Commits PHP `c55e8a4fd` (estatísticas) e `b380d2f69`
(reembolso), Rust `cd52482` (teste de contenção). Checkpoint de coordenação inclui
procedimentos e resultados brutos. Sem push ou implantação em produção.

### Retorno ao legado e reconciliação — concluído neste incremento

Implementar a preparação offline do rollback e a reconciliação explícita da
projeção legada, inclusive em peers com `state_version > 0`. O backfill inicial
continua sem sobrescrever endpoints. Uma marca persistente em `tracker_ownership`
impede os dois coordenadores novos de adquirir o swarm entre a preparação e a
conclusão da reconciliação. Escritores originais não conhecem esse protocolo:
entrada fechada, drenagem e parada de processos continuam pré-condições operacionais.

A reconciliação será retomável, com lotes limitados e exclusão entre execuções.
Reconstrói endpoints, estado agregado, referência temporal e contadores; preserva
versões e contabilidade confirmada. Falha deixa a marca ativa. Não transfere
crédito, não limpa filas pendentes e não reinicia versões para esconder conflitos.

Validação deste incremento: MySQL/Redis reais para recusa de proprietário/fila
pendente, exclusão concorrente, interrupção e retomada, troca de IP legado,
expiração, idempotência e conservação de saldos/seedtime/conclusões; aquisição PHP
e Rust bloqueada durante manutenção. Depois, ensaiar as tags originais em cópias
isoladas no banco de teste, sem alterar o baseline, e retomar os novos backends.
O ensaio com binários originais é distinto dos testes de reconciliação e somente
será declarado concluído com evidência própria.

Implementado `dualstack:legacy prepare|reconcile --offline --batch=500` e migração
aditiva 000006. Os dois coordenadores recusam aquisição durante manutenção, sem
avançar a geração. Reconciliação em lotes pela PK, exclusão MySQL entre comandos,
checagem da posse da exclusão em cada transação (inclusive depois de reconexão),
preservação de versões/saldos/seedtime/conclusões e recálculo de atividade/contagem.
O backfill inicial mantém sua semântica anterior. Nenhum SQL foi acrescentado ao
caminho normal de announce Rust.

Validação final PHP: **40 testes / 593 asserções**, incluindo o journal e testes
novos de manutenção, recusa de filas, perda da conexão e retomada. O contrato Rust
MySQL passou com a nova recusa de aquisição e regressões de retry, deadlock,
restart e publicação em memória. A primeira rodada PHP foi 39/583; o teste
adicional de perda da conexão e a conectividade de inativos integram o resultado final 40/593.

Ensaio com `git archive` das tags originais, verificando os commits:

| Passo | Crédito acumulado | Endpoints depois da reconciliação/retomada |
|---|---:|---:|
| PHP novo prepara retorno | 100 | 2 |
| PHP 9.2.0 original, job e consumidores CLI | 200 | 1 |
| PHP novo retomado | 300 | 2 |
| Rust 0.3.1 original, HTTP com origem IPv4 real e SIGTERM | 400 | 1 |
| Rust novo retomado, announces nas duas famílias | 500 | 2 |

Referências e créditos confirmados permaneceram coerentes; reanunciar o mesmo
contador não gerou crédito. História financeira, seedtime, conclusões e versões
foram preservados na reconciliação. Containers encerrados; baseline preservado.

Houve duas falhas de configuração do harness: mountpoint `.env` ausente no arquivo
exportado (container nem iniciou) e header de proxy herdado no teste Rust direto
(`Internal tracker error` antes do processamento). Corrigidas no runner, sem mudar
os fontes originais; preflight e rodada final passaram. Não houve critério de
produto dispensado.

Procedimento, limites e reprodução: `docs/dualstack-rollback-legado.md`.
Checkpoint e evidências: `lab/dualstack/checkpoint-legacy.json` e
`results/legacy-{final-tests,php-roundtrip,rust-roundtrip}.txt`, além da resposta
HTTP `results/legacy-original-http.json`. O PHP original foi exercitado por CLI,
e a cadeia de rollback usou um peer: não equivale a throughput nem transferência
de arquivo BitTorrent. O contrato Rust integral teve saída observada no terminal,
sem transcript bruto salvo; esse limite está identificado no checkpoint.

Revisão final única: diff alinhado ao incremento autorizado de retorno e
reconciliação. Identificada e corrigida a projeção `connectable` de peers inativos
durante essa revisão; asserção acrescentada e suíte PHP aprovada novamente.
Limites de evidência explicitados acima; nenhum BON por família ou SQL por
announce Rust acrescentado. Próximos itens: clientes BitTorrent reais e matriz
completa de performance, além do fechamento documental dos consumidores do site.

Commits do incremento: PHP `8071ac42e`; Rust `859aa88`. O checkpoint de
coordenação registra os dois hashes completos, testes, procedimento e resultados.
Sem push ou implantação em produção.

## Pipeline de homologação — retomada autorizada

O usuário autorizou executar em sequência do menor ao maior custo, avançando
após aprovação. Uma falha deve ser investigada e uma correção localizada pode
ser aplicada e revalidada no mesmo ciclo. Mudanças de grande impacto exigem
evidências e apresentação das alternativas antes de escolher. Essa orientação
substitui a parada imediata usada nos incrementos anteriores.

Ordem operacional: (1) robustez e asserções do harness, (2) clientes reais PHP,
(3) paridade com clientes reais Rust e contabilidade final, (4) fechamento da
cobertura funcional do site, (5) preparação/calibração de carga, (6) matriz
original versus candidato, (7) ensaio de seis horas e janela de perda em crash.
As etapas demoradas só começam depois de validar as anteriores. Manter dados
originais, capturas privadas, versões fixadas e resultados separados por backend.

### Homologação funcional encerrada nesta retomada

- Limpeza do harness: cinco verificações em namespaces Linux reais, incluindo
  falhas durante provisionamento e preservação de recursos preexistentes.
- PHP standalone: oito casos aprovados em `php-20261008T144932`.
- Rust: os mesmos oito casos aprovados em `rust-20261008T145811`.
- Ambas as rodadas exigem as duas famílias no mesmo peer e na resposta, dados
  no caminho restante depois da falha, SHA-256, uma conclusão e crédito final
  igual ao maior contador observado menos a referência inicial. Após stopped,
  zero endpoints e contagens ativas. Backend/generation confirmados no SQL.
- O último announce do Transmission revelou buffering no tcpdump; captura
  imediata corrigiu a evidência. O caso original falhou, e a matriz completa
  passou depois, sem alterar os produtos nem dispensar a asserção financeira.
- Consumidores finais do site reexecutados: 31 testes / 276 asserções, 5,10 s.
  Somados à cobertura já registrada de preferência/API, endpoints/permissões,
  BON vigente, seedtime, estatísticas, reseed/graveyard e exclusões, encerram a
  pendência documental da etapa 5. Evidências anteriores continuam identificadas
  pelos checkpoints; não foram apresentadas como novas execuções.

### Calibração — perda no consumidor legado identificada e corrigida

Primeiro perfil válido: 1.000 peers, 100 torrents, 800 seeders anunciando e
200 leechers residentes, IPv4, `numwant=25`, 20 req/s, aquecimento de 30 s e
medição de 60 s. PHP 9.2.0 original aceitou 1.800 requests sem erros HTTP, mas
persistiu 180.000 bytes nas referências e 180.200 nos usuários, com quatro
históricos divergentes. A perda não foi atribuída ao dualstack.

Reprodução controlada com MySQL e Redis reais: inserir outro item na fila
depois do LRANGE e antes do LTRIM faz os comandos originais removerem ambos,
embora só tenham persistido o primeiro. Dois testes falharam na tag original.
O LTRIM removia até 4.062 itens, o tamanho máximo, em vez do número lido.

Correção localizada em `AutoUpsertPeers` e `AutoUpsertHistories`: remover
`count($peers)` / `count($histories)`. Dois testes / 18 asserções passaram,
inclusive após Pint. Nenhum schema, lock, política financeira ou caminho do
journal dualstack foi alterado. Não resolve a janela legado entre commit e
reconhecimento nem consumidores duplicados; o journal continua sendo a solução
de persistência da feature.

Controle adicional com tag original e somente esses dois consumidores
substituídos passou sob a mesma carga: 180.000 bytes em todas as referências,
históricos e saldos, zero divergências por usuário, zero jobs falhos e drenagem
em 5,03 s. p95 19,08 ms / p99 21,00 ms nessa calibração. O original permanece
intacto e seu resultado com perda fica separado do controle corrigido.
Evidência: `results/legacy-batch-loss.json` e testes na árvore UNIT3D.

Na preparação, os lockfiles foram conferidos: Composer igual após normalizar
fins de linha; Rust só tornou direta a dependência serde_json já travada,
sem atualizar versões/checksums de pacotes. Uma execução sem backend iniciado
foi descartada e o gerador passou a recusar essa condição antes da carga.
O flusher CLI recebeu SIGTERM explícito, pois a imagem FPM usa SIGQUIT por padrão.

Revisão do incremento localizado: diff corresponde à perda reproduzida e à
validação autorizada. A correção de consumidores legados é adicional ao núcleo
dualstack e está identificada separadamente. Benchmarks completos continuam
pendentes; este controle curto não aprova capacidade nem o limite de 10%.

### Clientes BitTorrent reais — parada IPv6-only (resolvida abaixo)

Executar na VM clientes isolada qBittorrent 4.6.3 e Transmission 4.0.5, registrando
as versões efetivas e a biblioteca libtorrent. Criar arquivo determinístico,
torrent privado sem DHT/PEX/LSD e clientes em namespaces com IPs próprios na rede
do laboratório. Usar somente o banco de ensaio, com Rust ausente no modo PHP.

Verificar descoberta via tracker, handshake BitTorrent, transferência e SHA-256,
IPv4-only, IPv6-only e dualstack, trocando os papéis dos clientes. Exercitar perda
de uma família durante transferência e comprovar continuidade na outra. Preservar
capturas brutas privadamente (contêm passkeys); exportar somente dados permitidos,
incluindo família, peer_id, evento, versão e deltas. Não injetar peers por RPC.

Erros de preparação do harness serão separados de falhas do produto ou limitações
dos clientes. Um critério funcional reprovado interrompe o avanço ao benchmark;
nenhuma transferência parcial ou announce sintético será apresentado como prova
de transferência real.

Implementado o harness `real-clients.py` e o adaptador RPC local `bt-rpc.py`.
Os produtos permaneceram nos commits PHP `8071ac42e` e Rust `859aa88`.
Resultados do PHP standalone, com arquivo determinístico de 16 MiB:

| Seeder → downloader | Rede | Resultado |
|---|---|---|
| qBittorrent → Transmission | IPv4-only | Handshake, transferência e SHA-256 aprovados |
| qBittorrent → Transmission | IPv6-only | Handshake, transferência e SHA-256 aprovados |
| Transmission → qBittorrent | IPv4-only | Handshake, transferência e SHA-256 aprovados |
| Transmission → qBittorrent | IPv6-only | Timeout 180 s, zero bytes, sem handshake |

No caso reprovado, o PHP respondeu HTTP 200, `complete=1` e um endpoint
`[fd42:756e:6974:92::40]:6881` em `peers6` (18 bytes). O seeder estava
persistido com um peer ativo, um endpoint IPv6 e `state_version=1`. O downloader
ficou em `stalledDL`; captura contém zero pacotes TCP para a porta 6881 e
tcpdump reportou zero descartes pelo kernel. A causa ainda não foi determinada;
não atribuir o resultado ao tracker nem a uma incompatibilidade geral IPv6.

Duas falhas de preparação anteriores foram corrigidas e preservadas nas
evidências: flag não suportada no qBittorrent e bind RPC IPv4 do Transmission
no namespace IPv6-only. São distintas da falha funcional que parou a matriz.
Versões efetivas: qBittorrent 4.6.3, Transmission 4.0.5, libtorrent 2.0.10,
TShark 4.2.2. Baseline preservado; nenhum cliente, namespace ou container do
tracker permaneceu em execução após a coleta.

Próximo passo delimitado: investigar aceitação do peer e seleção/conexão de
saída no qBittorrent/libtorrent nesse cenário. Só depois de corrigir a causa e
repetir os quatro casos, retomar dualstack, falha de família e Rust. Upload
final após encerramento dos clientes também não está homologado por estes
snapshots. Não houve avanço ao benchmark.

Revisão final única do incremento: harness e evidências conforme o escopo de
clientes reais; sem alterações nos produtos. Divergências de conclusão
registradas: cenário funcional bloqueado, casos dualstack/falha de família
definidos mas não executados, asserções específicas dos dois endpoints ainda
necessárias antes de aceitar esses casos, e recuperação de falha parcial na
preparação de namespaces não validada. Nenhum critério dispensado.

Procedimento e ponto de retomada: `docs/dualstack-clientes-reais.md`.
Checkpoint: `lab/dualstack/checkpoint-real-clients.json`. Resultados permitidos
em `lab/dualstack/results/real-clients/`; pcaps e logs com URLs ficam somente
na VM clientes. Sem push ou implantação em produção.

### Diagnóstico do bloqueio IPv6 — causa confirmada e regressão aprovada

Reproduzido o timeout de 180 s sem alterar o tracker. A API do qBittorrent
reconheceu o tracker e um peer recebido, sem filtro, proxy ou banimento. O
Transmission estava em seeding e respondeu a um handshake TCP/BitTorrent
diagnóstico independente pela mesma rede IPv6.

O rastreamento de syscalls do qBittorrent mostrou socket `AF_INET6`,
`SO_BINDTODEVICE` bem-sucedido para `bt0`, seguido de `bind(AF_INET, 0.0.0.0)`
com retorno `EINVAL`. Não chegou ao `connect()` com o seeder. O código fixado
do libtorrent 2.0.10 em `include/libtorrent/enum_net.hpp:166–224` confirma esse
ramo quando o nome de interface é usado; não foi falha do Transmission.

Controles no mesmo cenário: vínculo por nome mantém zero download; sem vínculo
por nome, ou com IPv6 local explícito, completa os 16 MiB com SHA-256 correto.
Restaurar o vínculo por nome reproduziu novamente o bind inválido. Nenhuma
rota padrão foi adicionada e as versões dos clientes foram preservadas.

O harness passou a deixar `current_network_interface` vazio dentro do namespace
que só tem loopback e `bt0`, sem acesso externo. Adicionado
`diagnose-client-ipv6.py`, com controles negativo/positivo e probe separado,
sem inserir peers nos clientes. Probe não vale como transferência da matriz.
O runner versionado foi executado em `original` e `unbound`; o controle de
IP explícito foi comprovado no protótipo anterior equivalente.

Depois de restaurar somente o banco de ensaio, os quatro casos funcionais
passaram: qBittorrent → Transmission e Transmission → qBittorrent, cada sentido
por IPv4-only e IPv6-only. Handshake, arquivo e hash corretos em todos eles,
sem probe na rodada funcional. Evidência `results/real-clients/php-20261008T142110/`;
diagnóstico e syscalls em `results/real-clients/ipv6-bind-cause.json` e
`diagnosis-*/`. Capturas e logs privados não foram exportados.

Esta retomada resolveu o bloqueio e verificou a regressão; não avançou para
dualstack simultâneo, falha de família, Rust ou performance. Próximo passo:
completar as asserções dos dois endpoints antes de executar os casos dualstack.
Produtos continuam em PHP `8071ac42e` e Rust `859aa88`, sem alterações.

Revisão final única: diff limitado ao bind do harness, diagnóstico reproduzível,
documentação e evidências. A correção não altera endpoint, protocolo, fonte de
IP ou contabilidade dos produtos. Controles com syscalls e regressão real
aprovados; scripts compilados e JSONs verificados. VMs de tracker sem containers
ativos, clientes sem processos/namespaces; dados do baseline preservados.
Sem push ou implantação em produção.

## Checkpoint da homologação em sequência

Retomada mais recente: 16 casos reais aprovados, fechamento financeiro completo
e cinco testes de limpeza do harness. Consumidores finais: 31/276 aprovados.
Detalhes na seção Pipeline de homologação e em docs/dualstack-clientes-reais.md.
Correção localizada da fila legada confirmada no commit PHP
6d8e7437daa652fb02519584c456b15dceacffa4. A calibração curta PHP original versus
candidato mantém os registros separados; a matriz completa ainda não foi aprovada.
Revisão única do harness de clientes contra o plano: asserções de identidade,
endpoints, transferência, integridade e crédito final cobertas; correções limitadas
a captura e ciclo de vida do laboratório. Sem push ou implantação em produção.

### Calibração de performance e decisão de maior impacto

PHP: 20 req/s, 1.000 peers distribuídos; original com falha de fila preservado,
controle legado corrigido e candidato com crédito correto. Candidato dentro
de 10% nesse perfil curto, sem conclusão sobre capacidade máxima.

Rust: 1.000 req/s, 90.000 requests por rodada. Distribuído em 100 torrents:
+3,33% no p95 e +4,17% no p99. Concentração em um torrent: +51,44%/+50,65%.
Investiguei com perfil de CPU e corrigi a passagem duplicada de contagem/seleção.
Commit Rust `4cb05fc`: suíte completa `dualstack_mysql` aprovada, com caso extra
de amostragem por peer e associação dos endpoints. Gate concentrado depois da
correção: +27,53%/+25,25%; continua reprovado. Contabilidade dos 1.000 usuários
correta, listas de 25 peers corretas e nenhum erro HTTP/perda do gerador.

Controle `numwant=0`, sem profiler, ainda apresentou +24,58%/+24,02%.
O índice atual por torrent exige buscar cada identidade no mapa global para
calcular totais a cada resposta. A opção recomendada para o próximo incremento
é investigar acesso direto ao estado dos peers pelo índice do torrent.
Isso alcança bootstrap, publicação, administração, retenção e exclusão; não foi
implementado sem a decisão solicitada pelo usuário para soluções de maior impacto.
Ganhos dessa alternativa ainda não estão medidos.

Não avançamos para populações 54 mil/100 mil, repetições longas, capacidade máxima,
churn de seis horas ou janela de perda abrupta. Também faltam os perfis curtos
de 50%/100% dualstack: a matriz funcional dualstack passou, mas isso não substitui
o benchmark dessas populações. Nenhum critério foi flexibilizado.

Procedimento, resultados, limites e impactos em `docs/dualstack-benchmarks.md`.
JSONs e amostras compactadas em `lab/dualstack/results/benchmarks/`; capturas de
CPU com pilhas permanecem privadas na VM. Produtos em checkpoints separados;
sem push ou produção. Laboratório drenado ao concluir esta rodada de diagnóstico.

### Índice direto validado e investigação do SSD

Autorização recebida para investigar o ganho do índice direto e a hipótese de
limitação de I/O no SSD compartilhado. Rust `a9ab263` mantém um estado por peer
em mapa por torrent e identidades ordenadas para manutenção/consulta por usuário.
Contratos MySQL, exclusão, concorrência, recuperação, rede e índice passaram;
PHP permaneceu em `6d8e7437`. Revisão final do produto sem divergência do incremento.

Calibração IPv4 concentrada: p95/p99 0,257212/0,289764 ms, ganho de
14,75%/13,82% frente ao candidato anterior. Original repetido:
0,242375/0,281989 ms. Gate curto aprovado (+6,12%/+2,76%).

50% dualstack: gate de latência reprovado. A instrumentação separou leitura
da resposta e validação local; mesmo sem asserções no tempo de leitura, a
diferença permanece acima de 10%. Drenagem do harness agora exige todas as
versões, além do saldo. Última rodada: 90.000 transições confirmadas, 1.500
endpoints, 6.000.000 bytes, nenhum erro/perda/divergência.

I/O observado na VM dados e no Proxmox: nenhuma saturação sustentada nessa
carga de 1.000 req/s; buffer pool de 128 MiB, durabilidade preservada. O candidato
gera ~3,6 vezes mais escritas/s que a tag original. O índice reduziu latência
sem reduzir esse custo. Regravação por delete/insert dos endpoints é uma
hipótese localizada para investigar em incremento separado.

Probe sem HTTP/SQL no trecho medido: seleção com 25 peers passa de mediana
~8,5 µs (torrent de 1.000) para 445–470 µs (54.000). Sem listas, ~6,2 µs para
354–364 µs. Confirma custo da varredura em memória, não desempenho HTTP ou I/O
de 54 mil peers. Recomendação e impactos da próxima mudança maior: contadores
incrementais, expiração indexada com memória limitada e seleção por elegibilidade.
Ainda não implementada; exige decisão conforme a orientação do usuário para
mudanças de maior impacto. Não flexibilizar TTL ou gate de 10%.

Evidências e procedimento em `docs/dualstack-benchmarks.md`,
`lab/dualstack/results/rust-index/` e `checkpoint-benchmarks.json`.
Gate misto bloqueia avanço da homologação; perfil de 100%, cargas HTTP grandes,
repetições longas, capacidade e seis horas continuam pendentes. Encerramento
conferido: tracker parado, lease liberada, aliases removidos, nenhum namespace,
saldo/versões corretos. Sem push ou produção.

### Validação complementar autorizada, sem nova otimização

O usuário pediu validar os resultados antes de decidir o próximo incremento.
Manter Rust `a9ab263` e PHP `6d8e7437`, durabilidade e parâmetros de carga.
Não implementar contadores incrementais nem alterar a persistência nesta rodada.

Sequência diagnóstica:

1. Repetir original/candidato com 1.000 peers e 50% dualstack, incluindo controle
   `numwant=0`, medindo leitura da resposta e validação local separadamente.
2. Repetir o perfil com lista de 25 em três pares, alternando a ordem para
   observar dispersão e influência da sequência no host compartilhado.
3. Medir 54 mil peers distribuídos e concentrados com o mesmo volume de requests,
   observando pressão de I/O, leituras físicas, fila de persistência e recursos.
   Esses casos investigam a reprovação, sem liberar os gates da homologação.
4. Verificar todos os saldos, identidades e versões; registrar divergências e
   investigar antes de ampliar carga. Comparar resultados e recomendar o próximo
   incremento com seus limites explícitos.

Usar o mesmo banco descartável, restaurado entre rodadas, origens reais e
observadores equivalentes. O runner deve recusar um tracker já ativo, limitar
carga/duração, preservar evidências de falha e drenar o backend no encerramento.
Não alterar os produtos. Ao final, remover aliases e confirmar lease liberada.

Desvios encontrados durante a validação complementar:

- O runner precisava esperar explicitamente o listener das duas famílias após
  o bootstrap. Espera limitada adicionada ao harness; tentativa falha preservada.
- O bootstrap concentrado de 54 mil peers excedeu 120 s. A consulta de
  reconciliação continuou no MySQL depois da saída do Rust e examinou mais de
  um bilhão de linhas. Cancelada somente sua conexão no banco de laboratório;
  o mesmo código/base iniciou em 1,9 s na repetição. Os planos/estatísticas
  precisam de tratamento próprio; não aumentar o timeout como suposta correção.
- A continuação diagnóstica prepara estatísticas da fixture antes de ambos os
  backends, com opção explícita e evidência separada. Isso não aprova a robustez
  do bootstrap nem permite avançar automaticamente para a homologação longa.
- O controle original com flush de 100 ms distingue frequência de gravação da
  diferença de modelo. Original usual: 3 s; coordenador candidato: 100 ms.

Fechamento dessa sequência: 13 ensaios de carga, 1.170.000 requests aceitos,
540.000 versões candidatas confirmadas, nenhum erro/drop/divergência ou novo
deadlock/timeout de lock durante a carga. Gate curto distribuído de 54 mil
aprovado; concentrado reprovado (+235,68%/+214,67% no p95/p99). O controle
original com flush de 100 ms produziu IOPS semelhantes ao candidato, que ainda
gerou cerca de 2,95 vezes mais redo. Nenhuma alteração adicional nos produtos.

Próxima decisão: corrigir a robustez da reconciliação/cancelamento do bootstrap
antes de otimizar contagem/seleção incremental. A preparação de estatísticas do
ensaio não resolve essa pendência do produto. Matriz longa não iniciada.
Resultados completos em `docs/dualstack-benchmarks.md:422` e
`lab/dualstack/results/rust-validation/`. Laboratório drenado, aliases removidos,
lease inativa e nenhum SQL de bootstrap remanescente. Sem push ou produção.

### Continuidade: bootstrap corrigido e validado

Após o incremento do escritor (`docs/dualstack-writer.md`, Rust `9446bfd`),
a pendência de reconciliação/cancelamento foi tratada conforme
`docs/plans/2026-10-08-bootstrap-rust.md`. Rust `9e8b546`, PHP preservado em
`6d8e743`: consulta agregada por identidade e cancelamento confirmado no MySQL.
Seis cenários, 18 inicializações, até 100 mil peers/200 mil endpoints, sem
ANALYZE corretivo. Inicialização máxima de 3,38 s, sem divergência contábil.
Regressões de MySQL, PHP, handoff, exclusão, histórico e reembolso passaram.

Checkpoint e evidências em `docs/dualstack-bootstrap.md` e
`lab/dualstack/checkpoint-bootstrap.json`. Esta aprovação fecha a pendência
específica de bootstrap. Continuam separados a comparação formal com as tags,
a janela de perda abrupta/memória sob rotação, proxy/TLS/probes e as seis horas.
O orçamento de armazenamento deve ser conferido antes das campanhas extensas.

### Continuidade: controle curto de queda abrupta

Depois do bootstrap, dois ensaios HTTP controlados executaram quatro SIGKILLs
do Rust, antes/depois do commit, e quatro reinicializações com expiração natural
da lease. Crédito confirmado preservado; 100 transições pendentes perdidas em
cada queda com escritor bloqueado; contador cumulativo seguinte recuperou o delta
uma vez. Nenhuma mudança adicional nos produtos. Evidências e limites em
`docs/dualstack-falha-abrupta.md` e `lab/dualstack/checkpoint-rust-crash.json`.
Isso fecha o controle funcional, sem substituir a medição da janela sob carga.

### Continuidade: TLS/proxy e memória/cache

Ordem priorizada pelo usuário: concluir TLS/proxy e memória/cache antes da carga.
Ambos os backends passaram nos 19 controles de HTTPS/proxy/probes e em 2.048
trocas reais de IPv6/porta por peer, com crédito único e dois endpoints. O teste
encontrou e corrigiu o middleware de proxy PHP desativado no kernel; confiança
somente em proxies explícitos, preservando o modo legado. Regressões: 39 testes
PHP (493 verificações) e 19 Rust. Rust permanece em `9e8b546`.

Cache de conectividade limitado; o estado por IP do limitador PHP expirou pelo
TTL natural, sem limpeza manual. Controle adicional Rust de produto: 256 trocas;
controle PHP do limitador: 512 trocas e 130 s ociosos. Relatório/checkpoint:
`docs/dualstack-tls-memoria.md` e `lab/dualstack/checkpoint-tls-memory.json`.
Laboratório drenado, sem aliases/regras temporárias ou proprietário ativo.
São ensaios curtos: a matriz formal de carga, janela de perda sob carga, memória
por população e seis horas continuam separados. Nenhum push ou produção.

### Continuidade: armazenamento para a campanha de seis horas

Preparação autorizada e concluída em 08/10/2026: VirtioFS já instalado no host,
três datasets exclusivos com quota/reserva agregada de 300 GiB. Binlogs fechados
são copiados, conferidos e sincronizados antes de purga SQL; banco/redo/binlog
ativo permanecem no SSD. Livre na VM de dados: 7,62 → 26,00 GiB.

Montagens e timer testados após reiniciar as três VMs. Oito testes e quatro
controles reais de falha/reexecução passaram; contabilidade e peers preservados.
Sonda concorrente: 30 mil commits, zero erros e throughput preservado; p95
mediano +0,55 ms/+12,44%, a validar com carga real antes de seis horas.
Relatório: `docs/dualstack-armazenamento.md`; checkpoint:
`lab/dualstack/checkpoint-storage.json`.

Não iniciou campanha longa, não alterou PHP/Rust e não fez push. Próximos gates:
gerador com RAM limitada, monitor de espaço/backlog em execução e ensaio curto
da aplicação com arquivo ativo. Este incremento não aprova performance formal.

