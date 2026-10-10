# Capacidade por configuração de VM

Estado em 10/10/2026: diagnóstico com banco **1 vCPU/4 GiB concluído e auditado**.
A matriz geral permanece incompleta, aguardando decisão sobre o controle de cache.

## Escopo autorizado

Os perfis **1 vCPU/2 GiB** e **2 vCPU/4 GiB** representam cada VM separadamente,
conforme confirmação do operador. A referência tem 4 vCPU/8 GiB por VM.
O objetivo é localizar a fronteira sustentável do Rust candidato e do MySQL,
e relacionar a carga confirmada a CPU, memória e operações de disco.

Esta campanha não retoma a validação PHP nem a comparação com a tag original.
Usa o candidato Rust `36823b5`, sem alterações de produto. O plano está em
[capacidade por recursos](plans/2026-10-10-capacidade-recursos.md).

## Isolamento e método

- VMs 120 (tracker), 121 (dados) e 122 (gerador), exclusivas do laboratório.
- Base nova `unit3d_dualstack_capacity_20261010`. Evidências anteriores preservadas.
- Mudança real de vCPU/RAM com encerramento gracioso e reboot; balloon desligado.
- Gerador fixo em 4 vCPU/8 GiB, quatro processos com identidades disjuntas.
- 10.000 peers lógicos, 20.000 endpoints, 40 torrents de 250 peers, 80% seeders.
- Conexões com origem IPv4/IPv6 real; duas famílias compartilham a referência de crédito.
- HTTP direto, `numwant=10`, lote 500, TTL 7.200 s, sem probes ou logs de announces.
- `ANNOUNCE_MIN_ENFORCED=0` permite a carga sintética; fatores globais de crédito
  permanecem em 100%. Requests/s de estresse não equivalem à população de usuários
  com intervalos normais de announce.
- O primeiro estágio mantém as configurações MySQL constantes: buffer pool 128 MiB,
  `innodb_flush_log_at_trx_commit=1` e `sync_binlog=1`. Aumentar a RAM da VM não
  aumenta implicitamente o buffer pool; a investigação de memória é uma fase própria.
- Rampas de 60 s após 20 s de aquecimento; até duas bisseções para estreitar a
  fronteira; três confirmações de 300 s após 30 s de aquecimento no maior ponto
  estável encontrado. Uma falha de confirmação impede chamar aquele ponto de sustentável.
- Cada rodada reinicia o processo, estabelece a fixture limpa, drena e confere
  crédito por identidade, histórico e usuário, endpoints e contadores.

| Perfil | Tracker | Dados |
|---|---|---|
| reference | 4 vCPU / 8 GiB | 4 vCPU / 8 GiB |
| tracker1 | 1 vCPU / 2 GiB | 4 vCPU / 8 GiB |
| tracker2 | 2 vCPU / 4 GiB | 4 vCPU / 8 GiB |
| database1 | 4 vCPU / 8 GiB | 1 vCPU / 2 GiB |
| database2 | 4 vCPU / 8 GiB | 2 vCPU / 4 GiB |
| database1ram4 | 4 vCPU / 8 GiB | 1 vCPU / 4 GiB |
| database2ram2 | 4 vCPU / 8 GiB | 2 vCPU / 2 GiB |
| balanced1 | 1 vCPU / 2 GiB | 1 vCPU / 2 GiB |
| balanced2 | 2 vCPU / 4 GiB | 2 vCPU / 4 GiB |

## Calibrações concluídas

| Execução | Recursos tracker / dados | Taxa | Aceitos | Erros / divergências | Drenagem |
|---|---|---:|---:|---:|---:|
| capacity-smoke-v1 | 4/8 + 4/8 | 1.000 req/s | 12.000 | 0 / 0 | 0,733 s |
| capacity-resource-smoke-v1 | 1/2 + 1/2 | 1.000 req/s | 12.000 | 0 / 0 | 0,730 s |
| capacity-smoke-v2 | 4/8 + 4/8 | 1.000 req/s | 12.000 | 0 / 0 | 0,731 s |

Cada calibração teve 2 s de aquecimento e 10 s medidos. O crédito de 601.600 bytes
foi confirmado individualmente, com 10.000 peers e 20.000 endpoints. A contagem
de requests não é uma fórmula geral de crédito: os pares das duas famílias e
as rodadas incompletas por identidade são considerados pelo oráculo.

O ensaio de recursos também confirmou os reboots e a restauração para 4 vCPU/8 GiB.
Esses resultados validam a instrumentação e a administração do laboratório;
**não determinam os tetos sustentáveis**. A segunda calibração confirmou a
telemetria adicional de PSS, esperas SQL, disco físico e encerramento com código
zero e sem OOM. As saídas públicas estão em
`lab/dualstack/results/capacity/<nome-da-calibração>`.

## Correção do alinhamento das amostras

A série `capacity-cpu-ram-v1` começou em **10/10/2026 às 07:20:36 UTC**.
Foi interrompida graciosamente após detectar uma classificação falsa de saturação
a 1.000 req/s. A rodada recebeu 80.000 announces, confirmou o crédito integral,
teve zero erros, p99 de resposta de 0,344 ms e drenou em 0,732 s.

O classificador subtraía a última amostra de cada observador sem alinhar seus
instantes. A tendência aparente era +31,662 transições/s. Interpolando o contador
do gerador para o instante da consulta SQL, as mesmas séries mostram +0,018
transição/s, com atraso estimado entre 33 e 153 transições. As consultas duraram
no máximo 61 ms. A reanálise preserva os dados e a classificação original em
`results/capacity/capacity-cpu-ram-v1/lag-alignment-reanalysis.json`.

Trata-se de um problema novo no instrumento desta campanha, sem alteração no
produto. A série v1 não vale como fronteira de capacidade. A rodada em andamento
foi drenada, a contabilidade conferida e os recursos originais restaurados.

`capacity_metrics.py` agora usa instantes alinhados, exige amostras suficientes
e registra a resolução da detecção: dois lotes mais a incerteza temporal da
consulta. Crescimento abaixo dessa resolução não é declarado rigorosamente zero.
Cinco testes verificam o caso real, coleta defasada, filas crescentes em rampas e
confirmações longas, e falta de amostras. A calibração no MySQL real precede a retomada.

A calibração `capacity-alignment-smoke-v1` passou: 20 s de aquecimento e 60 s
medidos a 1.000 req/s, 80.000 aceitos, crédito de 4.006.400 bytes conferido por
identidade, zero erros/divergências, drenagem de 0,738 s e encerramento com código
zero. O atraso alinhado ficou entre 36 e 158 transições, sem crescimento detectado.
Recursos restaurados; saídas públicas coletadas. A matriz foi retomada como
**`capacity-cpu-ram-v2`**, com acompanhamento pela execução indicada no checkpoint.

