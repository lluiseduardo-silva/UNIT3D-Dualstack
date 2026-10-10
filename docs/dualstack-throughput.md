# Throughput do announcer Rust

Estudo concluído no laboratório isolado. Plano:
`docs/plans/2026-10-08-throughput-rust.md`. Produtos preservados em
`6d8e7437` (UNIT3D) e `a9ab263d` (UNIT3D-Announce).

## Pergunta e método

Separar requests respondidos de transições confirmadas no MySQL. Resposta HTTP
rápida com fila crescente não demonstra capacidade sustentável.

A cópia experimental instrumenta espera e ocupação do mutex nas operações de
publicação e seleção, duração dos lotes e suas etapas, versões confirmadas,
backlog e retries. Os contadores são cumulativos, limitados e sem identidades.
As médias são deltas dentro da janela medida; não são percentis de spans.
Os percentis HTTP são recalculados a partir de todas as amostras exportadas.

Fixture principal: 10 mil peers, 40 torrents de 250 peers, 250 usuários
compartilhados entre torrents, 20 mil endpoints, 100% dualstack, 80% seeders.
Somente seeders anunciam; cada resposta contém dez peers leechers, ambos os
endpoints, 349 bytes de corpo. Os valores IPv4/IPv6 compartilham o contador.
Não representa dez mil usuários independentes nem churn de endereços.

Política: mesma versão/compilação release, numwant 10, conexão persistente,
conectividade e log de announce desligados, origens reais nas duas famílias.
O HTTP alcança diretamente o Rust, sem Nginx. Banco MySQL 8.0.46 com buffer
pool de 128 MiB, REPEATABLE-READ, flush-at-commit=1 e sync-binlog=1.

## Primeiro resultado confirmado

Rampa com 5 segundos de aquecimento e 15 segundos medidos por fase, drenando
antes da próxima. Ordem de chegada intercalada entre torrents.

| Entrada req/s | HTTP concluído/s | Confirmações/s | Crescimento da fila/s | Drenagem final |
|---:|---:|---:|---:|---:|
| 1.000 | 999,9 | 1.000,1 | ~0 | 0,27 s |
| 1.800 | 1.799,9 | 1.799,9 | ~0 | 0,27 s |
| 2.000 | 1.999,9 | 2.000,1 | ~0 | 0,27 s |
| 2.500 | 2.500,0 | 1.999,9 | 500,1 | 5,22 s |
| 3.000 | 3.000,0 | 1.999,9 | 1.000,1 | 10,17 s |
| 4.000 | 3.999,9 | 1.999,9 | 2.000,1 | 20,07 s |

O p99 HTTP permaneceu entre 0,228 e 0,239 ms. A 4.000 req/s, o lote levou
21,55 ms em média, mas o gravador fez dez lotes/s: cerca de 21,6% do tempo
estava no processamento/persistência de lotes. O restante inclui a espera pelo
tick e manutenção; não é CPU ocupada. A cadência do código é o primeiro limite
confirmado neste perfil, não a capacidade física do SSD.

Referências do código preservado: `repos/UNIT3D-Announce/src/dualstack/coordinator.rs:46`
(lote 200), `coordinator.rs:294` (um lote por flush) e `coordinator.rs:345`
(tick de 100 ms). Publicação e seleção usam o mesmo mutex em
`coordinator.rs:208` e `response.rs:99`; a seleção percorre o torrent em
`response.rs:127`.

Na mesma janela, ocupação média do mutex: publicação 2,65 µs e seleção 4,28 µs;
espera média: 0,031 µs para ambas. Rust usou cerca de 20% de um núcleo; MySQL,
20,9% de um núcleo. As VMs têm quatro vCPUs cada. Esses números não apontam
saturação de CPU ou contenção do mutex com 250 peers/torrent nesta taxa.

I/O da VM de dados: 661 writes/s, 10,89 MiB/s, escrita média 0,324 ms,
flush médio 0,481 ms; zero novos waits de row lock, redo ou buffer livre,
e zero leituras físicas do buffer pool na janela. Isso não exclui interferência
do SSD compartilhado em outras cargas ou taxas.

