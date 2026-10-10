# Densidade de peers por torrent — Rust

Medição informativa solicitada em 2026-10-08. O operador considera **250 peers
no mesmo torrent um pior caso operacional**, com média muito inferior. Densidades
maiores neste relatório exploram o comportamento do sistema; não acrescentam
requisitos de aceitação nem justificam, por si, alterações no produto.

## Escopo e método

Somente o candidato Rust `a9ab263de2fe6473c86eeabfd0b6ca1c019f6070`. O PHP permanece
em `6d8e7437daa652fb02519584c456b15dceacffa4`, sem servir announces. Este ensaio
compara o candidato consigo mesmo sob diferentes densidades. A comparação
candidato/original anterior permanece em [benchmarks](dualstack-benchmarks.md).

- Três VMs dedicadas, cada uma com 4 vCPU e 8 GiB. MySQL 8.0.46, Redis 7.2.16,
  Rust 1.99.0; buffer pool de 128 MiB, flush de commit e sync binlog em 1.
- Banco de teste `unit3d_dualstack_journal_test`; nenhuma produção ou base de
  baseline alterada. Estatísticas analisadas depois da fixture e antes do
  bootstrap. Isso não resolve a pendência anterior de robustez do bootstrap.
- 100% dos peers possuem IPv4 e IPv6, com origem real nas duas famílias. São
  80% seeders e 20% leechers residentes. Usuários reaparecem em vários torrents,
  cada qual com um peer lógico independente por torrent.
- Somente seeders enviam requests nesta carga; os leechers residentes alimentam
  as listas. Os endpoints são previamente conectáveis. Não há rotação, churn,
  expiração ou teste de conexão durante a medição.
- `numwant=10`: resposta com dez peers lógicos e vinte endpoints, 240 bytes de
  listas compactas. O envelope pode aumentar alguns bytes conforme os dígitos
  dos contadores. A população não aumenta a quantidade de peers retornada.
- Announces sintéticos frequentes, com evento `completed` e referência cumulativa
  compartilhada entre famílias. Este evento exercita o processamento sem o bloqueio
  de intervalo; não representa a cadência esperada de clientes privados. A matriz
  funcional com clientes reais foi executada separadamente.
- Taxa oferecida em malha aberta. Registrar respostas concluídas dentro da janela,
  espera no gerador, descartes e erros, além das latências. O p99 principal mede
  da execução do request ao recebimento completo do corpo, excluindo as asserções
  locais. Não é tempo interno do servidor: inclui rede e processamento do cliente.
- Conferência contábil entre fases: versão por request aceito, referência por
  peer, histórico e saldo agregado por usuário, sem duplicação por família.
  As varreduras SQL de conferência ocorrem fora das janelas medidas.
- Recursos coletados na VM do banco, container Rust e host. O host é compartilhado;
  a anomalia anterior dos contadores de tempo do NVMe continua sendo sinalizada,
  sem eliminar amostras ou interpretar médias inválidas como latência do SSD.

Os resultados agregados são **medianas dos percentis de cada repetição**. As
faixas indicam o menor e maior percentil entre repetições, não intervalos de
confiança. Janelas curtas detectam tendências, não homologam estabilidade por horas.

## Interpretação de degradação

Exibir diferenças relativas de 10%, 25% e 50% com seus valores absolutos. Para
delimitar uma faixa exploratória, “grande” significa p99 pelo menos **50% e
0,5 ms acima do controle de baixa densidade comparável**, ou erros, descartes
ou incapacidade de acompanhar a taxa oferecida. Esse critério descritivo foi
fixado antes da carga; não substitui o gate original de regressão de 10%.

Um limite depende da taxa de requests, mix, seleção, hardware e janela. A maior
população aprovada é um ponto medido; o primeiro ponto acima do critério delimita
uma faixa. Não é adequado interpolar um número exato ou chamá-lo de limite
universal de peers do tracker.

## Reprodução e dados

Plano: [densidade Rust](plans/2026-10-08-densidade-rust.md).
Harness: `lab/dualstack/{density-fixture.py,density-http.py,density_common.py}`.
Execução: `run-density-survey.ps1 -PlanFile <plano.json> -IdentityFile <chave>`.
A execução exige os scripts-base e aliases preparados no laboratório existente,
recusa containers ativos do tracker e reseta apenas o banco dedicado de testes.
O runner inicia, mede, drena e encerra o backend; a remoção dos aliases ocorre
ao encerrar o conjunto de séries.

