# Laboratório dualstack

## Estado da entrega de 10/10/2026

O roteiro atual é o [README da coordenação](../../README.md), com
[resultados consolidados](../../docs/resultados-consolidados.md) e
[reprodução](../../docs/testes-e-reproducao.md). O bootstrap foi corrigido,
o candidato Rust e o original completaram seus ensaios de seis horas, e o
A1/B/A2 de cache foi concluído. A matriz comparativa completa e a campanha
geral de capacidade permanecem incompletas; B não está incorporado ao produto.

As seções abaixo preservam a preparação e os checkpoints históricos.
`checkpoint-benchmarks.json` registra uma etapa intermediária, não o estado
global final. IPs/caminhos/IDs de VM precisam ser revisados num novo laboratório.
Não executar os runners contra serviços de produção. O pacote distribui
snapshots de fontes sem `.git` interno; helpers que exportam commits históricos
precisam de uma cópia de desenvolvimento separada ou dos arquivos de `packages/`.

O levantamento de [densidade por torrent](../../docs/dualstack-densidade.md)
trata 250 peers por torrent como referência operacional fornecida pelo usuário.
População total, concentração e taxa de requests são dimensões separadas;
concentrações maiores são exploração informativa, não novos gates do produto.

Ambiente exclusivo deste projeto: VMs 120 (tracker), 121 (dados), 122 (clientes).
Cada VM tem 4 vCPU e 8 GiB; discos 24/16/12 GiB. Rede isolada `vmbr92`,
IPv4 `172.29.92.0/24`, IPv6 `fd42:756e:6974:92::/64`. O acesso administrativo
usa DHCP em `vmbr0`; não fixar os endereços DHCP como identidade das VMs.

O manifesto fixa fontes e recursos; `images.env` fixa imagens. O PHP usado nos
pares original/candidato deve ser **o mesmo image ID**, registrado nos resultados.
Reconstruções podem receber pacotes Debian ou PECL diferentes; não misturar uma
reconstrução com o baseline antigo. Nesse caso, executar um novo par completo.

## Preparação

1. Inventariar Proxmox, memória, disco, bridges e IDs. O script recusa IDs ocupados
   e bridges sem a identificação deste laboratório.
2. Copiar `provision-proxmox.sh`, `manifest.json` e a **chave pública** de acesso
   para `/root/unit3d-dualstack` no Proxmox; executar o script como root.
   Não copiar chaves privadas para as VMs ou para o repositório.
3. Esperar `/var/lib/cloud/unit3d-dualstack-ready` em cada VM. Descobrir os IPs
   administrativos pelo guest agent, não pelo nome de outra máquina.
4. Copiar os arquivos de laboratório para `/opt/unit3d-dualstack/lab` em cada VM.
   Executar `prepare-data.sh` nos dados. Transferir `database.env` por SSH para
   tracker/clientes, com modo 600, sem imprimir seu conteúdo.
5. Executar `prepare-tracker.sh`, depois `initialize-baseline.sh` no tracker.
   Instalar `python3-pymysql` na VM de clientes. Transferir o fixture privado
   `/opt/unit3d-dualstack/private/fixture.json` para os clientes, modo 600.
6. Confirmar conectividade de clientes para o tracker nas duas famílias.

A bridge isolada é transitória e as VMs têm `onboot=0`. Após reinicializar o host,
recriar a bridge com o mesmo nome e alias `unit3d-dualstack` antes de ligar as VMs.
Não reexecutar o provisionamento para adotar IDs existentes. O script habilita
`snippets` em `local` preservando os tipos anteriores; o valor anterior fica no
host em `local-storage-content.before`. A imagem Ubuntu usada tem SHA256
`6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2`.

## Baseline funcional

No tracker: `sudo bash /opt/unit3d-dualstack/lab/start-baseline.sh php`.
Nos clientes:

```sh
python3 /opt/unit3d-dualstack/baseline.py --mode php \
  --fixture /opt/unit3d-dualstack/fixture.json \
  --database-env /opt/unit3d-dualstack/database.env \
  --output /opt/unit3d-dualstack/results/baseline-php.json
```

Encerrar com `stop-baseline.sh`, que retira a entrada antes dos consumidores e
faz o flush final. Executar `reset-baseline.php` no container PHP com os mounts
`repos/UNIT3D:/app` e `lab:/lab:ro`. Esse reset exige o banco e os usuários do
fixture, filas vazias e ausência de jobs falhos. Depois iniciar `rust` e repetir
o comando dos clientes usando `--mode rust` e outro arquivo de saída.

O gerador usa origem IPv4/IPv6 real e aguarda sete segundos entre snapshots,
acima dos flushes de cinco e três segundos. O proxy do Rust sobrescreve o header
de origem; o binário escuta apenas em loopback. FPM também escuta em loopback.
MySQL/Redis e listeners HTTP escutam apenas na rede do laboratório.

A entrada e os IDs são determinísticos; intervalos aleatórios das versões
originais, tempos de execução e endereços administrativos podem variar.
O JSON publicado contém apenas IDs sintéticos, IPs de laboratório, eventos,
respostas decodificadas e snapshots de contabilidade. Não publicar os arquivos
`.env`, `fixture.json` nem logs que possam conter passkeys.

## Resultado da etapa 1

Executado em 8 de outubro de 2026 UTC (7 de outubro no fuso do usuário).
PHP 8.4.26; Rust 1.99.0; MySQL 8.0.46, REPEATABLE-READ, lock wait 10 s;
Redis 7.2.16. Lockfiles das tags preservados. O Rust emitiu apenas um aviso
de API depreciada em `src/stats.rs:226`; não foi alterado.

| Observação | PHP original | Rust original |
|---|---|---|
| Segundo `started`, após 14 s | Recusa por intervalo | Troca o endereço, responde listas/contadores vazios |
| `completed` na segunda família | Substitui IP, mantém uma linha | Substitui IP, mantém uma linha |
| `stopped` na família anterior, porta 0 | Peer inteiro inativo | Peer inteiro inativo |
| Crédito após 1.000 → 1.100 → 1.200 | 200 bytes | 200 bytes |
| Jobs falhos | 0 | 0 |