## Acompanhamento

O supervisor inicia na referência 4/8 + 4/8 e só avança após drenagem e auditoria.
O acompanhamento `acompanhar-capacidade-do-rust-e-mysql` verifica a execução a
cada 15 minutos, em silêncio enquanto saudável, e continua as etapas autorizadas
após examinar os resultados. O checkpoint identifica a execução ativa.

**Atualização de 10/10/2026:** a série v2 foi interrompida por proteção de memória
no perfil do banco com 1 vCPU/2 GiB. Recursos restaurados e acompanhamento pausado;
a matriz não foi concluída nem reiniciada. O diagnóstico e os resultados parciais
estão abaixo.

## Como interpretar as métricas

- CPU do processo é expressa em percentual de **um núcleo**; CPU da VM usa o total
  de vCPUs. Não comparar os dois denominadores diretamente.
- Percentis combinam histogramas dos quatro processos na mesma rodada. São
  separados entre resposta HTTP e espera no gerador. Não há mistura do aquecimento.
- A diferença entre aceitos e versões SQL é uma estimativa de atraso, com amostras
  coletadas em instantes próximos, não uma leitura exata da fila. Cada rodada
  termina antes do TTL, portanto não inclui transições de expiração.
- O critério provisório de localização usa >=99% da taxa oferecida, zero erros,
  contabilidade exata, drenagem <=30 s e tendência da fila na metade final dentro
  da resolução da observação. Os gráficos/séries e as confirmações longas precisam
  confirmar essa classificação; não basta confiar no booleano `stable`.
- IOPS, MiB/s, tamanho médio das operações, latência de escrita/flush e filas são
  medidos na VM de dados e no SSD do host. O SSD atende outros serviços; sua carga
  total não pode ser atribuída integralmente ao MySQL deste ensaio.
- O observador SQL e o arquivo de binlogs permanecem ativos. Seus custos fazem
  parte da configuração medida, de forma igual entre perfis.
- A saturação interrompe a oferta antes do limite de backlog. Não é necessário
  provocar queda, OOM ou esgotar armazenamento para localizar a fronteira.

## Evidências e continuidade

O supervisor roda no Proxmox, sem depender da sessão SSH. As saídas públicas ficam
em `/storage_pool/unit3d-dualstack/supervisor/capacity/<série>` e nos diretórios
`results/capacity/<rodada>` de cada VM. O coletor exporta apenas JSON/JSONL públicos;
não inclui binlogs, credenciais ou fixtures privadas.

Ferramentas: `capacity-admin.py`, `capacity-load.py`, `capacity-observer.py`,
`capacity-series.py`, `summarize-capacity.py` e `collect-capacity.ps1`, em
`lab/dualstack`. O checkpoint é `lab/dualstack/checkpoint-capacity.json`.

Após a matriz CPU/RAM: interpretar fronteiras e limitações do gerador; então
executar controles de população/buffer pool e de I/O da VM de dados. Essas fases
ainda não foram executadas nem automatizadas neste supervisor. Os limites de
IOPS reduzirão capacidade disponível para observar sensibilidade; não reproduzem
um SSD mais rápido. Qualquer estimativa para outro hardware será identificada
como estimativa, com latência, durabilidade e perfil de carga associados.

## Interrupção da v2: memória da VM de dados

Às **09:11:57 UTC de 10/10/2026**, o observador registrou `memory_low`:
`MemAvailable=251,422 MiB`, abaixo do piso de 256 MiB. O supervisor interrompeu
a oferta da rodada `capacity-cpu-ram-v2-database1-confirm-2`, a 5.500 req/s,
ainda nos primeiros sete segundos do aquecimento. Não houve janela medida nessa
rodada; seus percentis medidos são nulos, não zero.

O MySQL cresceu durante as rodadas do mesmo perfil, mantendo o mesmo processo.
O Rust é reiniciado entre rodadas; o MySQL não é reiniciado entre taxas do mesmo
perfil. Portanto, o estado de memória acumulado também influencia esta fronteira.

| Momento | RSS do MySQL | Memória disponível da VM |
|---|---:|---:|
| Início da rampa de 500 req/s | 467,8 MiB | 1.196,4 MiB |
| Fim da rampa de 4.000 req/s | 1.168,8 MiB | 440,5 MiB |
| Fim da primeira confirmação de 5.500 req/s | 1.245,4 MiB | 346,0 MiB |
| Início da segunda confirmação | 1.249,3 MiB | 353,4 MiB |
| Acionamento da proteção | 1.376,9 MiB | 251,4 MiB |

O PSS acompanhou o RSS: 1.377,0 MiB na última amostra. A queda de memória
disponível coincide com crescimento do próprio processo MySQL; não é apenas
uma leitura de cache de arquivos como memória ocupada. O buffer pool permaneceu
em 128 MiB. Isso não identifica, por si só, qual subsistema fez a alocação.

**Consequências verificadas:**

- 38.646 announces aceitos nessa rodada, todos persistidos; 1.932.800 bytes de
  crédito iguais nos peers, histórico, histórico real e usuários.
- Drenagem em 0,735 s; Rust encerrou com código zero, sem OOM.
- 10.000 peers e 20.000 endpoints, metade em cada família; zero divergências de
  identidade, crédito, endpoints, limite e contadores.
- Todas as **40 rodadas** com resultado salvo passaram na auditoria de correção
  e na verificação individual de encerramento. Saturação de capacidade em algumas
  rodadas não foi perda de crédito.
- Recursos das VMs 120/121/122 conferidos em 4 vCPU/8 GiB, balloon desligado;
  MySQL/Redis e timer de arquivo ativos. Base da última rodada preservada,
  proprietário inativo. Nenhuma nova carga iniciada.
- A consulta ao journal do kernel não encontrou evento de OOM no intervalo.
  A proteção parou antes de uma queda por falta de memória.

Esta interrupção específica foi causada pelo **piso de memória disponível**.
Ela não prova que o SSD causou o evento, nem que qualquer instalação de 2 GiB
suporta menos de 5.500 req/s. O resultado vale para a configuração, instrumentação,
sequência de taxas e estado acumulado deste laboratório.

## Hipótese de alocação a investigar