Planos públicos em `lab/dualstack/density-plans/`. Relatórios, amostras numéricas
comprimidas e recursos em `lab/dualstack/results/density/`. Fixtures com passkeys
ficam somente no laboratório. `export-density-results.py` restringe a exportação
aos relatórios e amostras. `analyze-density.py <serie>` reproduz as agregações e
os deltas de I/O nas janelas medidas.
`audit-density.py <serie>` reconstrói os percentis pelas amostras, compara as
referências e saldos dos snapshots e gera hashes SHA-256 dos arquivos exportados.

## Curva inicial: efeito sobre o próprio torrent

Série `density-curve-v1`: 79.550 peers residentes em onze torrents, 40.000
usuários e 159.100 endpoints. Somente um torrent recebe **1.000 req/s** em cada
fase; os demais ficam residentes e ociosos. Três repetições, em ordens crescente,
decrescente e embaralhada determinística. Cada fase: 5 s de aquecimento e 15 s
medidos. 660.000 requests aceitos, sem erros, descartes ou divergências.

| Peers no torrent alvo | p99 mediano (ms) | Faixa entre repetições (ms) |
|---:|---:|---:|
| 50 | 0,2390 | 0,2316–0,2416 |
| 100 | 0,2421 | 0,2420–0,2425 |
| 150 | 0,2454 | 0,2394–0,2539 |
| **250** | **0,2483** | **0,2462–0,2514** |
| 500 | 0,2515 | 0,2473–0,2525 |
| 1.000 | 0,2555 | 0,2530–0,2659 |
| 2.500 | 0,2745 | 0,2728–0,2764 |
| 5.000 | 0,3155 | 0,3080–0,3172 |
| 10.000 | 0,4038 | 0,3911–0,4056 |
| 20.000 | 0,5836 | 0,5770–0,5837 |
| 40.000 | 1,1346 | 1,1066–1,1845 |

O crescimento é gradual. Frente ao controle de 50, 250 peers acrescentam
0,0093 ms ao p99 mediano (+3,9%). O primeiro ponto com aumento superior a 10%
consistente entre as três repetições é 2.500 peers (+14,9%; +0,0355 ms).
Frente à referência operacional de 250, esse ponto representa +10,6%.
Isso não significa custo rigorosamente zero abaixo de 2.500: diferenças menores
já aparecem, mas o efeito é pequeno e parte das faixas se sobrepõe.

A CPU mediana do container cresce de 6,56% no controle de 50 para 6,85% em
250, 25,11% em 20.000 e 47,76% em 40.000 (100% corresponde a um núcleo).
A VM do banco não apresentou esperas por espaço de redo ou buffer livre nas
janelas. A drenagem observada após os requests ficou abaixo de 0,40 s; sem
amostragem de versões durante a fase, isso não prova estabilidade sustentada
do backlog. Um dos 33 intervalos recebeu sinalização da anomalia de tempo de
escrita do host. Os valores brutos e o sinalizador permanecem no relatório.

O critério descritivo de degradação grande foi cruzado entre 20 mil e 40 mil
peers nesta varredura. O refinamento usa um controle próprio, no mesmo dataset
dos pontos intermediários, para não misturar o custo residente entre séries.

## Interferência: desenho dos controles

Série `density-interference-v1`: fixture constante de 118.450 peers, 10.000
usuários, 265 torrents e 236.900 endpoints. O torrent sentinela tem 50 peers e
recebe 200 req/s. Há pools separados de 128 torrents com 50 peers, 128 com 250
e oito com 10.000. A cada fase, somente os grupos declarados recebem requests.
O gerador intercala os torrents desde o primeiro ciclo e registra o total aceito
por torrent. Não percorre toda a população de um torrent antes de visitar outro.

| Comparação | Torrents de fundo ativos | Requests/s de fundo | Total, com sentinela |
|---|---|---|---|
| Total fixo, 250 peers/torrent | 1, 4, 16, 64, 128 | 800 divididos pelo grupo | 1.000 |
| Carga crescente, 250 peers/torrent | 1, 4, 16, 32 | 50 por torrent | 250–1.800 |
| Exploratória, 10.000 peers/torrent | 1, 2, 4, 8 | 200 por torrent | 400–1.800 |

Na comparação de total fixo, o controle tem 128 torrents de 50 peers e a mesma
taxa agregada. Nos dois blocos de carga crescente, cada ponto tem seu controle
com **a mesma quantidade de torrents ativos e a mesma taxa**, usando 50 peers
por torrent. Todos os pools continuam residentes. Assim, a mudança de tráfego
não é confundida automaticamente com efeito de densidade.