Ambas as ordens, IPv4→IPv6 e IPv6→IPv4, produziram esses resultados.
Evidências: `results/baseline/baseline-{php,rust}.json`. Verificação reproduzível:
`python3 lab/dualstack/verify-baseline.py` a partir da raiz de coordenação.

Isso aprova somente a reprodução funcional do diagnóstico original.
Não aprova dualstack, concorrência, recuperação, clientes reais ou performance.
Os ensaios de carga de announce e soak continuam pendentes; 54 mil peers e
27–98 ms citados pelo operador não são medições deste laboratório.

## Validação do schema e ponto de parada

Depois de aplicar a migração aditiva, executar no tracker:

```sh
docker run --rm --network host -e DUALSTACK_MYSQL_TESTS=1 \
  -v /opt/unit3d-dualstack/repos/UNIT3D:/app unit3d-ds-php:baseline \
  vendor/bin/pest tests/Integration/DualstackSchemaTest.php --colors=never
```

A fixture corrigida passou: 8 testes e 38 assertions. O checkpoint anterior,
com falha de preparação, permanece registrado em `results/schema/schema-tests.txt`.
O resultado corrigido fica em `results/schema/schema-tests-resumed.txt`.

Para DDL interrompido, executar `prepare-schema-test.sh` na VM de dados e depois:

```sh
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_schema_test \
  -v /opt/unit3d-dualstack/repos/UNIT3D:/app \
  -v /opt/unit3d-dualstack/lab:/lab:ro unit3d-ds-php:baseline \
  php /lab/validate-schema.php
```

O script recria apenas o schema de ensaio, cujo nome é validado antes de escrever.
Ele nunca deve receber o banco do baseline ou de uma instalação real como destino.
O sucesso exige o relatório JSON completo: sete fronteiras de retomada e dois
backfills. Não aceitar somente exit code: o handler Laravel pode imprimir uma
exceção sem tornar o código de saída diferente de zero.

**Falha histórica, corrigida na retomada de 8 de outubro:** FK e índices ficaram ausentes depois
da interrupção na criação de `peer_ips`. Catálogo e DDL observados estão em
`results/schema/ddl-recovery-evidence.json`. A correção passou nas sete fronteiras
de DDL e nos dois backfills de 54 mil peers. Evidências atuais:
`results/schema/schema-final.txt` e `results/schema/schema-recovery-fixed.txt`.

## Núcleo e journal PHP — etapa 3 em andamento

O contrato compartilhado está em `fixtures/peer-v1.json`; definir
`DUALSTACK_PEER_FIXTURES=/lab/peer-v1.json` ao executar
`vendor/bin/pest tests/Integration/DualstackPeerContractTest.php` com a fixture
montada nesse caminho. O PHP passou em 13 testes e 251 assertions; Rust pendente.

Na VM de dados, executar `prepare-journal-test.sh`. Além de criar o banco
exclusivo, esse script concede PROCESS ao usuário do laboratório para consultar
deadlocks/timeouts em `INNODB_METRICS`. Não aplicar essa concessão em produção.
Na VM tracker, copiar `initialize-journal-test.php` para a pasta de scripts e:

```sh
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
  -v /opt/unit3d-dualstack/repos/UNIT3D:/app \
  -v /opt/unit3d-dualstack/lab:/lab:ro unit3d-ds-php:baseline \
  php /lab/initialize-journal-test.php
docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
  -e DUALSTACK_JOURNAL_TESTS=1 \
  -v /opt/unit3d-dualstack/repos/UNIT3D:/app unit3d-ds-php:baseline \
  vendor/bin/pest tests/Integration/DualstackJournalTest.php --colors=never --stop-on-failure
```

A preparação recria somente o banco de teste, copia fixtures sintéticas do
baseline e aplica as três migrações aditivas. A suíte exige esse nome de banco,
MySQL, REPEATABLE-READ e lock wait 10 s. Sem opt-in, informa skip explícito.
Resultado atual: **9 testes e 126 assertions**, incluindo quatro produtores e
dois consumidores PHP, rollback pré-commit, reentrega pós-commit, troca de geração
e expiração parcial. Logs em `results/journal/`; o ensaio inicial de métricas
com erro de instrumentação foi mantido junto do resultado corrigido.

O ensaio inicial acima foi ampliado para **15 testes e 239 assertions**, incluindo
probes TCP reais e retenção. Para executar esses casos, acrescentar
`DUALSTACK_TEST_BIND_IPV4=172.29.92.10` e
`DUALSTACK_TEST_BIND_IPV6=fd42:756e:6974:92::10` ao container na VM tracker.
Resultado: `results/journal/journal-php-fencing.txt`.

O HTTP foi conectado e passou em **30 passos**, incluindo quatro clientes HTTP
concorrentes, rotação de IPv6 por origem real e o limite de uint64. Iniciar com
`start-candidate-php.sh fresh` e encerrar com `stop-candidate-php.sh`. O modo
`resume` mantém o banco. Na VM cliente, preparar a origem secundária com
`prepare-client-rotation.sh` antes de executar:

```sh
python3 /opt/unit3d-dualstack/candidate-php.py \
  --fixture /opt/unit3d-dualstack/fixture.json \
  --database-env /opt/unit3d-dualstack/database.env \
  --output /opt/unit3d-dualstack/results/candidate-php-http-extended.json
```

Resultados em `results/standalone/`, incluindo restart, encerramento e 27
transições confirmadas sem passkeys. O serviço usa `APP_ENV=local` e SIGTERM;
`testing` desativa a captura de sinais no Laravel e não serve para esse ensaio.
`php-fpm.conf` exclui URI do access log. O primeiro teste HTTP com saldo inicial
copiado do baseline e seus resultados foram preservados para rastreabilidade.