Evidência: `lab/dualstack/results/throughput/density-throughput-ramp-v1-analysis.json`.

## Verificações já concluídas

- Suíte `dualstack_mysql` na cópia experimental com drenagem habilitada:
  1 teste composto aprovado em 57,92 s; reentrega, restart, fila cheia, rollback,
  quatro threads, zero SQL em publish, TTL, seleção, retenção, administração,
  lock timeout, deadlock real, lease e falha do supervisor.
- Smoke: 16 mil announces, duas fases, contabilidade exata.
- Rampa atual: 286 mil announces, seis fases, sem erros, drops ou divergências;
  auditoria local das 214.500 amostras medidas aprovada.

## Drenagem e tamanho dos lotes

A variante experimental mantém um escritor, transações, versões e fence.
Quando existe ao menos um lote completo pendente, ela cede execução ao runtime
e volta a drenar sem esperar o próximo tick. Heartbeat, manutenção e shutdown
continuam supervisionados. Não houve consultas SQL novas por announce.

| Variante/carga | Resultado observado |
|---|---|
| Atual, lote 200, entrada 4 mil/s | Confirma ~2 mil/s; fila cresce ~2 mil/s; drena em 20,07 s |
| Drenagem, lote 200, entrada 4 mil/s | Confirma ~4 mil/s; drena em 0,27 s |
| Drenagem, lote 200, entrada 6 mil/s | Acompanha nas três repetições dispersas, mas há oscilações; pico de fila 7.459 |
| Drenagem, lote 500, entrada 6 mil/s | Três repetições; fila amostrada até 1.450; drenagem 0,27 s |
| Drenagem, lote 500, entrada 8 mil/s | 180 s medidos; ~8 mil confirmações/s; fila final próxima da inicial |
| Drenagem, lote 500, entrada 10 mil/s | Três janelas curtas; 9.951–9.999 confirmações/s, pouca margem |
| Drenagem, lote 500, entrada 12 mil/s | HTTP entrega 12 mil/s; banco confirma 9.964/s; fila cresce 2.036/s |

As repetições dispersas embaralham os peers com seed fixa, mantendo os dois
requests de cada identidade próximos. A ordem original agrupava mais os
usuários entre torrents. A diferença altera a consolidação dos lotes; não é
correto extrapolar uma única ordem como capacidade universal.

Na comparação dispersa a 6 mil/s, medianas das três repetições:

| Medida | Lote 200 | Lote até 500 |
|---|---:|---:|
| Transições efetivas por lote | ~199 | ~476 |
| Duração média do lote | 27,59 ms | 44,27 ms |
| CPU do MySQL, percentual de um núcleo | 71,9% | 56,9% |
| Escrita da VM de dados | 31,55 MiB/s | 27,69 MiB/s |
| Iowait da VM de dados | 18,0% | 11,0% |

O lote maior demora mais individualmente, mas confirma mais transições por
operação. Neste perfil reduziu CPU e I/O por request. Ele também aumenta o
tempo durante o qual uma transação pode manter locks: o valor 500 é uma opção
experimental validada aqui, não uma recomendação de aumentar indefinidamente.

## Onde fica o próximo limite

Na fase de 12 mil req/s, o gravador passou **99,85% do tempo** dentro de
persistência. Com 500 transições e **50,10 ms/lote**, a capacidade observada
fica perto de **10 mil confirmações/s**. O limite mudou da espera artificial
pelo timer para o custo do caminho de persistência.

| Etapa do lote | Média | Fração aproximada |
|---|---:|---:|
| Regravação dos endpoints | 14,04 ms | 28% |
| Atualização de saldos e contadores | 11,52 ms | 23% |
| Commit | 7,29 ms | 15% |
| Persistência do peer | 5,73 ms | 11% |
| Histórico | 5,38 ms | 11% |
| Fence e leituras bloqueantes | 5,37 ms | 11% |

Spans incluem construção da consulta, espera pelo servidor e retorno de rede;
não são CPU SQL isolada. A soma pode diferir ligeiramente por arredondamento e
lotes que atravessam os limites da janela. O servidor também registrou 9,72 s
em execução de prepared statements e 1,73 s em commits numa janela de 12,46 s.

