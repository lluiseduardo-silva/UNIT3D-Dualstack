# Baseline Rust original — 9 de outubro de 2026

Execução autorizada do Rust 0.3.1, commit
`fcd189e9aebf07a12a1f8cc39500819c3870925b`, sem correções de produto aplicadas.
Esta etapa precede o par PHP versus PHP. A série formal é
`rust-original-formal-v1`; cada repetição tem nome `rust-original-formal-rN-v1`.

**Concluído e aprovado neste perfil:** três repetições, **28.800.000 requests
aceitos**, zero erros e zero divergências contábeis. A carga começou em
**09/10/2026 às 18:47:26**; a série terminou, após drenagens e auditorias, às
**19:50:29, Brasília**. Conferência e coleta final realizadas no acompanhamento
das 20:02. Monitor `acompanhar-baseline-rust-original` desativado (`PAUSED`).
[Estado final da série](../lab/dualstack/results/soak/rust-original-formal-v1/status.json).

Após esse fechamento, o [ensaio separado de seis horas do original](dualstack-rust-original-prolongado.md)
também passou: de 20:27 de 09/10 a 02:33 de 10/10, incluindo drenagem, com
175.346.000 aceitos, zero erros e replay contábil completo aprovado. O monitor
foi novamente desativado. Os perfis e as evidências permanecem separados,
inclusive a diferença de payload e a variação de latência do prolongado.

## Perfil e comparação

- Três repetições com reinício do backend e fixture limpa entre elas.
- Por repetição: 300 segundos de aquecimento e 900 de medição, a 8.000 req/s.
- 10.000 peers em 40 torrents de 250, 250 usuários, 80% seeders.
- IPv4 observado na conexão, 72 origens reais; sem headers simulando IPs.
- Seeders anunciam `completed` repetidamente e incrementam 100 bytes por request.
  Leechers residentes fornecem a lista. `numwant=10`; HTTP direto com keep-alive.
- Sem verificação de conectividade ou log de announces. Respostas, listas,
  contadores, créditos por identidade e totais são conferidos.
- Calibração anterior: 30 segundos de aquecimento e 60 de medição, mesmo perfil.

O candidato precisa repetir **este mesmo perfil** antes do veredito p95/p99
até +10% / throughput pelo menos 95%. A v3 dualstack de seis horas tem outra
carga e não é o par desta comparação. Esta taxa fixa mede sustentação, não o
throughput máximo. Não encerra a matriz de famílias, escalas e distribuições.
As três repetições do original sequenciais não controlam perfeitamente variações
da carga dos outros serviços no SSD; registrar isso ao confrontar o candidato.

## Resultados formais

Cada linha abaixo corresponde somente à janela de **900 segundos de medição**,
com 7.200.000 requests aceitos. O aquecimento não entra nesses percentis. A
resposta mede do início do envio até sua leitura; o tempo total também inclui
a espera no gerador e a validação da resposta.

| Repetição | Req/s concluídos na janela | Resposta p95 (ms) | Resposta p99 (ms) | Total p99 (ms) | Drenagem contábil (s) |
|---|---:|---:|---:|---:|---:|
| r1 | 7.999,998 | 0,198607 | 0,311351 | 2,982941 | 5,468 |
| r2 | 7.999,999 | 0,199407 | 0,311976 | 3,083003 | 3,647 |
| r3 | 7.999,999 | 0,207582 | 0,318935 | 2,880360 | 4,170 |

A mediana **entre as três estimativas** de p95 é 0,199407 ms e de p99 é
0,311976 ms. Não são percentis globais de todas as amostras. Histogramas mantêm
a aproximação documentada de até 0,1% + 1 microssegundo. A diferença de um ou
dois requests no throughput decorre da fronteira temporal da janela; todos os
7.200.000 requests foram aceitos, sem descarte. São 21.600.000 requests medidos
e 7.200.000 de aquecimento ao somar as três execuções.

Em **cada** repetição, os 9.600.000 requests produziram 960.000.000 bytes em
referências, históricos e saldos, com zero divergências por identidade nos
10.000 peers e 250 usuários. O replay das amostras foi confrontado com o MySQL
**antes de cada reset**, pelo supervisor. Não foi reexecutado contra uma base
que já pertencia à repetição seguinte. Somados entre execuções independentes,
são 2.880.000.000 bytes; o banco final da r3 contém 960.000.000, pois os dados
foram reinicializados entre repetições.