### Falhas reais e sobreposição

O journal foi ampliado para **24 testes / 449 assertions**, sem skips, no mesmo
comando acima. Inclui seis ordens de announce/expiração/stop, três produtores
simultâneos e SIGKILL do consumidor antes do commit e depois dele, antes do ACK.
Resultado: `results/journal/journal-php-crash-overlap.txt`.

Para o ensaio de indisponibilidade, copiar `fault-announce.py` para a pasta base
da VM clientes e `fault-state.php` para `lab/` da VM tracker. No host que possui
a chave SSH, com os containers de tracker encerrados:

```sh
python lab/dualstack/fault-services-php.py --ssh-key CAMINHO_DA_CHAVE \
  --output lab/dualstack/results/standalone/candidate-php-service-faults.json
```

O script valida os três hostnames, inicia uma fixture nova somente no banco de
ensaio, pausa o coordenador para produzir uma transição pendente e interrompe
MySQL/Redis separadamente. Verifica recusa HTTP, recuperação em nova geração,
reenvio sem crédito extra e drenagem. Em falha, restaura o serviço de dados,
fecha a entrada e preserva containers/filas para diagnóstico. Não exporta corpo
HTTP, mensagens de drivers ou logs brutos. Resultado atual: **29 passos aprovados**.

Redis usa stop com sincronização do AOF; esse ensaio não mede a perda possível
de comandos ainda não sincronizados em um desligamento abrupto do host.
Clientes BitTorrent reais, paridade Rust, handoff, rollbacks e benchmarks
continuam pendentes. Consulte o documento de progresso antes de retomar.

### Contrato Rust e comparação completa com PHP

Copiar `run-rust-contract.sh`, `export-peer-contract.php` e a pasta `fixtures/`
para `lab/` na VM tracker, junto dos fontes atuais dos dois repositórios.
Executar `sudo bash /opt/unit3d-dualstack/lab/run-rust-contract.sh` nessa VM.
O teste de contrato é opt-in; o script usa `--include-ignored` e exige a fixture.
Os dois traces serão gravados em `/opt/unit3d-dualstack/results/`. Depois de
copiá-los para os resultados versionados, executar no host:

```sh
python lab/dualstack/compare-peer-contract.py \
  --php lab/dualstack/results/contract/peer-contract-php.json \
  --rust lab/dualstack/results/contract/peer-contract-rust.json \
  --output lab/dualstack/results/contract/parity.json
```

Resultado: cinco testes Rust aprovados, 12 casos / 51 operações e igualdade de
todos os campos exportados. Isso valida apenas o núcleo puro. O handler HTTP,
as filas e a persistência Rust ainda precisam ser integrados e validados.

### Coordenador Rust com MySQL — correção de timestamps

`run-rust-mysql.sh` executa a suíte `dualstack_mysql` na VM tracker, usando
o arquivo privado `database.env` como ambiente do container. O script recusa
containers do tracker e o teste exige o banco `unit3d_dualstack_journal_test`,
REPEATABLE-READ e lock wait 10 s. A fixture desse banco deve estar preparada.

**Resultado atual: suíte aprovada, com oito blocos em um teste de integração.**
Ver `results/rust/mysql-timestamp-regression.txt` e o snapshot somente leitura
`results/rust/mysql-after-timestamp-fix.json`. A falha anterior de codec e os
obstáculos intermediários do ensaio permanecem registrados nos outros logs.

TIMESTAMP usa `DateTime<Utc>`; DATETIME de conclusão preserva `NaiveDateTime`.
Foram verificados reentrega, restart, geração, stop parcial, backlog, rollback,
quatro threads/401 transições sem SQL durante publish, expiração, limite de
peers, uint64 e restauração de timestamps preenchidos com seedtime/conclusão.
A injeção SQL usa um CHECK temporário no banco isolado, sem permissões globais;
o teste remove esse CHECK antes de validar o rollback. Não usa CREATE TRIGGER.

`inspect-rust-checkpoint.py` na VM clientes confirma que o ensaio encerrou com
lease liberada e sem trigger/CHECK residual. Nenhum tracker ficou ativo.
O coordenador continua desacoplado do HTTP. A etapa 4 ainda exige cobertura de
falhas/lease/handoff e integração, conforme o documento de progresso.

### Falhas Rust e troca PHP/Rust

A suíte Rust agora cobre 17 blocos, incluindo timeouts, deadlock real e supervisor.
Ver `results/rust/mysql-failures.txt`. Para reproduzir a troca completa, copiar
`run-handoff.sh`, `apply-handoff-schema.php`, `handoff-php.php`,
`initialize-journal-test.php` e `run-rust-mysql.sh` para `lab/` na VM tracker,
com os fontes atuais. Executar `sudo bash /opt/unit3d-dualstack/lab/run-handoff.sh`.

O script exige tracker parado, aplica a migração de confirmação de drenagem,
executa as suítes PHP/Rust e recria somente o banco de ensaio entre elas. A troca
recusa duas mensagens PHP pendentes, recupera com PHP e alterna os coordenadores
nos dois sentidos. O preflight impede recriar o banco se o journal desse ensaio
ficou pendente em execução anterior; primeiro recuperar/drenar essa execução.
Resultados: `results/rust/handoff-initial.txt`, `mysql-after-handoff.json` e
`results/journal/handoff-php-full.txt` (27 testes, 474 asserções, sem skips).
São ensaios diretos dos coordenadores; o HTTP Rust permanece pendente.


### Handler HTTP Rust e restart

Com os fontes atuais, copiar `start-candidate-rust.sh` e
`run-rust-network-tests.sh` para `lab/` na VM tracker. Executar os testes do
binário e então `sudo bash /opt/unit3d-dualstack/lab/start-candidate-rust.sh fresh`.
O modo `fresh` recria somente o banco isolado; `resume` conserva seus dados.
O script deriva um env privado, permite apenas redes privadas do laboratório,
usa intervalo mínimo zero neste ensaio e desativa os probes TCP.