O código substitui os endpoints com DELETE e INSERT em
`repos/UNIT3D-Announce/src/dualstack/persistence.rs:328` e atualiza os deltas
por CASE em `persistence.rs:351`. Essas duas etapas concentram aproximadamente
metade do tempo do lote. São os próximos candidatos a otimização mensurável.

Na mesma fase: Rust 53,5% de um núcleo; MySQL 97,3% de um núcleo agregado,
com as threads de conexão alternando a execução. Nenhuma thread de banco
amostrada manteve um núcleo saturado durante toda a janela. Espera média pelo
mutex: publicação 0,050 µs, seleção 0,034 µs; ocupação média 2,47 e 4,42 µs.
Portanto, **mais vCPUs ou dividir agora o mutex global não ataca o limite
observado com 250 peers/torrent**. Para torrents muito densos, a conclusão
anterior sobre a varredura linear continua válida; ver `dualstack-densidade.md`.

O banco escreveu 43,61 MiB/s, com ~2.612 writes/s e ~849 flushes/s. Iowait:
21,0%; tempo ocupado do dispositivo virtual: 78,3%; escrita média 0,385 ms,
flush médio 0,507 ms. Não ocorreram novos waits de redo/buffer livre nem
leituras físicas do buffer pool. Houve quatro esperas de row lock somando
43 ms, sem deadlock, timeout ou retry durante a carga.

**O I/O participa do próximo limite e das oscilações.** Isso não demonstra
que trocar apenas o SSD produziria um ganho específico: disco físico,
virtualização e cargas concorrentes não foram isolados. As anomalias já
conhecidas de tempo acumulado de escrita no host continuam sinalizadas nos
relatórios; os contadores brutos foram preservados. Não houve alteração de
durabilidade, cache do disco, buffer pool, hardware ou kernel.

Redis não participa do caminho Rust medido; CPU observada permaneceu residual.
Nginx não estava entre o gerador e o Rust. Logo, nenhum dos dois explica o teto
de confirmação encontrado neste ensaio. Uma implantação com proxy, TLS,
checagem de conectividade e logging precisa de sua própria medição.

## Sustentação, controles e alcance

O ensaio de 8 mil/s teve 10 s de aquecimento e 180 s medidos: **1.520.000
announces aceitos**, sendo 1.440.000 amostras medidas. HTTP: 7.999,99 req/s;
confirmações: 7.999,47/s. Fila amostrada de 748 no início e 844 no fim,
com pico de 7.718 durante oscilações e recuperação posterior. Drenagem final:
0,27 s; p99 HTTP: 0,257 ms. Nenhum retry, erro, drop ou divergência.

Isso demonstra **quatro vezes a taxa sustentada por três minutos** frente
ao patamar de 2 mil/s do gravador atual, nas condições do ensaio. A faixa de
10 mil/s teve somente janelas curtas; não é um compromisso de capacidade em
produção. O teto de respostas HTTP não foi encontrado: ele respondeu até
12 mil/s enquanto a persistência ficou atrás.

Controles a 4 mil/s: p99 de 0,230 ms no binário preservado, 0,225 ms na cópia
com métricas desligadas, 0,228 ms na rampa instrumentada; CPU ~20% de um núcleo
nos três. São controles curtos, não uma estimativa precisa de overhead.

Para subir a carga, o gerador passou a pré-calcular os campos HTTP constantes.
Ele confere igualdade dos bytes com o caminho anterior antes de usá-los em cada
worker/família, e mantém todas as verificações de resposta e contabilidade.
O smoke desse caminho aceitou 40 mil requests antes das rampas maiores.
A espera local de agendamento está publicada separadamente: p99 chegou a
20,59 ms a 12 mil/s. O p99 HTTP mede envio até leitura no cliente e não inclui
essa espera anterior; não deve ser apresentado como latência total. A CPU do
gerador é média da fase incluindo drenagem, não só da janela de tráfego.

