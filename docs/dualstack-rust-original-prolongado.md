# Ensaio de seis horas do Rust original

Execução autorizada em 09/10/2026: `rust-original-six-hours-v1`.
**Concluído e aprovado neste perfil de sustentação do original.** A carga começou
em **09/10 às 20:27:07, Brasília**, a última janela terminou em **10/10 às
02:32:51** e o supervisor concluiu a drenagem às **02:33:21**. As 72 janelas
medidas, além do aquecimento, passaram sem erros. Integridade e replay completo
contra MySQL foram confirmados antes de qualquer reset do banco.
O acompanhamento `acompanhar-baseline-rust-original` foi desativado após a
conclusão. A comparação formal com o candidato e a validação PHP continuam pendentes.

## Perfil

- UNIT3D-Announce 0.3.1 original, commit
  `fcd189e9aebf07a12a1f8cc39500819c3870925b`.
- Mesmo binário do baseline formal, SHA-256
  `648e22b58f40b91f1760cab415fdf66c830161646aa4fbfe1056268102ee364d`.
- 300 s de aquecimento e **21.600 s de medição**, em 72 janelas de 300 s.
- 8.000 req/s; 10.000 peers, 40 torrents de 250, 250 usuários e 80% seeders.
- IPv4 real, HTTP direto com keep-alive, `numwant=10`, conectividade e logs de
  announces desativados. Schema aditivo do laboratório, como no baseline formal.
- Seeders acrescentam 100 bytes por request. Os 2.000 leechers renovam IPv4
  antes de cada janela, sem evento, com `left=16 MiB`, `numwant=0` e zero tráfego.
  Isso mantém o swarm sem alterar o TTL original. Não há rotação ou expiração
  provocada neste perfil. As renovações entram na auditoria e ficam separadas
  da taxa/latência medida.
- Configurações originais preservadas: flush 3.000 ms, TTL ativo 7.200 s,
  retenção inativa 1.814.400 s, rotina de expiração a cada 1.800 s.

Esperado: 172.800.000 announces medidos, 2.400.000 no aquecimento e 146.000
renovações; **175.346.000 aceitos** no total. Crédito lógico esperado de
**17.520.000.000 bytes** em peers, histórico e usuários. São seis horas e cinco
minutos oferecendo carga, mais pausas curtas entre janelas para renovação,
fechamento das amostras e conexões. Não é um fluxo ininterrupto de seis horas.

## Preparação e critérios

As três VMs passaram no preflight, com aproximadamente 260,4 GiB livres no
arquivo ZFS, 23,9 GiB no SSD de dados, 6,0 GiB nos clientes e 4,1 GiB no tracker.
O thin pool tinha aproximadamente 30,9 GiB livres. O crescimento observado no
arquivo durante os três baselines curtos corresponde, por extrapolação linear,
a 3,5–5,7 GiB para 21.900 s. Isso é estimativa daquele perfil, não reserva nem
garantia; a autorização depende também das proteções contínuas do supervisor.

Sete testes do executor e seis do coletor/proteções passaram no Linux. A
calibração `rust-original-soak-rehearsal-v2` aplica o perfil prolongado durante
cinco minutos (60 + 240 s, cinco janelas de 60 s). O início longo exige sucesso,
drenagem, integridade SHA-256/CRC/cardinalidade e replay por identidade no MySQL.

A tentativa curta v1 foi interrompida por `single_family_payload`, com drenagem
aprovada e evidências preservadas. As 2.000 renovações passaram, mas o primeiro
seeder recebeu uma lista que o auditor rejeitou. Na tag original,
`src/announce.rs:506` mantém o `client_ip` recebido; `:680–688` serializa o tipo
IPv6 em `peers6`. O socket `::` representa conexões IPv4 como `::ffff:a.b.c.d`.
Após a renovação, os leechers antes carregados da fixture como IPv4 passam a
ser anunciados nessa representação de 18 bytes. Isso já era possível no código
original; o teste curto anterior não renovava os leechers residentes.