Na VM clientes, executar `candidate-php.py --backend rust` com os mesmos
argumentos `--fixture`, `--database-env` e `--output` usados no PHP. O nome do
arquivo foi preservado para manter a reprodução anterior; o gerador agora é
compartilhado e mantém todas as asserções originais. Resultado: 30 passos aprovados.

`rust-http-lifecycle.py` usa esses argumentos mais `--checkpoint` e `--phase`.
Executar `before`, parar o container com SIGTERM, conferir código 0, executar
`stopped`, iniciar o mesmo container e executar `resumed`. Resultado: estado
restaurado, nenhum crédito repetido e delta adicional de 100 confirmado uma vez.
`test-rust-second-owner.sh` exige o primeiro processo ativo e confirma a recusa
do segundo. Ao terminar, parar/remover somente o container `unit3d-ds-rust`.

Logs e snapshots: `results/rust/*http*`. A API administrativa, retenção e ensaios
BitTorrent/performance ainda não estão homologados por estes testes HTTP.


### Retenção Rust

O mesmo `run-rust-mysql.sh` agora executa 21 blocos. O teste de retenção usa
relógio controlado para simular mais de 7200 s, MySQL real, bloqueio de linha e
cancelamento real da tarefa. Nenhuma referência pendente ou histórico é removido.
Ver `results/rust/rust-retention.txt` e `mysql-after-retention.json`.


### Contrato administrativo PHP/Rust

`run-admin-php-tests.sh` formata os quatro arquivos PHP envolvidos e executa
13 testes do adaptador, sem limpar banco. Para a integração real, preparar
`start-candidate-rust.sh fresh direct`, executar o contrato compartilhado de
30 passos e rodar `admin-php.php` na imagem PHP com rede host, DB de ensaio e
`rust-candidate.env` montado somente leitura em `/run/rust-candidate.env`.
O script nunca exporta a chave administrativa nem a resposta de usuário.

Resultado em `results/rust/php-rust-admin.json`: seis peers, onze endpoints,
uint64 preservado, quatro consultas e refresh sem sobrescrever contadores.
Em seguida `admin-php.php free-double` altera somente metadados em memória do
torrent 12002; `rust-http-factors.py --profile free-double --output ...` na VM
clientes confirma crédito 200/0 nas duas famílias. Repetir com `normal` confirma
100/100. Parar/remover o container Rust ao terminar. Scripts exigem fixtures
sintéticas e banco `unit3d_dualstack_journal_test`; nunca executar em produção.

## Preferência visual e contadores REST

No tracker isolado, sincronizar os arquivos do checkpoint e executar
`sudo bash /opt/unit3d-dualstack/lab/run-preference-tests.sh`. O runner usa o
banco `unit3d_dualstack_journal_test`, recusa containers de tracker ativos e testa
em transações revertidas. Exige o schema e as fixtures já preparados.
Resultado: `results/php-preference-tests.txt`; contrato e limites em
`../../docs/dualstack-contadores.md`. O motor de busca é simulado nesta suíte;
as leituras e escritas de contadores usam MySQL real.

## Escritas diretas do site — diagnóstico e correção

`check-site-writers.php` reproduz as limpezas manual e administrativa em
`unit3d_dualstack_journal_test`, sempre com rollback e sem tracker ativo. Executar
no container PHP do laboratório, com o repositório em `/app`, o diretório `lab`
montado em `/lab:ro` e `DB_DATABASE=unit3d_dualstack_journal_test`:

```sh
php /lab/check-site-writers.php
```

O script recusa outro banco ou lease ativa. No checkpoint de preferência, encerra
com código 1 porque ambos os controllers alteram peers/histórico diretamente com
dualstack ativo. Evidência: `results/site-writers.json`. Não remover ou inverter
a asserção para obter verde; integrar a limpeza ao proprietário antes de retestar.

Esse critério foi corrigido no checkpoint de limpezas. O resultado anterior é
histórico; `results/cleanup-tests.txt` contém a repetição com código 0 e mantém
as mesmas asserções. A recusa sem proprietário não demonstra, sozinha, a limpeza
positiva; esta é coberta pelas suítes e pelo ciclo real abaixo.

## Limpeza manual via coordenador PHP

Sincronizar o checkpoint PHP e os scripts para a VM tracker isolada. Com os
trackers parados/removidos e fixtures do banco de ensaio preparadas, executar:

```sh
sudo bash /opt/unit3d-dualstack/lab/run-cleanup-tests.sh
sudo bash /opt/unit3d-dualstack/lab/run-cleanup-lifecycle.sh
sudo bash /opt/unit3d-dualstack/lab/run-preference-tests.sh
```

São ensaios destrutivos somente em `unit3d_dualstack_journal_test`; não usar em
produção. A primeira suíte aplica a migração da fila duas vezes, executa 42 testes
de limpeza/journal em MySQL e Redis reais e repete os controllers sem proprietário.
Inclui subprocessos concorrentes, crash/reentrega, cotas, cortes por endpoint,
limite de backlog e probes nas duas famílias, sem skips.

O ciclo real recria fixtures após preflight, registra uma limpeza com journal
vazio, confirma a recusa de handoff pelo Rust inalterado e recupera com
`dualstack:work --once`. Depois inicia o daemon PHP com `APP_ENV=local`, solicita
outra limpeza, anuncia novamente nas duas famílias e encerra com SIGTERM.
Exige saída zero, fila vazia, referência mantida e crédito adicional único de 100.
Em falha, preserva o container para inspeção e as intenções/journal para recuperação;
recuperar antes de repetir o preflight. Não forçar o marcador de drenagem.

Logs finais: `results/cleanup-tests.txt`, `results/cleanup-lifecycle.txt` e
`results/cleanup-preference-regression.txt`. As falhas iniciais e seus ajustes
estão documentados em `../../docs/plans/2026-10-08-dualstack-execucao.md`.
Configuração e semântica assíncrona: `../../docs/dualstack-standalone.md`.