Duas passagens em ordens opostas; 5 s de aquecimento e 15 s medidos por fase.
Como há apenas 3.000 requests medidos por sentinela em cada fase, diferenças
pequenas de cauda precisam de cautela. A medição separada da espera no gerador
ajuda a identificar quando o emissor ou conexões compartilhadas acrescentam
atraso ao invés do processamento HTTP observado.

### Resultados de interferência

46 fases e **828.000 requests aceitos**, com zero erros, descartes, divergências
ou novos deadlocks/timeouts de lock. Todos os torrents selecionados receberam
requests, conforme os mapas `accepted_by_torrent`. As conclusões dentro de cada
janela/grupo ficaram em pelo menos 99,93% da taxa oferecida; todos os requests
foram concluídos e confirmados ao drenar. Diferenças de uma resposta nas bordas
da janela não são tratadas como perda de requests.

Carga total fixa de 1.000 req/s; controle da sentinela: p99 mediano **0,3056 ms**.

| Torrents de 250 peers ativos | p99 da sentinela (ms) | Diferença do controle |
|---:|---:|---:|
| 1 | 0,3028 | −0,9% |
| 4 | 0,2962 | −3,1% |
| 16 | 0,3028 | −0,9% |
| 64 | 0,3067 | +0,4% |
| 128 | 0,2982 | −2,4% |

Carga crescente de 50 req/s por torrent de fundo, mais 200 req/s da sentinela:

| Torrents de 250 peers | Taxa total (req/s) | p99 controle / candidato denso (ms) | Diferença |
|---:|---:|---:|---:|
| 1 | 250 | 0,3066 / 0,2929 | −4,5% |
| 4 | 400 | 0,3188 / 0,3246 | +1,8% |
| 16 | 1.000 | 0,2986 / 0,2941 | −1,5% |
| 32 | 1.800 | 0,3124 / 0,2976 | −4,7% |

Não apareceu aumento relevante atribuível aos torrents de 250 peers nesses
limites. As pequenas diferenças negativas não demonstram benefício de aumentar
a densidade. **Não foi encontrado um teto de quantidade de torrents de 250**;
128 com taxa total fixa e 32 com taxa crescente são os maiores pontos medidos.
Quantidades maiores ou taxas maiores não foram validadas por esta série.

Carga exploratória de 200 req/s por torrent de **10.000 peers**, mais a sentinela:

| Torrents de 10.000 peers | Taxa total (req/s) | p99 controle / denso (ms) | Aumento absoluto | Aumento relativo |
|---:|---:|---:|---:|---:|
| 1 | 400 | 0,2432 / 0,4579 | 0,2147 ms | +88,3% |
| 2 | 600 | 0,2440 / 0,4265 | 0,1825 ms | +74,8% |
| 4 | 1.000 | 0,2281 / 0,4289 | 0,2007 ms | +88,0% |
| 8 | 1.800 | 0,2432 / 0,5774 | 0,3342 ms | +137,4% |

Com 10.000 peers, **um único torrent de fundo já produz efeito mensurável**
na sentinela. Não há relação estritamente monotônica com a quantidade em todos
os pontos: taxas, agendamento e contenção também influenciam o resultado.
Nenhum ponto ultrapassa o critério composto de +50% **e** +0,5 ms para a
sentinela; isso não significa ausência de degradação relativa, mostrada na tabela.

No par de oito torrents extremos, CPU mediana do Rust: 10,12% no controle e
36,04% no denso. Escrita na VM do banco: 8,34 e 9,98 MiB/s; fila média 0,30 e
0,28; tempo médio de escrita 0,36 e 0,32 ms. Não houve esperas por espaço de
redo ou buffer livre nas 46 janelas. Esse conjunto sustenta efeito de processamento
na latência observada, sem estabelecer a capacidade máxima do SSD. Quatro
janelas têm sinalização da anomalia de contadores de tempo do host.

O gerador chegou a 25,96% de um núcleo na métrica agregada por fase, que inclui
a conferência SQL final; não é CPU restrita à janela medida. Drenagem máxima
observada: 0,44 s. Não houve varredura SQL periódica de versões durante a carga,
portanto não se deve inferir estabilidade do backlog por horas.

## Refinamento: faixa do limite em um único torrent