O auditor agora aceita **somente no original** a representação IPv4 mapeada
em `peers6`, verificando cada IP/porta contra a mesma lista IPv4 permitida. IPv6
nativo, endpoints desconhecidos, duplicados e respostas acima de `numwant`
continuam recusados; no candidato, mapeados em `peers6` continuam recusados.
A v2 registra quantas respostas contêm mapeados. O binário, listener e TTL
permanecem intactos. Não inferir desta calibração compatibilidade de transferência
com clientes reais ou suporte dualstack no original.

Consequentemente, o payload da lista do original renovado pode chegar a
18 × `numwant` bytes, enquanto os baselines curtos tinham 6 × `numwant`.
Essa diferença deve aparecer na análise; não apresentar estes ensaios como
comparação com o mesmo payload. A falha da v1 foi da expectativa do auditor,
não evidência de timeout de banco. Nenhum resultado da v1 foi aprovado.

## Calibração aprovada

A v2 concluiu cinco minutos de carga, com **2.410.000 requests aceitos e zero
erros**: 2.400.000 principais e 10.000 renovações. O replay dos cinco segmentos
conferiu as 10.000 identidades e 250 usuários com **240.000.000 bytes**, zero
divergências, SHA-256/CRC/cardinalidade aprovados e `tracker_drain=passed`.
As 2.400.000 respostas principais continham IPv4 mapeado em `peers6`, confirmando
o comportamento que motivou a correção do auditor. Fonte e hash do produto
original conferiram novamente; não foram aplicadas correções ao binário.

Nas quatro janelas medidas: throughput mínimo 7.998,33 req/s e mediana
7.999,65 req/s; medianas dos p95/p99 de resposta 0,2621/0,3897 ms. Drenagem
contábil de 5,73 s; maior atraso estimado amostrado de 69.415 passos de crédito.
Os observadores não registraram falha. Não comparar esses percentis diretamente
com o baseline curto anterior, que devolvia listas de tamanho diferente.

[Resumo](../lab/dualstack/results/soak/rust-original-six-hours-preparation-v1/rehearsal-summary.json),
[integridade](../lab/dualstack/results/soak/rust-original-six-hours-preparation-v1/rehearsal-integrity.json),
[replay contábil](../lab/dualstack/results/soak/rust-original-soak-rehearsal-v2/clients/sample-accounting-audit.json)
e [início do prolongado](../lab/dualstack/results/soak/rust-original-six-hours-preparation-v1/start-status.json).

O supervisor mantém os limites existentes: no mínimo 8 GiB no SSD de dados e
thin pool, 20 GiB no arquivo, 512 MiB de memória disponível; arquivo sem estoque
excessivo e com progresso, tracker vivo, zero erros e atraso de persistência
sem ultrapassar 80.000 passos por 30 s. O atraso é estimado pelo crédito de
100 bytes e inclui defasagem do observador; não é tamanho real das filas. O
original não tem lease nem `state_version`, e o auditor não exige esses campos.

## Resultado final

| Verificação | Resultado |
|---|---|
| Medição | 21.600 s em 72 janelas de 300 s; 172.800.000 requests principais |
| Aquecimento | 300 s; 2.400.000 requests principais |
| Renovações sem crédito | 146.000 |
| Aceitos / erros | **175.346.000 / 0** |
| Crédito | **17.520.000.000 bytes**, exatos por identidade e usuário |
| Replay contra MySQL | 10.000 peers, 250 usuários, zero divergências |
| Swarm final | 40 torrents; 8.000 seeders, 2.000 leechers; todos ativos |
| Contadores de conclusão / BON | Preservados em zero neste perfil |
| Integridade do arquivo | 73 segmentos; SHA-256, CRC gzip e 175.346.000 registros conferidos |
| Throughput por janela medida | Mínimo **7.999,93 req/s**; mediana **7.999,99 req/s** |
| Drenagem contábil | **3,92 s**; encerramento do tracker aprovado |
| Atraso estimado por crédito | Máximo 77.869 passos de 100 bytes; mediana 37.897; final **zero** |