## Exclusões coordenadas

Com os trackers parados, aplicar o código e executar `run-deletion-tests.sh`.
O runner aplica a migração aditiva 000005 duas vezes e exige MySQL/Redis reais,
banco exclusivo e ausência de skips. São 57 testes PHP e seis blocos Rust.

Para o ciclo HTTP, executar sequencialmente os modos PHP standalone e Rust:

1. Na VM clientes, reaplicar `prepare-client-rotation.sh` (IPv6 `::31`).
2. Iniciar o backend com `start-candidate-php.sh fresh` ou
   `start-candidate-rust.sh fresh direct`.
3. Na VM clientes, executar `candidate-php.py` com `--backend php-standalone`
   ou `rust`, fixture privada, database.env privado e caminho de resultado.
4. No tracker, rodar `deletion-operator.php php-standalone` ou `rust` na imagem
   PHP, rede host, `APP_ENV=local`, DB de ensaio, repositório `/app` e scripts
   `/lab:ro`. Rust exige seu env privado montado `/run/rust-candidate.env:ro`.
5. Na VM clientes, executar `deletion-http.py` com os mesmos argumentos do
   contrato. Confere recusa nas duas famílias e outro torrent disponível.
6. Encerrar com SIGTERM, conferir saída zero e remover somente os containers
   deste ensaio. Nunca executar esses scripts em produção.

Resultados em `results/deletion-*`. A exclusão usa o controller real; notificações
externas e jobs alheios ao tracker são simulados para não enviar mensagens.
A exclusão em lote adicional é exercitada pela suíte de integração, não pelo
roteiro HTTP individual. `deletion-php-missing-address.json` registra a falha de
configuração IPv6 anterior à repetição aprovada.

## Telas locais de endpoints

`run-endpoint-view-tests.sh` executa os testes de leitura das telas e as regressões
de preferências/API: 46 testes, 498 asserções, com MySQL real. Usa transações
revertidas no banco de ensaio e recusa trackers em execução. Não exige Rust.
Inclui HTML real do corpo da tela de torrent e renderização/atualização Livewire,
além de paginação e quantidade constante de consultas. Logs em
`results/endpoint-view-tests.txt`; preparação inicial em `endpoint-view-initial.txt`.

O mesmo runner agora inclui a busca administrativa: **54 testes / 568 asserções**.
A versão anterior de 46 testes permanece como evidência histórica. Resultado
atual em `results/admin-endpoint-tests.txt`, diagnóstico inicial da recursão
corrigida em `results/admin-endpoint-initial.txt`. Agrupamentos por IP sobrepõem
peers dualstack; a própria tela explica que não devem ser somados como total único.

## Critério dos consumidores do site

Com os trackers parados, executar `check-site-consumers.php` na imagem PHP com
rede host, DB `unit3d_dualstack_journal_test`, código em `/app` e scripts em
`/lab:ro`. O ensaio usa transação revertida e simula comunicações externas.

O checkpoint anterior retornou **código 1**: 18 verificações aprovadas, duas falhas
porque BON considera a projeção positiva de um endpoint expirado. Não apagar nem
relaxar essa asserção. Evidência em `results/site-consumers.json`. O modo externo
é uma configuração do consumidor PHP; o ensaio não executa outro processo Rust.
As suítes verdes anteriores permanecem registradas separadamente.

## Correção do BON e gate de concorrência

Na VM tracker, com os mesmos mounts, banco exclusivo e trackers parados:

```sh
sudo bash /opt/unit3d-dualstack/lab/run-bon-tests.sh functional
sudo bash /opt/unit3d-dualstack/lab/run-bon-tests.sh contention
sudo bash /opt/unit3d-dualstack/lab/run-bon-tests.sh legacy-control
```

`functional`: **83 testes / 925 asserções**, Blade compilado e **20/20** checks
dos consumidores. Transações revertidas. A verificação de BON que falhava agora
concede zero quando só há checagem positiva expirada. Resultado integral em
`results/bon-functional.txt`; JSON extraído em `results/site-consumers-fixed.json`.

`contention`: **falha conhecida, saída 1**. Quatro processos persistem os mesmos
24 eventos, em lotes de um, enquanto um quinto executa cinco alocações. O pai
segura locks de usuários até o MySQL registrar cinco esperas simultâneas.
Usa MySQL real em `REPEATABLE-READ`, timeout de lock de dez segundos, Redis real
e o `TransitionWriter` real. A preparação reinicia peers, histórico, contadores
e tráfego **somente no banco de ensaio**; não é um teste revertido por transação.
Regras BON e saldos são restaurados ao final, a lease é liberada e o stream
isolado é removido. Não executar contra outra instalação.

O resultado registrado teve 27 deadlocks e nenhum timeout novo. Os três usuários
receberam, cada um, 800 bytes de upload e 100 BON, sem duplicação; seis peers,
12 endpoints e journal vazio. O gate exige também ausência de novos deadlocks.

`legacy-control`: mesma carga, com a consulta BON legada e os gravadores dualstack
atuais. Também falha: 22 deadlocks, créditos corretos e nenhum timeout novo. Isso
reproduz a pendência sem a consulta nova de endpoints; **não é baseline completo
da tag 9.2.0 nem comparação estatística de performance**. Contagens variam com
a ordem de execução dos processos. Evidências `results/bon-contention*.txt`.

`inspect-bon-locks.php` extrai somente operações e locks do último deadlock do
MySQL, sem SQL completo ou valores das linhas. Após o controle legado, o registro
mostra o ciclo `users` exclusivo → `torrents` exclusivo contra `torrents`
compartilhado → `users` exclusivo. Evidência `results/bon-locks.json`.
O retorno 1 não foi dispensado: a etapa segue pendente até corrigir essa disputa.

### Resultado após a correção dos locks