Série `density-refinement-v1`: 115.300 peers em seis torrents, 40.000 usuários
e 230.600 endpoints residentes. Um alvo a 1.000 req/s por fase. Três ordens,
5 s de aquecimento e **30 s medidos**; 18 fases e 630.000 requests aceitos.
Zero erros, descartes, divergências ou novos deadlocks/timeouts durante a carga.

| Peers no alvo | p99 mediano (ms) | Faixa entre repetições (ms) | Aumento sobre controle de 50 |
|---:|---:|---:|---:|
| 50 | 0,2348 | 0,2272–0,2421 | — |
| **250** | **0,2421** | **0,2394–0,2421** | **0,0072 ms / +3,1%** |
| 20.000 | 0,5835 | 0,5817–0,6182 | 0,3486 ms / +148,4% |
| 25.000 | 0,7255 | 0,7013–0,7279 | 0,4906 ms / +208,9% |
| 30.000 | 0,8468 | 0,8319–0,8576 | 0,6119 ms / +260,6% |
| 40.000 | 1,0859 | 1,0742–1,0862 | 0,8510 ms / +362,4% |

Pela mediana, **25.000 é o maior ponto medido abaixo do critério composto**,
e **30.000 é o primeiro acima** no refinamento. A margem de 25.000 para o corte
absoluto é apenas 0,0094 ms. Comparando a primeira repetição com seu próprio
controle, o aumento foi 0,5007 ms, ligeiramente acima do corte; nas demais,
ficou abaixo. Portanto 25.000 é uma **zona de transição**, não um teto seguro.
20.000 manteve margem maior para esse corte nas três repetições.

Isso não transforma aumentos de 148% ou 209% em ausência de degradação. A
classificação “grande” exige também +0,5 ms, conforme definido antes do ensaio.
Se o objetivo for conservar o p99 dentro de **10%**, a curva inicial aponta
1.000 como último ponto abaixo desse aumento na mediana e 2.500 como primeiro
consistentemente acima. São critérios diferentes, ambos expostos para a decisão
do operador. Não se pode extrapolar esses limites para outra taxa, resposta ou
composição de swarm.

O refinamento concluiu pelo menos 999,93 req/s em cada janela de 1.000 req/s.
Drenagem máxima observada: 0,91 s. Quatro janelas foram sinalizadas pelo contador
de tempo de escrita do host. Percentis não são máximos: os relatórios mantêm
também picos individuais e todas as amostras, sem descarte de outliers.

## Encerramento e alcance

Ao todo, incluindo os dois smokes: **101 fases, 2.139.000 requests aceitos e
1.671.000 amostras de requests agendados nas janelas medidas**. Auditoria local
recalculou os percentis e conferiu snapshots e hashes de todas as cinco séries.
O smoke de interleaving confirmou 2.800 requests por torrent de fundo em cada
fase, antes de iniciar a matriz de interferência.

O harness acrescentou a distribuição intercalada e os mapas por torrent após a
curva inicial. A ordem de um grupo com um único torrent permanece idêntica;
o refinamento foi executado com a versão final do gerador. O produto não mudou.

Estado final: 115.300 peers, 230.600 endpoints, 630.000 versões confirmadas e
31.500.000 bytes iguais nas referências, históricos e soma de saldos por usuário.
Nenhuma divergência por identidade, endpoint ou contagem de torrent; nenhum job
falho. Os contadores históricos de locks permanecem em 193/71, sem incremento
nas cargas. Lease inativa, zero consultas ativas no banco de testes, nenhum
container/listener do tracker, nenhum namespace e nenhum alias temporário.

Dados e limites indicam que **250 peers por torrent está muito abaixo da faixa
em que a densidade produziu aumento expressivo nestes ensaios**. Isso não aprova
a matriz formal de regressão contra a versão original, não mede capacidade
máxima em req/s, não cobre churn de seis horas e não resolve o bootstrap anterior.
Somente o laboratório e a documentação foram alterados; sem push ou produção.

Checkpoint: `lab/dualstack/checkpoint-density.json`. Evidências de encerramento:
`results/density/final-state.json` e `results/density/cleanup.txt`.

Revisão final única contra o plano: escopo restrito às medições e ao laboratório,
com controles, refinamento, conferência contábil, evidências e limpeza concluídos.
Os ajustes de interleaving e conferência por torrent foram validados antes da
interferência. O Git preserva os bytes das evidências, inclusive logs brutos,
para manter seus hashes independentemente da conversão de linhas no Windows.
Produtos e lockfiles permaneceram intactos; não houve ampliação para otimizações.