O atraso inclui defasagem entre observadores e não representa o tamanho real
das filas internas. Nenhuma amostra ultrapassou 80.000 passos. Nenhum observador
registrou falha, e não houve reinício do MySQL. O executor também conferiu que
os contadores de erros de banco e jobs falhos não aumentaram durante a carga.

Cada endpoint legado teve IP e porta conferidos contra a identidade esperada,
normalizando IPv4 mapeado para comparação. Todas as 175.200.000 respostas
principais publicaram dez IPv4 mapeados em `peers6`: **180 bytes de lista**,
fora o envelope bencode. As renovações devolveram listas vazias. `peer_ips`
permanece uma fixture estática de compatibilidade com 10.000 linhas; sua presença
não comprova manutenção de endpoints dualstack pelo original. Expiração,
restauração, rotação e falhas injetadas não foram exercitadas neste perfil.

### Latência e recursos ao longo das seis horas

Os números de p95/p99 abaixo são **medianas dos percentis de 12 janelas por
hora de carga medida**, não percentis globais. As pausas entre janelas estão
incluídas nos intervalos usados para resumir recursos. CPU representa consumo
do processo, com 100% equivalente a um núcleo; `CLK_TCK=100` foi conferido nas
três VMs. Não é utilização total da VM ou do host.

| Hora | p95 resposta (ms) | p99 resposta (ms) | p99 fila do gerador (ms) | CPU Rust | CPU MySQL | CPU gerador |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 0,249 | 0,375 | 4,27 | 31,8% | 11,4% | 85,4% |
| 2 | 0,252 | 0,380 | 3,98 | 31,9% | 11,5% | 85,4% |
| 3 | 0,291 | 0,419 | 5,76 | 34,1% | 12,6% | 88,9% |
| 4 | 0,377 | 0,508 | 10,77 | 36,5% | 13,7% | 92,6% |
| 5 | 0,372 | 0,500 | 10,06 | 36,4% | 13,7% | 92,6% |
| 6 | 0,365 | 0,495 | 9,56 | 35,7% | 13,4% | 91,6% |

Nas 72 janelas, as medianas de p95/p99 de resposta foram **0,352/0,475 ms**;
o maior p99 de uma janela foi **0,538 ms**. Incluindo espera no gerador e
validação, a mediana dos p99 de tempo total foi **10,015 ms**. Não confundir
esse tempo total com o tempo de resposta da API.

Houve aumento de latência: da primeira à última hora, aproximadamente **46% no
p95 e 32% no p99** resumidos dessa forma. O aumento coincidiu com mais CPU
no gerador e maior espera em sua fila, mas isso **não isola a causa** entre
gerador, execução compartilhada do host, rede ou Rust. O crédito continuou
drenando, sem acúmulo persistente; estas séries tampouco demonstram saturação
de IOPS. Este ensaio passa nos critérios de sustentação adotados, sem afirmar
latência constante, teto de capacidade ou aprovação do limite comparativo de
10%. Uma atribuição causal dessa variação exige ensaio controlado separado;
nenhum outro ensaio foi iniciado neste acompanhamento.

O Rust teve RSS mediano de **27,46 MiB**, máximo observado de **38,61 MiB** e
último valor de **31,01 MiB**. As medianas horárias ficaram entre 26,95 e
27,92 MiB, sem crescimento contínuo observado. PSS máximo: 38,80 MiB. O MySQL
manteve RSS de 1.601,38 MiB. O gerador ficou perto de 53,75 MiB nas amostras;
seu pico autorreportado ao fechar a auditoria foi 72,13 MiB, fora dos picos
capturados pela coleta periódica. Isso não indica crescimento do cache Rust.