## Ajustes recomendados e validação para incorporar

1. Incorporar drenagem quando houver backlog, com orçamento explícito de
   trabalho, yield, manutenção, heartbeat e encerramento. Manter os limites de
   fila e a rejeição explícita quando não há capacidade; ampliar a fila não
   aumenta throughput.
2. Tornar o lote configurável dentro do limite validado de 500 e comparar
   200/500 com o tráfego do operador. Preservar um escritor inicialmente.
   Antes de promover: repetir os contratos, concorrência com BON/refunds,
   falhas, troca de backend e benchmarks formais na implementação definitiva.
3. Otimizar a persistência de endpoints para evitar DELETE/INSERT integral
   quando bastaria atualizar um caminho, preservando encerramento, expiração,
   revisão e idempotência. Investigar os UPDATE CASE de saldos/contadores com
   consultas equivalentes e os mesmos testes financeiros. Medir bytes de redo,
   tempo de lote e locks antes/depois.
4. Reservar contadores incrementais e seleção indexada para o caso de torrents
   densos ou evidência de contenção futura. Um contador cacheado precisa tratar
   TTL, mudança de família, stop, exclusão e conectividade; simplesmente somar
   endpoints ou ignorar expiração violaria o contrato.

## Evidências e encerramento

**12 séries, 40 fases, 4.622.000 announces aceitos e 3.821.500 amostras medidas.**
Auditoria recalculou os percentis e verificou hashes, versões, saldos e endpoints
de todas as séries. Zero divergência contábil, erros HTTP, drops e aumento de
deadlocks/timeouts durante as cargas. A suíte de falhas provocou os locks
esperados separadamente; não confundir seus contadores históricos com falhas
dos benchmarks.

Após drenar, o binário experimental reiniciou e abriu listeners nas duas
famílias. Depois de encerrá-lo novamente, o estado confirmado permaneceu igual:
10 mil peers, 20 mil endpoints, 1.520.000 versões e 76.000.000 bytes em cada
uma das somas de referências, históricos e usuários. A geração avançou uma vez.
Não foram enviados announces nessa verificação adicional de restart; o contrato
de crédito após reconexão foi exercitado na suíte MySQL.

Lease inativa, zero consultas ativas no banco de testes, nenhum listener ou
container de tracker, zero aliases/namespaces temporários. As VMs de dados
continuam disponíveis, e a cópia experimental permanece para reprodução.
Os hashes do código foram comparados com os checkouts limpos; somente cinco
arquivos Rust diferem na cópia de laboratório, incluindo o módulo de métricas.

Entradas: `lab/dualstack/throughput-plans.py` e `lab/dualstack/plans/`.
Preparação: `prepare-throughput-copy.py`, `throughput-metrics.rs` e
`throughput-backend.sh` no diretório do laboratório. Execução:

```powershell
./lab/dualstack/run-density-survey.ps1 `
  -PlanFile lab/dualstack/plans/density-throughput-sustained-v1.json `
  -IdentityFile <chave-do-laboratorio> -Study throughput -Mode drain -Batch 500
```

O runner recusa resultados existentes; use outro nome para repetir. O laboratório
precisa estar provisionado, os helpers copiados e os aliases adicionados pelo
script existente. Nunca reutilizar essa inicialização contra um banco real.

Resultados: `lab/dualstack/results/throughput/summary.json`, análises por série,
amostras compactadas, métricas, I/O e snapshots. Checkpoint:
`lab/dualstack/checkpoint-throughput.json`. Não substitui os gates anteriores
de regressão, a matriz de 0/50/100% dualstack, TLS/proxy ou o ensaio de seis horas.
Nenhuma otimização foi aplicada aos produtos ou à produção.

Revisão final única contra o plano: instrumentação e variantes confinadas ao
laboratório, controles e refinamentos documentados, contabilidade e recuperação
verificadas, dados brutos auditados e limpeza concluída. Foram reforçados os
guards de identidade do código e de ação do runner. O levantamento do mutex
não justificou implementar sua divisão neste perfil; essa decisão está
fundamentada nas medições, e não representa um teste omitido.