`tracker_drain=passed` nas três, processos encerrados normalmente, serviço da
série `Result=success`, `ExecMainStatus=0`, `ActiveState=inactive`. Os aliases
temporários foram removidos; o container de evidência da v2 continua preservado.
Os gates de crédito, contagem, jobs e ausência de aumento dos contadores de
deadlock/timeout passaram no executor. Nenhum observador registrou falha ou
reinício do MySQL.

## Recursos e persistência observados

| Repetição | Pico RSS Rust (MiB) | RSS Rust final amostrado (MiB) | CPU Rust (% de um núcleo) | Maior atraso estimado em créditos de 100 bytes |
|---|---:|---:|---:|---:|
| r1 | 37,30 | 26,50 | 31,10 | 70.588 |
| r2 | 34,91 | 27,39 | 31,73 | 73.151 |
| r3 | 34,66 | 24,95 | 31,87 | 76.161 |

CPU é a média entre as amostras do processo, incluindo aquecimento, com
`CLK_TCK=100` confirmado nas três VMs; 100% representa um núcleo lógico.
MySQL ficou entre 11,23% e 11,38%, e o gerador entre 76,02% e 77,17%. Esses
valores não medem saturação do host inteiro nem determinam o teto de capacidade.
Os picos de RSS são amostrados a cada aproximadamente cinco segundos, não o
máximo instantâneo do processo. As janelas de vinte minutos não substituem um
teste de vazamento de memória por seis horas.

O atraso estimado combina diferença entre crédito aceito/persistido e defasagem
do observador, com flush original de três segundos. Não é cardinalidade real
das filas nem latência por request. Nenhuma amostra ultrapassou 80.000 passos;
o último valor foi **zero nas três repetições**. Drenagem completa e replay
contábil confirmam o estado final, além do indicador amostrado.

Houve no mínimo 23,54 GiB livres no SSD de dados, 30,58 GiB no thin pool e
260,39 GiB no arquivo ZFS. O maior estoque amostrado de binlogs fechados foi
1.074.491.752 bytes, com idade máxima do estado do arquivador de 51,12 s;
recuperou e não acionou as proteções. Não houve esgotamento de recursos neste
perfil. Isso não demonstra ausência de limitação de I/O em outras cargas.

Os seis segmentos de amostras somam **626.987.528 bytes compactados** (cerca
de 598 MiB), mantidos no ZFS. SHA-256, CRC e cardinalidade passaram para os
28.800.000 registros. Os três snapshots contábeis de 10.000 linhas também
tiveram seus hashes reconferidos no host; os conteúdos finais são iguais,
como esperado para fixtures e contadores idênticos. Nenhum dump foi exportado.

Evidências públicas por execução:
[r1](../lab/dualstack/results/soak/rust-original-formal-r1-v1/supervisor/status.json),
[r2](../lab/dualstack/results/soak/rust-original-formal-r2-v1/supervisor/status.json),
[r3](../lab/dualstack/results/soak/rust-original-formal-r3-v1/supervisor/status.json).
[Análise consolidada](../lab/dualstack/results/soak/rust-original-formal-v1/analysis.json)
e [manifesto dos 48 arquivos coletados](../lab/dualstack/results/soak/rust-original-formal-v1/evidence-manifest.json).
Os resumos `r1-summary.json`, `r2-summary.json` e `r3-summary.json` foram gerados
com `summarize-soak.py`, excluindo o aquecimento das métricas apresentadas.

O baseline Rust original está pronto para o par equivalente com o candidato.
**Comparação original/candidato e PHP continuam pendentes.** Nenhum novo ensaio
foi iniciado por este acompanhamento.

## Proveniência e limites

Os 62 arquivos rastreados foram comparados por hash de blob com a tag. Há CRLF
na cópia proveniente do Windows; normalizando somente CRLF → LF, todos conferem.
Lockfiles mantêm as versões travadas. Binário original SHA-256:
`648e22b58f40b91f1760cab415fdf66c830161646aa4fbfe1056268102ee364d`.

Build release com Rust 1.99.0 e imagem
`rust:1-bookworm@sha256:114c7a4425406451c2866b6aafe69fe29b1b298832db1277d411ac73c82d04d6`.
O flush legado efetivo continua em **3.000 ms**; não foi usado o controle de
100 ms. Proveniência de cada repetição inclui somente uma lista permitida de
configurações públicas, compilador, imagem e hash do binário.