O SSD de dados manteve pelo menos **23,54 GiB livres**, o thin pool **30,55 GiB**
e o arquivo **254,65 GiB**. A redução líquida de espaço livre no arquivo foi
6.106.644.480 bytes (5,69 GiB); é uma medida do filesystem compartilhado, não
uma soma exclusiva dos artefatos deste ensaio. As amostras compactadas somam
**3.899.339.938 bytes**. O maior estoque amostrado de binlogs fechados foi
1.075.038.784 bytes, com idade máxima do progresso do arquivador de 53,29 s,
dentro das proteções. Os binlogs e as amostras brutas permaneceram no ZFS.

### Evidências e reprodução da análise

- [Status final e drenagem](../lab/dualstack/results/soak/rust-original-six-hours-v1/supervisor/status.json).
- [Integridade dos segmentos](../lab/dualstack/results/soak/rust-original-six-hours-v1/sample-integrity.json).
- [Replay por identidade](../lab/dualstack/results/soak/rust-original-six-hours-v1/clients/sample-accounting-audit.json)
  e [hash do snapshot SQL](../lab/dualstack/results/soak/rust-original-six-hours-v1/clients/accounting-proof.json).
- [Resumo das séries](../lab/dualstack/results/soak/rust-original-six-hours-v1/summary.json)
  e [análise por hora](../lab/dualstack/results/soak/rust-original-six-hours-v1/analysis.json).
- [Proveniência do original](../lab/dualstack/results/soak/rust-original-six-hours-v1/tracker/provenance.json)
  e [manifesto público coletado](../lab/dualstack/results/soak/rust-original-six-hours-v1/evidence-manifest.json).

O hash do snapshot SQL foi reconferido diretamente no ZFS após o replay.
Para reproduzir a análise local, executar `summarize-soak.py` sobre a pasta
coletada e salvar sua saída em `summary.json`; depois executar
`analyze-original-soak.py` sobre a mesma pasta. O segundo script valida os
totais esperados e calcula as séries horárias a partir dos JSONs públicos.

## Procedimento de acompanhamento e encerramento

Status remoto:
`/storage_pool/unit3d-dualstack/supervisor/rust-original-six-hours-v1/status.json`.
Checkpoint local: `lab/dualstack/checkpoint-rust-original-soak.json`.
O supervisor roda no Proxmox e não depende da continuidade desta conversa.
Uma falha interrompe o ensaio e preserva evidências; não há reinício automático.

Executado após `passed` e `tracker_drain=passed`, no host:

```sh
python3 /root/unit3d-soak/verify-soak-samples.py rust-original-six-hours-v1
```

Executado na VM de clientes, **antes de qualquer reset do banco**:

```sh
sudo python3 /opt/unit3d-dualstack/lab/audit-rust-comparison-samples.py rust-original-six-hours-v1
```

O replay distingue announces de seeders e renovações sem tráfego (evento 3
na amostra); o crédito depende de `main_accepted`, não de todos os requests.
Conferir `sample-accounting-audit.json` e `accounting-proof.json`, coletar com
`collect-soak.ps1` e analisar com `summarize-soak.py`. O resumo exclui aquecimento;
suas medianas de percentis por janela não são percentis globais. Verificar cada
janela, recursos, arquivo, memória, crédito e drenagem final. Amostras grandes
e snapshots permanecem no ZFS; somente evidências públicas leves são exportadas.

Os dados e fixtures privados dos baselines curtos permanecem no arquivo; os
bancos de evidência v2/v3 e o container de falha v2 devem ser preservados.
O banco de trabalho é exclusivo do laboratório. Nenhuma produção é acessada.

Esta execução acrescenta evidência de sustentação do original. Não aprova PHP
nem a comparação original/candidato: a v3 dualstack tem outro perfil, com dois
endpoints, rotação e expiração. O candidato ainda precisa repetir o perfil
formal equivalente para avaliar os limites de regressão.