No candidato `36823b5`, as consultas dinâmicas em lote usam
`q.build().execute/fetch_all` sem desativar a persistência dos statements:
`repos/UNIT3D-Announce/src/dualstack/persistence.rs:287`, `:298`, `:302`, `:348`,
`:361`, `:373`, `:383` e `:395`. A fila legada de peers usa `.persistent(false)` em
`repos/UNIT3D-Announce/src/queue/peer_update.rs:126`.

A documentação da versão SQLx 0.8.6 recomenda considerar `.persistent(false)`
para lotes com muitos comprimentos diferentes, para evitar ocupar o cache de
statements da conexão. O cache padrão comporta 100 statements distintos por
conexão. [QueryBuilder](https://docs.rs/sqlx/0.8.6/sqlx/struct.QueryBuilder.html#method.push_values),
[MySqlConnectOptions](https://docs.rs/sqlx/0.8.6/sqlx/mysql/struct.MySqlConnectOptions.html#method.statement_cache_capacity).

**Hipótese, não causa demonstrada:** preparação de SQLs grandes, cache de
statements e retenção pelo alocador podem contribuir para esse crescimento.
O limite de 60 conexões do pool (`src/state.rs:72`) não significa que existiam
60 conexões ativas; não foi feita essa multiplicação para estimar memória.

A telemetria desta série não coletava alocações MySQL por subsistema nem quantidade
de statements preparados. A restauração reiniciou o MySQL, perdendo os contadores
voláteis daquele processo. A inspeção posterior encontrou zero statements preparados
e buffer pool de 128 MiB, mas pertence ao processo novo e **não confirma nem refuta**
a hipótese sobre o processo anterior. Não foi alterado produto, cache, limite de
proteção ou durabilidade para contornar a falha.

## Resultados parciais de capacidade

| Tracker / dados | Evidência obtida | Limite de interpretação |
|---|---|---|
| 4/8 + 4/8 | 8.000 req/s passaram em 60 s; confirmação de 300 s foi interrompida por backlog | 8.000 não confirmado; falta confirmar ponto inferior |
| 1/2 + 4/8 | 6.500 req/s completaram três confirmações de 300 s | Houve pico transitório de atraso estimado de 46.014 transições na segunda, depois recuperado |
| 2/4 + 4/8 | 7.000 req/s completaram duas confirmações; a terceira foi interrompida por backlog | Não aprovado nas três repetições; não concluir que mais CPU piora a capacidade |
| 4/8 + 1/2 | 5.500 req/s completaram uma confirmação; a segunda acionou proteção de memória no aquecimento | Fronteira sustentada não confirmada |
| Demais cinco perfis | Não executados | Matriz incompleta |

Nas três confirmações concluídas de 6.500 req/s, p99 HTTP ficou entre 0,941 e
1,016 ms e a drenagem entre 0,735 e 0,747 s. São percentis de cada rodada, não um
percentil global. O pico de backlog da segunda impediu tratar o booleano `stable`
como evidência de latência de persistência sempre baixa.

Na única confirmação completa do banco 1/2, a 5.500 req/s, a CPU da VM ficou em
79,79% ocupada e 9,09% de iowait; MySQL usou 65,64% de um núcleo. O disco da VM
registrou cerca de 1.601 escritas/s, 513 flushes/s, 25,97 MiB/s escritos e médias
de 0,388 ms por escrita e 0,480 ms por flush. São demanda observada e médias do
disco virtual, incluindo a instrumentação e o arquivo de binlogs; **não são uma
especificação mínima de SSD nem o teto de IOPS do hardware**. Nesse intervalo,
o InnoDB não registrou novas leituras de buffer pool, esperas por buffer livre,
esperas de log ou esperas por row lock. A VM também teve leituras fora dessas
leituras de páginas do InnoDB; não atribuir todo I/O ao conjunto quente do banco.

As interrupções por backlog tiveram contabilidade exata após a drenagem. Nos
resultados brutos, `completed_rps` divide pelo tempo solicitado mesmo quando a
oferta termina cedo; nesses casos o valor não representa a taxa instantânea
atendida. Os recursos resumidos também podem incluir parte da drenagem ainda
dentro da janela solicitada. Não usar essas médias como ponto sustentado.

## Evidências preservadas e decisão de continuidade

Coletados 567 arquivos públicos pelo coletor, incluindo resultados, séries,
observadores, estados de recursos e todas as provas `tracker-drain`.
`summarize-capacity.py` foi executado no host; a auditoria local revalidou as 40
rodadas. Diretório:
`lab/dualstack/results/capacity/capacity-cpu-ram-v2/`.

Entradas principais:

- `supervisor/capacity/capacity-cpu-ram-v2/status.json` e `summary.json`;
- `memory-guard-analysis.json`: evolução de RSS/PSS, confirmação por rodada e
  verificações de crédito, endpoints, contadores e drenagem;
- `recovery-verification.json`: recursos restaurados e supervisor inativo;
- `database-post-restore.json`: estado final preservado, configurações e inspeção
  de memória **posterior ao restart**, identificada como tal.

Recomendação para a próxima decisão: antes de retomar a matriz, instrumentar um
ensaio curto e limitado do **mesmo binário**, com banco de 4 GiB para ter margem,
registrando alocações por subsistema, `Prepared_stmt_count`, conexões, memória
anônima/cache e o intervalo de reset/reconexão entre rodadas. Assim será possível
distinguir statements, instrumentação e retenção do alocador. Um eventual teste
com cache desativado constitui um controle separado e não substitui o resultado
do candidato atual. A série v2 não será reiniciada automaticamente, conforme
a instrução de acompanhamento. Controles de população/buffer pool e I/O continuam
pendentes; a campanha não está concluída.

## Diagnóstico autorizado com banco de 4 GiB

O usuário autorizou o ensaio recomendado em 10/10/2026. O banco mantém 1 vCPU;
somente sua RAM passa de 2 para 4 GiB. Rust `36823b5`, buffer pool de 128 MiB,
durabilidade `1/1` e fixture permanecem iguais. A base final da v2 foi preservada
em cópia privada na VM de dados (7.972.038 bytes; hash na prova pública), sem
exportar seu conteúdo.

A calibração `capacity-memory-calibration-v1` completou 10 s de aquecimento e
30 s a 1.000 req/s: 40.000 announces aceitos, zero erros, 2.003.200 bytes de
crédito exatos por identidade/histórico/usuário, 10.000 peers e 20.000 endpoints.
Drenagem em 0,740 s, encerramento com código zero e sem OOM. VMs restauradas
para 4 vCPU/8 GiB; configurações de durabilidade conferidas após o retorno.

O novo coletor usa instrumentos MySQL já habilitados, sem coletar textos SQL.
Foram 25 amostras, com intervalo máximo de 5,001 s, sem falhas. Consultas do
coletor levaram mediana de 58,47 ms e máximo de 207,33 ms. Até 200 statements
preparados e 135,67 MiB em `Prepared_statement::main_mem_root` foram observados.
São evidências de calibração, ainda insuficientes para atribuir a interrupção
anterior a uma causa. Diretório público:
`lab/dualstack/results/capacity/capacity-memory-calibration-v1/`.

Série executada: `capacity-memory-4g-v1`, com sete rampas curtas e duas rodadas
de cinco minutos a 5.500 req/s, conforme o plano. O coletor contínuo abrange
também reset/reconexão e o período após a drenagem, antes do reboot final.
Esta série diagnostica alocação; não representa aprovação da matriz de capacidade.

## Resultado do ensaio com 4 GiB

Executado de **14:50:14 a 15:18:08 UTC de 10/10/2026**, incluindo preparação,
carga, intervalos e restauração (27 min 53 s). As nove rodadas completaram
**5.550.000 announces**, sem erros HTTP, com **277.523.200 bytes de crédito**
auditados. Como a base é resetada entre rodadas, este crédito é a soma das nove
auditorias, não o saldo da base ao final. A última rodada deixou 90.752.000 bytes
confirmados em peers, histórico e usuários.

Em todas as rodadas: 10.000 peers lógicos, 20.000 endpoints válidos, nenhum
endpoint extra, contador de torrent incorreto ou divergência por identidade.
Todas as drenagens terminaram em 0,730–0,794 s; encerramento do Rust com código
zero e sem OOM. O binário conferido permaneceu o candidato `36823b5`.

| Rodada | Medição após aquecimento | Aceitos, incluindo aquecimento | p99 HTTP (ms) | Drenagem (s) |
|---|---:|---:|---:|---:|
| 500 req/s | 60 s | 40.000 | 0,360 | 0,730 |
| 1.000 req/s | 60 s | 80.000 | 0,342 | 0,730 |
| 2.000 req/s | 60 s | 160.000 | 0,324 | 0,738 |
| 4.000 req/s | 60 s | 320.000 | 0,313 | 0,732 |
| 6.000 req/s | 60 s | 480.000 | 0,363 | 0,736 |
| 5.000 req/s | 60 s | 400.000 | 0,346 | 0,739 |
| 5.500 req/s | 60 s | 440.000 | 0,355 | 0,735 |
| 5.500 req/s, confirmação 1 | 300 s | 1.815.000 | 0,359 | 0,733 |
| 5.500 req/s, confirmação 2 | 300 s | 1.815.000 | 0,359 | 0,794 |

São percentis de resposta de cada rodada, sem a fila do gerador. Não são um
percentil global. O throughput das duas confirmações ficou em aproximadamente
5.500 req/s. Houve duas confirmações longas, não as três da matriz formal;
6.000 req/s foi apenas uma rampa curta. Nenhum desses resultados estabelece
o teto definitivo ou a estabilidade de seis horas do perfil 1/4.

## O que a memória mostrou

A coleta contínua produziu 317 amostras, intervalo máximo de 5,862 s, sem falhas;
o MySQL manteve o mesmo processo durante todas as rodadas. Os 502 instrumentos
de memória já estavam habilitados e permaneceram assim. O contador de perda
de instrumentação de statements permaneceu zero. A consulta adicional levou
mediana de 111,68 ms e máximo de 287,62 ms; esse tempo inclui espera e transporte,
não representa CPU consumida. Seu efeito sobre o teste não foi isolado em A/B.

| Medida | Antes da sequência | Maior valor observado | Antes do reboot final |
|---|---:|---:|---:|
| RSS do MySQL (MiB) | 410,89 | 1.245,75 | 1.215,86 |
| PSS do MySQL (MiB) | 411,00 | 1.245,94 | 1.216,03 |
| Memória anônima do MySQL (MiB) | 377,06 | 1.210,95 | 1.181,04 |
| Memória de arquivos do MySQL (MiB) | 33,94 | 34,99 | 34,99 |
| Alocações instrumentadas totais (MiB) | 449,11 | 958,74 | 464,06 |
| Grupo `memory/sql` (MiB) | 11,77 | 515,42 | 20,80 |
| `Prepared_statement::main_mem_root` (MiB) | 0 | 488,14 | 0 |
| Grupo `memory/innodb` (MiB) | 198,83 | 202,79 | 202,12 |
| Grupo `memory/performance_schema` (MiB) | 227,99 | 230,02 | 230,02 |
| Statements preparados ativos | 0 | 301 | 0 |

Os máximos de linhas diferentes podem ocorrer em instantes diferentes. São
máximos amostrados, não máximos contínuos. A memória disponível da VM nunca
ficou abaixo de **2.193,64 MiB** na coleta de cinco segundos; os observadores
de dois segundos tiveram mínimo de 2.193,74 MiB. O piso de proteção era 256 MiB.

As consultas preparadas têm custo material comprovado: até **488 MiB** só na
alocação `main_mem_root`. O grupo InnoDB variou menos de 4 MiB e o próprio
Performance Schema cerca de 2 MiB; eles não explicam o crescimento de centenas
de MiB observado na memória SQL. Foram observadas até cinco conexões totais,
incluindo a instrumentação; o máximo configurado de 60 não foi atingido.

Após **cada** encerramento do Rust, a contagem de statements e sua alocação
`main_mem_root` zeraram. Mesmo assim, o RSS após cada rodada foi, sucessivamente,
aproximadamente 512, 632, 791, 1.026, 1.171, 1.177, 1.191, 1.211 e 1.216 MiB.
A última confirmação variou apenas de 1.215,23 a 1.215,86 MiB durante a carga.
O RSS final continuou nesse patamar por cerca de 40 s após o encerramento.

**Confirmado:** as alocações instrumentadas das consultas foram liberadas e o
processo continuou residente com memória predominantemente anônima. **Inferência:**
o padrão é compatível com retenção/fragmentação no alocador. Não identifica o
alocador, não prova vazamento ilimitado e não permite atribuir toda a diferença
entre RSS e instrumentos a uma única causa. A contabilidade de alocações e o
RSS medem coisas diferentes; o contador MySQL registra blocos instrumentados
alocados e ainda não liberados. [Manual MySQL 8.0](https://dev.mysql.com/doc/refman/8.0/en/performance-schema-memory-summary-tables.html).

O cache de arquivos da VM oscilou entre 449 e 2.307 MiB, encerrando em 577 MiB.
Isso não é RSS do MySQL. O buffer pool permaneceu em 128 MiB. A coleta abrange
reset e bootstrap juntos: não separa picos dessas duas operações nem captura
todos os picos entre amostras. Comprimentos de SQL obtidos do Performance Schema
são comprimentos instrumentados, potencialmente truncados; não representam a
memória total da consulta. Nenhum texto SQL foi exportado.

## Persistência e I/O ainda merecem atenção

As duas confirmações de 5.500 req/s tiveram CPU ocupada da VM de 80,43% e 79,31%,
com iowait de 9,29% e 11,19%; o processo MySQL consumiu 65,44% e 65,20% de um
núcleo. No disco virtual foram observadas 1.634 e 1.594 escritas/s, 523 e 511
flushes/s e 26,10 e 25,79 MiB/s escritos. Médias por escrita: 0,370 e 0,424 ms;
por flush: 0,448 e 0,499 ms. Não houve novos buffer-pool reads, esperas por
buffer livre, log ou row lock nas janelas medidas.

O segundo ensaio longo teve um pico de atraso alinhado estimado em **47.573
transições**, por volta do segundo 200 da medição. No trecho anterior ao pico,
amostras de dois segundos mostraram até **67,0% de iowait**, escrita média de
**7,51 ms** e flush médio de **6,61 ms**, enquanto havia mais de 2,2 GiB disponíveis.
Após o pico, o atraso ficou abaixo de 3.000 transições em aproximadamente 60 s,
ainda com carga, e a drenagem final levou 0,794 s. A tendência final não foi de
crescimento e a auditoria confirmou todo o crédito.

Há evidência de um episódio de espera por I/O contribuindo para o atraso,
mesmo com folga de RAM. Não foi identificado o serviço ou componente físico
responsável. O host é compartilhado; esses dados não atribuem todo I/O físico
ao MySQL nem estabelecem a especificação de IOPS de um SSD substituto. O valor
47.573 é uma estimativa alinhada de aceitos menos persistidos, não leitura exata
da fila. A resposta HTTP rápida tampouco significa commit imediato no banco.

## Comparação com 2 GiB e próxima decisão

Com 2 GiB, a segunda confirmação foi interrompida no aquecimento, com RSS de
1.376,94 MiB e 251,42 MiB disponíveis. Com 4 GiB, a sequência concluiu com folga
de memória e correção preservada. Isso demonstra que **4 GiB foram suficientes
para este ensaio**; não demonstra que aumentar RAM corrigiu a causa do crescimento.
A execução anterior não possuía os instrumentos de alocação e foi feita em
outro horário, sem o coletor adicional. Não há prova retrospectiva de que o
mesmo mecanismo explique cada byte da interrupção anterior.

O candidato conserva os statements das consultas dinâmicas em lote nos pontos
de `persistence.rs` listados acima; a fila legada explicitamente usa
`.persistent(false)`. A medição fortalece a hipótese de custo do cache dessas
consultas. Não transforma esse custo em requisito inevitável do dualstack.
O SQLx 0.8.6 recomenda considerar desabilitar a persistência para lotes com
muitos comprimentos diferentes. [QueryBuilder](https://docs.rs/sqlx/0.8.6/sqlx/struct.QueryBuilder.html#method.push_values).

**Próxima decisão recomendada:** autorizar um controle A/B isolado, aplicando
`.persistent(false)` somente às consultas dinâmicas do coordenador, preservando
queries fixas, transações, limites e durabilidade. Comparar memória, quantidade
de prepares, CPU, latência, backlog e crédito com o mesmo protocolo em 4 GiB.
Preparar consultas novamente pode elevar CPU/latência; o benefício líquido
precisa ser medido. Só após essa avaliação decidir sobre retestar 2 GiB e
retomar a matriz. Nenhuma alteração de produto/cache foi feita neste diagnóstico.

## Encerramento e evidências do diagnóstico

Restaurados e conferidos os recursos das VMs 120/121/122: 4 vCPU/8 GiB, balloon
desligado. Supervisor inativo, lock disponível, announcer encerrado, MySQL/Redis
e arquivamento ativos, proprietário da base inativo. Configurações MySQL 1/1 e
buffer pool de 128 MiB preservadas. A base final permanece disponível; a cópia
privada da v2 não foi exportada. Nenhum novo ensaio foi iniciado.

Evidências em `lab/dualstack/results/capacity/capacity-memory-4g-v1/`:

- 137 arquivos públicos coletados, mais a verificação de recuperação e duas
  análises derivadas; nenhuma fixture privada ou binlog.
- `supervisor/capacity/capacity-memory-4g-v1/summary.json` e `memory-summary.json`:
  resultados, recursos e alocações por rodada.
- `analysis-verification.json`: nove auditorias revalidadas, 2.649 amostras dos
  observadores conferidas sem falha, identidade/endpoints/crédito e drenagens.
- `confirmation-lag-series.json`: reconstrução temporal do atraso nas duas
  confirmações e sua relação com os intervalos de I/O.
- `events.jsonl`, `probe-before-restore.json` e `recovery-verification.json`:
  marcos da execução, alocações antes do reboot e recuperação confirmada.

O acompanhamento foi encerrado após a análise. A campanha de CPU/RAM,
população/buffer pool e I/O permanece pendente da próxima decisão do usuário.

## A/B do cache de statements — autorizado em 10/10/2026

O usuário autorizou o controle recomendado. A referência **A é o dualstack
36823b5**, não a tag original 0.3.1. B contém somente oito acréscimos de
`.persistent(false)` às consultas dinâmicas de `persist_inner`. O patch
`lab/dualstack/capacity-cache-b.patch` está separado do checkout do produto;
consultas fixas, transações, pool, SQL, contabilidade e durabilidade não mudam.

Preparação concluída:

- B compilado com a mesma imagem Rust fixada, lockfile e perfil release;
  hashes e parâmetros em `lab/dualstack/capacity-cache-manifest.json`.
- A preservado: SHA-256 `25a9860c6caad0d78e2c3f8073f6ecd6822c05cbcd1b45773d0994a7df6d6833`.
- B experimental: SHA-256 `93ed97a5a50c3633452ba9eab56169b6eadadce53d5ccd4e2422edf3958c6057`.
- 25 testes passaram na primeira chamada; o contrato compartilhado, inicialmente
  ignorado pelo atributo do teste, passou na execução explícita: cinco testes,
  incluindo 12 cenários/51 operações. O teste de escala bootstrap com outro
  banco permaneceu fora deste escopo. Aviso preexistente de `fetch_update`
  obsoleto não foi alterado.
- Todos os arquivos do código-base conferidos: somente
  `src/dualstack/persistence.rs` difere, exatamente nos oito pontos previstos.
- Estado final de A1 preservado em arquivo privado de 8.076.478 bytes na VM de
  dados; SHA-256 `4f6cb24df298ecf4e3fd599a7dc0386cadcb9974b81a1d854c1bffc714551bc2`.
  Somente essa prova foi exportada, em `capacity-cache-previous-state.json`.

O primeiro preparo detectou conversão de finais de linha do Git no Windows;
o pacote foi refeito com `core.autocrlf=false` e conferido. A tentativa de usar
artefatos compilados sobre o ZFS revelou a restrição `noexec` do arquivo de logs.
A compilação limpa usou um bind temporário com execução permitida somente para
o diretório de build. Esse bind já foi desmontado e o arquivo permanece
`noexec,nosuid,nodev`. Ambos os binários serão executados no SSD da VM tracker.
Esses incidentes de preparação ocorreram antes de qualquer carga do A/B.

A calibração `capacity-cache-b-calibration-v1` falhou antes de iniciar o Rust:
o Docker não conseguiu montar a configuração no diretório somente leitura,
pois faltava o arquivo vazio `.env`. Nenhum announce foi enviado; versões e
crédito permaneceram zero. O container foi preservado e a restauração foi
executada separadamente, porque o encerramento estrito do supervisor recusou
o estado `created` com código 128. Isso é falha de preparação do laboratório,
não evidência sobre a variante B. A configuração real não foi copiada para B;
foi criado somente o arquivo vazio necessário para receber seu bind.

A nova calibração `capacity-cache-b-calibration-v2` **passou**: 10 s de
aquecimento + 30 s a 1.000 req/s, banco 1 vCPU/4 GiB; 40.000 announces,
zero erros/divergências, 2.003.200 bytes de crédito exato, 20.000 endpoints
válidos, drenagem em 0,731 s, saída zero e restauração 4 vCPU/8 GiB verificada.
Foram conferidas 107 amostras dos observadores e 25 de memória, sem falhas.
O verificador público também rejeitou divergências sintéticas de crédito e
de hash do binário, sem modificar a evidência real. Resultados em
`lab/dualstack/results/capacity/capacity-cache-b-calibration-v2/`.

Com os critérios de calibração atendidos, B completo foi iniciado; depois,
repetir A somente após conferir integridade, drenagem e restauração de B
(`capacity-cache-b-v1` e `capacity-cache-a-repeat-v1`) com as mesmas nove rodadas
de A1. As medições A1/B/A2 devem expor o possível benefício de memória junto
com o custo de CPU/preparações/latência e a variação do host compartilhado.
Nenhum resultado de benefício ou aprovação de incorporação está declarado.

### B concluído e repetição A2 iniciada — 2026-10-10

`capacity-cache-b-v1` completou as nove rodadas entre 15:52:50 e 16:20:56 UTC.
O verificador confirmou **5.550.000 announces, 277.523.200 bytes de crédito,
zero erros e zero divergências por identidade**, versões, endpoints e
contadores corretos. Os 10.000 peers mantiveram 20.000 endpoints válidos.
As nove drenagens terminaram com saída zero, sem OOM, entre 0,730 e 1,436 s;
o hash corresponde a B em todas elas. As proteções não foram acionadas.

Foram analisadas 2.662 amostras dos observadores e 319 do coletor de memória,
sem falhas. O MySQL manteve o mesmo PID durante B. Os 502 instrumentos de
memória estavam habilitados, sem perda de prepared statements, e houve no
máximo cinco conexões, incluindo observação. O intervalo máximo entre coletas
foi 5,739 s; a consulta do coletor levou mediana de 112,44 ms e máximo de
268,89 ms (A1: 111,68/287,62 ms). Picos entre coletas podem escapar à amostragem.

Abaixo estão diferenças **provisórias A1/B**, aguardando a repetição A2.
A é o candidato dualstack `36823b5`, não a versão original 0.3.1.

| Medida MySQL, série completa | A1: cache existente | B: oito consultas sem cache |
|---|---:|---:|
| Pico RSS | 1.245,75 MiB | 559,86 MiB |
| Pico PSS | 1.245,94 MiB | 560,00 MiB |
| Pico de memória anônima | 1.210,95 MiB | 525,02 MiB |
| Pico de memória de arquivos | 34,99 MiB | 34,98 MiB |
| RSS antes da restauração | 1.215,86 MiB | 559,86 MiB |
| Pico de memória instrumentada | 958,74 MiB | 476,51 MiB |
| Pico do grupo `memory/sql` | 515,42 MiB | 31,13 MiB |
| Pico `Prepared_statement::main_mem_root` | 488,14 MiB | 8,18 MiB |
| Pico `Prepared_stmt_count` | 301 | 20 |
| Preparações durante a série | 63.527 | 147.681 |
| Execuções de statements durante a série | 125.255 | 124.630 |

O pico RSS caiu **55,1%** e o pico instrumentado de prepared statements caiu
**98,3%**, enquanto as preparações aumentaram **2,32 vezes**. Esses contadores
incluem o ciclo de reset/bootstrap e observação; a quantidade de execuções
também depende do agrupamento dos lotes. Não são custos exatos por announce.
O número de fechamentos explícitos foi 44.837/110.556; sua diferença para
preparações não prova vazamento, pois há fechamento implícito de conexões.

Em B, as amostras após cada encerramento mostram zero prepared statements e
zero alocação correspondente. O RSS continuou retido, mas em nível menor:
de aproximadamente 474 MiB após a primeira rodada até 560 MiB após a última.
Na primeira confirmação ficou em 554,87 MiB; na segunda variou de 559,23 a
559,86 MiB durante a carga. O reset e bootstrap entre elas também alocam
memória. Antes de restaurar, os principais grupos instrumentados eram
`performance_schema` 230,02 MiB, InnoDB 202,25 MiB e SQL 20,84 MiB, próximos
de A1 após encerrar as conexões. Isso apoia a hipótese sobre retenção das
consultas dinâmicas; ainda não atribui retrospectivamente toda a proteção de
2 GiB ao cache nem comprova ausência de crescimento em execução prolongada.

Nas duas janelas medidas de **300 s a 5.500 req/s**:

| Medida | A1 confirmação 1 / 2 | B confirmação 1 / 2 |
|---|---:|---:|
| Throughput HTTP (req/s) | 5.500,00 / 5.500,00 | 5.499,99 / 5.500,00 |
| p95 da resposta HTTP (ms) | 0,3104 / 0,3107 | 0,3132 / 0,3145 |
| p99 da resposta HTTP (ms) | 0,3586 / 0,3590 | 0,3608 / 0,3644 |
| CPU MySQL, percentual de um núcleo | 65,44 / 65,20 | 70,46 / 70,91 |
| CPU Rust, percentual de um núcleo | 36,46 / 36,45 | 39,90 / 40,18 |
| RSS mediano Rust (MiB) | 32,45 / 31,29 | 29,16 / 29,10 |
| CPU ocupada da VM de dados (%) | 80,43 / 79,31 | 84,94 / 84,45 |
| iowait da VM de dados (%) | 9,29 / 11,19 | 8,38 / 8,76 |
| Escritas/s no dispositivo virtual | 1.634 / 1.594 | 1.625 / 1.632 |
| Flushes/s no dispositivo virtual | 523 / 511 | 522 / 523 |
| Escrita no dispositivo virtual (MiB/s) | 26,10 / 25,79 | 26,06 / 26,09 |
| Pico de atraso estimado (announces) | 16.704 / 47.573 | 16.482 / 16.289 |
| Drenagem (s) | 0,733 / 0,794 | 0,742 / 1,436 |

Os percentis pertencem a cada janela; não são percentis globais combinados.
O gerador usou aproximadamente 81% de um núcleo em B, com throughput alvo
alcançado. O maior custo de CPU observado no MySQL e no Rust precisa ser
comparado com A2. Nenhuma alteração de durabilidade, buffer pool, pool de
conexões ou tamanho de lote foi feita. As confirmações não registraram novas
leituras físicas InnoDB, log waits ou row lock waits. O I/O descrito é da VM,
não atribuição exclusiva de todo I/O físico do SSD compartilhado ao MySQL.

**B não passou em todos os critérios de estabilidade de desempenho.** A rampa
de 6.000 req/s terminou com atraso estimado de 6.971 announces e crescimento
detectado de 3.044, acima da resolução de 2.096. Drenou em 1,375 s. Na primeira
confirmação a 5.500 req/s, o crescimento detectado foi 2.525, acima da resolução
de 2.186, em aproximadamente 100 s. Sua série mostra picos transitórios:
16.482 aos 242,8 s, recuando a 2.046 na última amostra aos 298,8 s. A mediana
da janela 240–270 s foi 11.504; a de 270–300 s foi 2.684. Portanto, não foi
crescimento monotônico, mas também não se deve ignorar o critério reprovado.
A segunda confirmação teve pico de 16.289 aos 116,2 s, última amostra de
907 aos 298,2 s e nenhuma tendência crescente detectada. A1 também apresentou
picos e recuperação, incluindo 47.573 na segunda confirmação. O atraso é uma
estimativa com alinhamento temporal, não uma leitura direta da fila em memória.

Após B, foram confirmados lock livre, nenhum announcer ativo, arquivamento
ativo, hash de A intacto e recursos efetivos das VMs 120/121/122 restaurados
para 4 vCPU/8 GiB. A prova está em `recovery-verification.json`. Com os critérios
de correção/drenagem/restauração atendidos, o plano e o checkpoint foram
atualizados **antes** de iniciar `capacity-cache-a-repeat-v1`, às 16:27:37 UTC.
A2 repetirá o mesmo protocolo. Não houve promoção do patch ao produto, novo
ensaio com 2 GiB ou retomada da matriz geral. A conclusão A1/B/A2 permanece
pendente, considerando a variação temporal do host compartilhado.

Evidências públicas: `lab/dualstack/results/capacity/capacity-cache-b-v1/`,
incluindo `analysis-verification.json`, `memory-summary.json`, `summary.json`,
as nove drenagens e `provisional-a1-b-review.json` com as janelas de 30 s.

### A/B concluído: benefício de memória com custo de CPU — 2026-10-10

A2 (`capacity-cache-a-repeat-v1`) terminou às **16:55:49 UTC**, com as nove
rodadas completas. O verificador confirmou 5.550.000 announces, 277.523.200
bytes de crédito exato, zero erros/divergências, 10.000 identidades e 20.000
endpoints válidos, versões e contadores corretos. As nove drenagens tiveram
saída zero e nenhum OOM, em 0,729–0,774 s, usando o hash esperado de A.
Não houve `reason` de interrupção nem `probe_failures`. A restauração para
4 vCPU/8 GiB das VMs 120/121/122 foi conferida ao vivo; nenhum announcer ficou
ativo, o lock estava livre e o arquivamento continuava ativo. A base final
permanece preservada. A1/B/A2 somaram 27 rodadas e **16.650.000 announces**
com contabilidade correta; isso não equivale a 27 aprovações de desempenho.

A comparação abaixo fecha este experimento. **A1 e A2 usam o candidato
dualstack `36823b5`; B muda somente o cache das oito consultas dinâmicas.**
Não é comparação com o Rust original 0.3.1. O banco ficou em 1 vCPU/4 GiB,
buffer pool 128 MiB, durabilidade 1/1; tracker e clientes em 4 vCPU/8 GiB.

| Memória MySQL, série completa | A1 | B | A2 |
|---|---:|---:|---:|
| Pico RSS (MiB) | 1.245,75 | 559,86 | 1.389,38 |
| Pico PSS (MiB) | 1.245,94 | 560,00 | 1.389,52 |
| Pico anônimo (MiB) | 1.210,95 | 525,02 | 1.354,57 |
| Pico de arquivos (MiB) | 34,99 | 34,98 | 34,95 |
| RSS após encerrar conexões, antes da restauração (MiB) | 1.215,86 | 559,86 | 1.376,00 |
| Pico instrumentado total (MiB) | 958,74 | 476,51 | 961,37 |
| Pico grupo SQL (MiB) | 515,42 | 31,13 | 517,56 |
| Pico `Prepared_statement::main_mem_root` (MiB) | 488,14 | 8,18 | 490,32 |
| Pico de statements | 301 | 20 | 301 |
| Preparações | 63.527 | 147.681 | 61.219 |
| Execuções | 125.255 | 124.630 | 125.388 |

**B economizou 686–830 MiB no pico RSS, ou 55,1–59,7% frente às duas
execuções de A.** A alocação instrumentada de prepared statements caiu cerca
de 98,3%; preparações cresceram 2,32–2,41 vezes, com execuções próximas.
A volta do consumo elevado em A2 reforça a evidência de contribuição do cache.
Há diferença de RSS entre A1 e A2 mesmo com alocação instrumentada semelhante;
isso impede tratar RSS como soma exata dos statements ou como constante por peer.
O resultado não comprova que toda a proteção anterior em 2 GiB teve essa causa.

A2 manteve um único PID MySQL durante a série. Após cada encerramento, os
statements e sua alocação instrumentada zeraram; o RSS permaneceu alto. Na
primeira confirmação subiu de 1.212,13 para 1.389,38 MiB; na segunda, de
1.371,75 para 1.376,00 MiB. Depois das conexões, a memória instrumentada total
voltou a 463,57 MiB, próxima de A1/B (464,06/464,23). Predominaram
`performance_schema` 230,02 MiB, InnoDB 202,08 MiB e SQL 20,35 MiB. O comportamento
é compatível com retenção/fragmentação do alocador; não prova vazamento ilimitado.
Esses números incluem a instrumentação habilitada, que também ocupa memória.

As 319 amostras de memória de A2 e 2.659 dos observadores não tiveram falhas.
Os 502 instrumentos permaneceram habilitados, com zero perdas e até cinco
conexões, como A1/B. A consulta do coletor levou mediana de 104,87 ms, máximo
de 238,55 ms; o maior intervalo entre amostras foi 5,001 s. A menor memória
disponível observada na VM foi 2.043,44 MiB, longe da proteção de 256 MiB.
Foram examinados os intervalos antes/durante/depois e reset/bootstrap, sem
atribuir automaticamente todas as alocações desses intervalos ao announce.

| Janelas medidas de 300 s a 5.500 req/s (confirmação 1 / 2) | A1 | B | A2 |
|---|---:|---:|---:|
| Throughput HTTP (req/s) | 5.500,00 / 5.500,00 | 5.499,99 / 5.500,00 | 5.500,00 / 5.500,00 |
| p95 HTTP (ms) | 0,3104 / 0,3107 | 0,3132 / 0,3145 | 0,3193 / 0,3104 |
| p99 HTTP (ms) | 0,3586 / 0,3590 | 0,3608 / 0,3644 | 0,3648 / 0,3575 |
| CPU MySQL, % de um núcleo | 65,44 / 65,20 | 70,46 / 70,91 | 63,72 / 62,98 |
| CPU Rust, % de um núcleo | 36,46 / 36,45 | 39,90 / 40,18 | 36,55 / 36,35 |
| CPU ocupada VM de dados (%) | 80,43 / 79,31 | 84,94 / 84,45 | 78,69 / 76,94 |
| iowait VM de dados (%) | 9,29 / 11,19 | 8,38 / 8,76 | 9,45 / 9,66 |
| Escritas/s, dispositivo virtual | 1.634 / 1.594 | 1.625 / 1.632 | 1.607 / 1.580 |
| Flushes/s, dispositivo virtual | 523 / 511 | 522 / 523 | 512 / 504 |
| Escrita, dispositivo virtual (MiB/s) | 26,10 / 25,79 | 26,06 / 26,09 | 25,97 / 25,86 |
| Pico de atraso estimado (announces) | 16.704 / 47.573 | 16.482 / 16.289 | 13.302 / 13.346 |
| Drenagem (s) | 0,733 / 0,794 | 0,742 / 1,436 | 0,734 / 0,774 |

O custo observado em B foi **mais 5,0–7,9 pontos percentuais de um núcleo no
MySQL** (7,7–12,6% relativos) e 3,4–3,8 pontos no Rust (9,2–10,5% relativos),
considerando as faixas das confirmações de A1/A2. Essas faixas descrevem as
medições, não intervalos estatísticos de confiança. O p99 de B ficou dentro
da faixa vista nas duas execuções de A; não há aumento inequívoco de latência
HTTP nessa comparação. As respostas não esperam o commit, portanto isso
não demonstra a mesma folga de persistência. Os geradores atingiram a carga
alvo e usaram aproximadamente 80–83% de um núcleo nessas janelas.

O patch **não reduziu materialmente a escrita em disco**: ficaram próximos
os volumes, escritas/s e flushes/s. As seis confirmações não apresentaram
novas leituras físicas InnoDB, espera por buffer livre, log waits ou row lock
waits. Isso descreve uma base aquecida pequena; não responde ainda à escala
com população maior ou buffer pool insuficiente. Não é possível converter
esses IOPS da VM em requisito universal de SSD nem atribuir todo I/O físico
compartilhado ao MySQL. Durabilidade 1/1 foi preservada na prova final.

O exame das 27 séries confirma que A1/A2 ficaram dentro do detector de
estabilidade, enquanto B reprovou a rampa de 6.000 req/s e a primeira
confirmação a 5.500 req/s. Os detalhes de B estão na seção anterior. Em A2,
o pico da primeira confirmação ocorreu aos 248,3 s (13.302), com mediana de
3.284 na janela 240–270 s e 1.159 em 270–300 s; a última amostra ficou em
3.814. Na segunda, o pico foi 13.346 aos 102,5 s, mediana de 2.179 entre
90–120 s e 1.170 entre 120–150 s; a última amostra foi 1.246. As duas
drenaram integralmente. A1 teve pico bem maior que B, evidenciando variação
temporal; não se deve apresentar o máximo isolado como melhoria causal de B.

**Conclusão e próxima decisão:** o experimento sustenta a economia de memória
do cache seletivo e mostra seu custo de CPU/preparação. Recomendo considerar
B para instalações com pressão de RAM, preservando margem de CPU e
revalidando a taxa sustentável antes de adotá-lo. Não aprovo 5.500 req/s
sustentados em B com este banco de um núcleo: uma confirmação reprovou.
Também não aprovo instalação com 2 GiB a partir do ensaio feito com 4 GiB.
Manter A preserva a menor demanda de CPU observada, ao custo de mais memória.
A decisão entre essas opções, incorporação ao produto e novos ensaios cabe ao
usuário. Não houve promoção, alteração de durabilidade ou retomada da matriz.

A ordem A1/B/A2 no host compartilhado não elimina interferência nem substitui
repetições randomizadas; percentis são por janela e as confirmações duraram
cinco minutos. A campanha geral de CPU/RAM, população/buffer pool e I/O segue
pendente. O acompanhamento deste A/B é encerrado ao registrar a conclusão.

Evidências adicionais: `lab/dualstack/results/capacity/capacity-cache-a-repeat-v1/`
e `lab/dualstack/results/capacity/capacity-cache-ab-comparison.json`. O script
`lab/dualstack/compare-capacity-cache.py` reproduz a comparação pública das
27 rodadas e verifica contagem/pico das amostras alinhadas contra os resumos
originais. Nenhum dado privado foi exportado.