Os resultados vermelhos acima são históricos. O mesmo `run-bon-tests.sh`
agora aprova `functional`, `contention` e `legacy-control`. O funcional inclui
uma segunda suíte de alocação: total de 90 testes / 978 asserções e 20 checks
dos consumidores. As regras de alocação e saldos anteriores são restaurados
ao final dos ensaios confirmados; usuários sintéticos 15001–15501 são exclusivos
da nova suíte, que recusa colisão antes de criar e os remove ao terminar.

`run-bon-rust-tests.sh` compila o teste Rust com lockfile e executa simultaneamente
`dualstack_bon.rs` e o comando PHP real de BON, contra o mesmo MySQL. Quatro
tarefas Rust passam pelo mutex do coordenador: há dois escritores SQL (Rust e
BON), cujas esperas são forçadas e medidas. Créditos finais e métricas do motor
são conferidos; regras/saldos restaurados, backlog drenado e lease liberada.
Sinais temporários contêm somente flags e ficam preservados se houver falha.

Os três perfis de concorrência passaram com zero deadlocks/timeouts novos.
Logs atuais `results/bon-lock-fix-*.txt` e `results/bon-rust-contention-fixed.txt`.
O primeiro harness Rust tinha expectativa incorreta de cinco escritores SQL;
seu resultado está preservado em `results/bon-rust-harness-initial.txt`.

## Paridade de histórico e seedtime

`sudo bash /opt/unit3d-dualstack/lab/run-history-tests.sh` executa a mesma fixture
`fixtures/history-v1.json` no PHP e no Rust, sequencialmente, com os gravadores
reais. Exige trackers parados e banco `unit3d_dualstack_journal_test`; reinicia
peers, histórico, contadores e tráfego exclusivamente nesse banco. Não executar
contra uma instalação de uso. PHP usa namespace Redis isolado e o limpa ao final;
os dois testes liberam o proprietário após sucesso.

Resultado: 23 operações, seedtime final 251, uma conclusão e um histórico por
usuário/torrent; reaplicação de lotes sem novo crédito. PHP: 1 teste / 258
asserções. Rust: 1 teste. Evidência em `results/history-contract.txt`.

## Observação de I/O durante benchmarks

`benchmark-io.py --seconds 105` coleta contadores por dispositivo, pressão de
I/O e CPU a cada dois segundos. Executar no host Proxmox e na VM dados ao mesmo
tempo que a carga de 30 s de aquecimento e 60 s medidos. Na VM dados, acrescentar
`--mysql`: consulta somente contadores globais e agregados de espera em arquivos
do Performance Schema, usando a credencial já presente no container. Não exporta
credenciais, consultas de usuários ou nomes de arquivos. Não altera a durabilidade
do banco e não gera carga artificial de disco.

Guardar stdout em JSONL, com nomes distintos por rodada. Executar
`analyze-benchmark-io.py resultado-http.json dados-io.jsonl host-io.jsonl` para
calcular deltas somente dentro da janela medida. As amostras de dois segundos
não revelam todos os picos curtos; ocupação do dispositivo não equivale a um
limite universal de capacidade. O host inclui interferência de outras VMs.
Correlacionar filas, tempos de escrita/flush, leituras físicas do buffer pool,
esperas de redo e drenagem da persistência antes de atribuir a regressão ao SSD.