Usa o schema aditivo do laboratório, não uma instalação com schema original
intacto. O original não atualiza `peer_ips`, versões ou lease. O auditor verifica
os endereços de `peers`; `peer_ips` contém apenas uma fixture estática de
compatibilidade. Backlog original é estimado pelo crédito aceito menos o
persistido, dividido pelo incremento de 100 bytes. Inclui atraso de até cinco
segundos do observador e não equivale ao tamanho interno das filas.

## Calibração e preparação

A primeira calibração recebeu **720.000 requests sem erro de resposta**, mas
falhou no auditor por exigir IPv4 em quatro bytes no banco. O original ouvindo
em `::` grava os 8.000 seeders atualizados como IPv4 mapeado em 16 bytes; os
2.000 leechers residentes continuaram com a representação inicial de quatro
bytes. Exemplo: `::ffff:172.29.92.100`, mesma porta e mesmo endereço IPv4.
O supervisor drenou e encerrou normalmente. Evidências preservadas em
`lab/dualstack/results/soak/rust-original-calibration-v1/`.

O auditor foi corrigido para comparar o endereço canônico **apenas no original**.
Um teste exige que a mesma representação mapeada continue sendo recusada como
projeção do candidato e que IPv6 nativo não seja confundido com IPv4. O produto
original não foi modificado. Isso é uma correção da expectativa do laboratório,
não evidência de perda contábil ou de capacidade do tracker.

A segunda calibração foi aprovada: **720.000 requests, zero erros, 72.000.000
bytes** em referências/históricos/saldos, zero divergências nas 10.000 identidades
e drenagem do tracker concluída. A medição de 60 s recebeu 480.000 requests,
sustentando 7.999,967 req/s; resposta p95 **0,195441 ms**, p99 **0,304558 ms**.
Incluindo fila e validação do gerador, p99 foi **2,935601 ms**: não confundir
as métricas. [Resumo público](../lab/dualstack/results/soak/rust-original-calibration-v2-summary.json).

SHA-256, CRC e cardinalidade dos dois segmentos passaram. O replay das 720.000
amostras aceitas reproduziu os contadores de cada peer e conferiu o MySQL antes
do reset. [Auditoria das amostras](../lab/dualstack/results/soak/rust-original-calibration-v2/clients/sample-accounting-audit.json).
Essa aprovação curta libera a série formal, não encerra o veredito comparativo.

Seis testes do coletor/guardas e quatro do auditor passaram na VM Linux. A
execução local Windows do teste de durabilidade do coletor falhou porque usa
`os.O_DIRECTORY`, disponível no alvo Linux. Não alterar a garantia de fsync do
laboratório para fazer esse teste passar num ambiente diferente.
Log: [testes do harness](../lab/dualstack/results/soak/rust-original-harness-tests.txt).

## Preservação e acompanhamento

Antes do primeiro reset, foi criada a cópia local ao MySQL
`unit3d_dualstack_soak_v3_evidence`: 10.000 peers, 20.000 endpoints,
171.427.237 versões e 8.500.225.800 bytes em peers/históricos/usuários.
Agregados da origem permaneceram iguais e as cinco tabelas críticas conferem
em cardinalidade. Fixture privada guardada em `evidence-soak-v3` na VM de
clientes. v1/v2 anteriores, banco v2 e container v2 permanecem preservados.

O supervisor de cada repetição roda no Proxmox, verifica espaço SSD/ZFS/thin
pool, memória, arquivo de binlogs, processo e progresso. A série só avança após
sucesso, drenagem e verificação SHA-256/CRC/cardinalidade das amostras anteriores.
Não reinicia execuções falhas. O original não tem lease; essa única verificação
é inaplicável, sem dispensar as demais proteções.

Amostras compactadas e snapshots contábeis por identidade ficam no ZFS;
JSONs públicos são coletados no repositório. Sem exportação de binlogs,
credenciais, passkeys ou fixtures privadas. Logs do container limitados a 2×10 MB.
O estado consolidado fica em `lab/dualstack/checkpoint-rust-original.json`.

As correções independentes da feature estão documentadas separadamente em
[Problemas preexistentes](dualstack-problemas-preexistentes.md), com evidências
e limites de atribuição, inclusive a distinção da falha de lease introduzida.