O formato segue os [contadores de I/O do Linux](https://docs.kernel.org/admin-guide/iostats.html)
e os [tempos normalizados do Performance Schema](https://dev.mysql.com/doc/refman/8.0/en/performance-schema-timing.html).
Dados e interpretação desta investigação: `results/rust-index/` e
[relatório de benchmarks](../../docs/dualstack-benchmarks.md).

`run-rust-selection-probe.sh 1000` (ou `54000`/`100000`) exige o tracker
parado e uma fixture concentrada da população indicada. Carrega o coordenador
real, mede somente `select_at` em memória, com `numwant=0` e `25`, e libera a
lease. Faz três repetições de 2.000 chamadas, com aquecimento de 200 chamadas.
Não altera créditos e não representa throughput HTTP, I/O sustentado ou gate
de homologação. O exemplo Rust é montado temporariamente pelo Docker; não é
parte do produto. A configuração permite explicitamente os endereços privados
da fixture. O primeiro preparo sem essa opção foi recusado corretamente e está
registrado em `results/rust-index/selection-probe-initial-private-address.txt`.

O gerador HTTP mantém `latency_ms` (inclui asserções locais), acrescenta
`response_read_ms` (até ler todo o corpo) e `validation_ms` (validação e retorno
da tarefa). Os percentis dessas parcelas não devem ser subtraídos/somados entre
si: são distribuições diferentes. A drenagem agora exige também que o incremento
de `state_version` seja igual ao número de requests aceitos no candidato. Esse
controle se aplica à fixture estática de announces aceitos; churn/expiração
precisam de seu próprio contrato de transições.

`run-rust-validation.ps1` coordena uma rodada curta entre Windows e as VMs do
laboratório. Exige `-Variant original|candidate`, `-Label` único e
`-IdentityFile` apontando para a chave SSH existente, sem lê-la ou exportá-la.
Aceita população, distribuição, porcentagem dualstack e taxa (máximo 2.000 req/s).
Recusa tracker já ativo antes de restaurar o banco e usa `finally` para drenar
o backend iniciado pela própria rodada. O teste de recusa preservou o container
ativo; evidência `results/rust-validation/runner-guard.json`.

Instalar também `benchmark-readiness.py` na raiz do laboratório da VM clientes.
O runner espera os listeners IPv4 e IPv6 por até 180 segundos antes da carga.
Isso evita confundir o tempo de bootstrap de populações maiores com uma queda
do serviço. A tentativa anterior que falhou no preflight fica preservada.

`-LegacyFlushMilliseconds 100` executa um controle adicional do original usando
sua própria configuração de flush. O padrão `0` não sobrescreve a configuração
existente. Esse controle separa parte do custo da frequência de persistência;
não iguala os modelos de filas ou as garantias transacionais dos backends.

`-AnalyzeFixture` executa `analyze-benchmark-fixture.py` antes de iniciar o backend:
atualiza estatísticas de `peers`, `peer_ips`, `history` e `torrents` apenas no banco
descartável e exige proprietário parado. Aplicar a ambos os lados do par. A opção
foi introduzida após um timeout de bootstrap em 54 mil peers concentrados, com
mais de um bilhão de linhas examinadas por um plano desfavorável. Não é uma
correção do produto; a tentativa reprovada permanece no relatório.

`diagnose-rust-bootstrap.py` captura planos com `EXPLAIN`, índices, consultas
ativas desse banco e executa somente o `SELECT` agregado equivalente, limitado
a cinco segundos pelo servidor. Não executa o `UPDATE` de reconciliação.
Resultados grandes de tempo de escrita nos contadores de disco são sinalizados
pelo analisador como exigindo investigação; os dados brutos não são descartados.

O runner executa gerador, observadores de I/O e métricas do tracker em jobs
simultâneos. Cada nova rodada restaura somente o banco de ensaio. Os aliases
devem ser preparados antes da série e removidos ao final. Evidências numéricas
ficam em `results/rust-validation/`; os resultados completos do gerador continuam
na VM clientes, com exportação pelo filtro já existente.

Para isolar o observador SQL em populações maiores, `-MonitorInterval 0`
desativa os snapshots periódicos do gerador. Preserva as checagens de base
limpa, saldo, identidades e todas as versões no encerramento. Os contadores
externos de I/O continuam ativos; sem os snapshots, não há medição periódica
do atraso de persistência. O padrão é cinco segundos e o gerador registra o
tempo gasto em cada snapshot. Comparar somente pares com a mesma opção.

`summarize-rust-validation.py results/rust-validation` lê resumos, contadores e
resultados brutos exportados; valida parâmetros equivalentes e calcula cada
comparação separadamente. Nas três repetições curtas, apresenta mínimo, mediana
e máximo dos percentis por rodada. Não os confunde com o percentil combinado,
nem transforma a ausência de erros em homologação completa.

## Consumidores adicionais

O runner `run-bon-tests.sh functional` inclui agora os 20 testes reais de
seedboxes e oito cenários adicionais do perfil. Resultado consolidado atual:
118 testes / 1.215 asserções, 20 checks e templates compilados. `contention` e
`legacy-control` executam BON e seedbox separadamente, cada um junto de quatro
gravadores PHP: dois testes / 101 asserções por modo, cinco esperas SQL medidas
por cenário, zero novos deadlocks/timeouts. Os ensaios restauram também os
cadastros criptografados de seedboxes e as marcações de torrents.

Logs: `results/site-final-functional.txt`, `site-final-contention.txt` e
`site-final-legacy-control.txt`. Esses resultados substituem, sem apagar, os
totais menores das etapas anteriores. O ensaio Rust/BON permanece independente.

## Reprodução histórica — falhas legadas

`sudo bash /opt/unit3d-dualstack/lab/run-site-consumer-tests.sh` executa 12 casos
no banco exclusivo, em transações revertidas, com trackers parados. Chat,
notificações, filas e HTTP são simulados; SQL e comandos são reais. O dispatcher
das consultas de estatística usa o driver síncrono para participar da transação.

Resultado antes da correção: **saída diferente de zero**, seis casos
passam e seis falham. As duas causas, repetidas com IPv4/IPv6/dualstack, são
erro 1055 no agrupamento de clientes e crédito incompleto de reembolso quando
um usuário tem dois torrents elegíveis. Os dois arquivos responsáveis são
idênticos aos da 9.2.0. Não dispensar as asserções nem desligar SQL estrito.
Recompensa de ressurreição e reembolso de um torrent passaram.

Evidência: `results/site-history-consumers.txt`. O plano registra os blobs,
valores esperados/observados e a proposta separada de correção. Esse runner
é independente da regressão verde `run-bon-tests.sh`; o gate adicional impede
declarar concluída a validação de todos os consumidores.

## Reembolso e estatísticas corrigidos

O gate acima foi corrigido no incremento seguinte. O runner funcional agora
executa **31 testes / 276 asserções**, incluindo falhas e retry do reembolso.
`run-refund-contention-tests.sh` disputa as mesmas chaves entre 16 processos;
`run-refund-rust-tests.sh` combina um gravador SQL Rust e oito jobs PHP.
Nenhum deadlock/timeout novo; contabilidade e reentrega aprovadas.

Ensaios HTTP reais curtos: Rust 1.000 e 2.000 req/s, PHP aproximadamente
213 req/s sem reembolso e 209 com ele, com origens distribuídas para respeitar
o limitador existente. Não representam homologação do benchmark completo.
Ver [procedimento e limites](../../docs/dualstack-reembolso-concorrencia.md) e
`results/refund-final-tests.txt`, `results/refund-rust-contention.txt` e
`results/refund-*-http-*.json`. As evidências reprovadas anteriores são históricas.

## Retorno às tags originais e reconciliação

`run-legacy-reconciliation.sh` verifica o bloqueio persistente, a manutenção
offline e a regressão dos coordenadores. `run-legacy-originals.sh` ensaia as fases
`php`, `rust-start` e `rust-finish`, com um request HTTP real originado da VM
clientes entre as duas últimas fases. Usa cópias exportadas dos commits originais;
nunca redefine os repositórios candidatos ou o banco baseline.

Ver [procedimento completo e limites](../../docs/dualstack-rollback-legado.md),
`checkpoint-legacy.json` e `results/legacy-*`. A sequência de saldos confirmada
foi 100 → 200 → 300 → 400 → 500, sem duplicação na retomada. Não substitui testes
de transferência BitTorrent nem o benchmark completo.

## Clientes BitTorrent reais — bloqueio IPv6 resolvido

O novo `real-clients.py` prepara torrents privados e executa qBittorrent 4.6.3
e Transmission 4.0.5 em namespaces com origens reais. Quatro transferências de
16 MiB passaram no PHP standalone, com handshake e SHA-256 correto:
qBittorrent → Transmission e o sentido inverso, por IPv4-only e IPv6-only.

O bloqueio inicial Transmission → qBittorrent por IPv6 foi localizado no
libtorrent 2.0.10: bind IPv4 em socket IPv6 ao usar nome de interface, retornando
`EINVAL`. Controle com IP explícito e sem vínculo por nome completou o arquivo.
O harness usa agora seleção automática dentro do namespace isolado, preservando
as rotas locais e versões. `diagnose-client-ipv6.py` reproduz o erro e os
controles positivos sem alterar os produtos. Dualstack, falha de família e
backend Rust continuam pendentes; não declarar a etapa inteira concluída.

Ver [procedimento, evidência e limites](../../docs/dualstack-clientes-reais.md),
`checkpoint-real-clients.json` e `results/real-clients/`. Capturas completas
permanecem privadas na VM clientes; somente os relatórios permitidos foram
exportados. Baseline preservado, clientes/namespaces e tracker encerrados.

## Escritor Rust: drenagem e endpoints

O incremento está descrito em [dualstack-writer.md](../../docs/dualstack-writer.md).
`DUALSTACK_BATCH_SIZE` aceita 1–500 (padrão 200) e exige restart. Lotes cheios
seguem sem espera artificial; cada ciclo cede execução e preserva manutenção,
heartbeat, limites de fila e fencing. As opções de flush do modo legado não
controlam esse coordenador.

`run-writer-tests.sh` executa os contratos, MySQL real, concorrência com BON e
refunds, handoff, remoção e testes de rede/configuração. É destrutivo somente
para `unit3d_dualstack_journal_test` e exige todos os trackers encerrados.

`writer-plans.py` gera cargas com 40 torrents × 250 peers e três repetições por
taxa. `prepare-writer-copy.py` exige o fingerprint esperado e cria uma cópia com
instrumentação, sem mudar cadência ou SQL. `hash-writer-copy.py` identifica os
fontes e binário usados. Os modos `writer-cadence` e `writer-endpoints` do runner
separam a comparação. `summarize-writer.py` consolida apenas séries auditadas
desse incremento e mantém o relatório histórico de throughput intacto.

A VM de dados passou de 16 para 24 GiB depois de uma interrupção por disco cheio
nos binlogs, e para 32 GiB antes do ensaio sustentado; a série interrompida
permanece como evidência reprovada. O runner
confere mais de 2 GiB livres antes de cada série; monitorar o crescimento de
binlogs em campanhas longas. Durabilidade e timeout não foram relaxados.
Também conferir espaço físico no thin pool do Proxmox; a alocação virtual das
VMs supera a capacidade física. Este incremento não habilita a campanha de seis
horas sem orçamento de armazenamento e retenção.

## TLS/proxy e memória/cache

`prepare-network.sh` e `network-backend.sh` montam o frontend HTTPS com CA
privada de laboratório, backend em loopback e sobrescrita dos headers de origem.
`network-client.py` executa 19 controles por backend. `memory-client.py` rotaciona
IPs IPv6 reais a até 20 requests/s; `memory-sampler.py` mede RSS/PSS e Redis.
`build-memory-observer.sh` prepara uma cópia Rust para observar seu cache privado,
preservando fontes e executável do produto. `summarize-network-memory.py`
consolida as séries efetivamente aprovadas.

Procedimento, correção PHP encontrada e limites em
[dualstack-tls-memoria.md](../../docs/dualstack-tls-memoria.md). Evidências em
`results/tls-memory/` e `checkpoint-tls-memory.json`. Essa etapa não executa carga
de capacidade nem aprova a campanha de seis horas.

## Arquivo ZFS para a campanha prolongada

As VMs 120–122 têm áreas exclusivas via VirtioFS em `/mnt/unit3d-archive`,
compartilhando uma quota/reserva de 300 GiB no dataset
`storage_pool/unit3d-dualstack`. O banco ativo permanece no SSD. Na VM de dados,
`unit3d-binlog-archive.timer` arquiva binlogs fechados, verifica SHA-256/fsync e
purga somente o prefixo confirmado pelo MySQL.

Preparação: `prepare-archive-host.sh` (VMs paradas),
`prepare-archive-guest.sh`, `install-binlog-archive.py`,
`redirect-archive-results.py` e `guard-archive-mountpoint.sh`.
Scripts de instalação devem estar junto dos módulos Python correspondentes.
O instalador do arquivador não habilita o timer: validar, drenar o passivo e
habilitar `unit3d-binlog-archive.timer` conforme o procedimento registrado.

Antes de iniciar carga em cada VM:
`sudo python3 /opt/unit3d-dualstack/lab/archive-preflight.py`.
Capacidade, resultados, operação e retorno:
[`docs/dualstack-armazenamento.md`](../../docs/dualstack-armazenamento.md).
O checkpoint de armazenamento registra a situação anterior à campanha.
Os preparativos e o estado posterior estão em
[`docs/dualstack-prolongado.md`](../../docs/dualstack-prolongado.md) e
`checkpoint-soak.json`.

## Campanha prolongada com memória limitada

`start-soak.ps1` instala o perfil isolado e inicia o supervisor no Proxmox.
`soak-load.py` usa `soak_metrics.py` para segmentar amostras no ZFS e audita
identidade, crédito e contadores entre janelas. `soak-observer.py` e
`soak-supervisor.py` interrompem a carga ao detectar falha ou falta de recursos.
O supervisor independe da conexão SSH/Codex. Não iniciar dois perfis ao mesmo
tempo, nem reutilizar o nome de uma execução.

`test-soak.py` verifica histograma, segmentos, falhas do escritor e guards.
`verify-soak-samples.py` confere hash/CRC/cardinalidade no host após o término.
`collect-soak.ps1` exporta somente evidência pública; `summarize-soak.py` resume
os arquivos coletados, mantendo percentis por janela distintos de percentis
globais. Não exportar binlogs, arquivos `.env` ou fixtures com passkeys.
