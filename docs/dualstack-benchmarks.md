# Validação de performance

Execução autorizada em 8 de outubro de 2026, depois dos gates funcionais. A
calibração começa com 1.000 peers, IPv4, distribuídos entre 100 torrents, antes
da matriz de 54 mil/100 mil peers e do ensaio de seis horas. Resultados curtos
não constituem aprovação da matriz completa.

Estado atual: índice direto Rust `a9ab263` validado funcionalmente e aprovado
na calibração concentrada com 0% dualstack. O perfil de 50% continua reprovado
em latência. A investigação de I/O não mostrou saturação sustentada do SSD nessa
carga de 1.000 req/s; há amplificação de escrita e custo de seleção que cresce
com o torrent. Detalhes, medições e próximas opções na última seção.

## Primeiro perfil de calibração

- 800 seeders atualizam upload; 200 leechers residentes fornecem listas reais.
- Cada torrent distribuído tem oito seeders e dois leechers; no perfil popular,
  todos pertencem ao mesmo torrent. Um usuário e uma identidade por peer.
- `numwant=25`, checagem de conectividade desativada em ambos os comparados;
  origens reais por sockets IPv4/IPv6 em 72 pares de endereços privados.
- Evento `completed` repetido, com contador cumulativo compartilhado por família.
  Esse perfil mede atualização de seeders existentes, não conclusões repetidas
  nem uma simulação completa de downloads. Os leechers permanecem residentes.
- O PHP original impõe deduplicação de 30 segundos. O gerador recusa uma taxa
  que viole esse intervalo; não altera o código original para removê-lo.
  Em dualstack, as famílias anunciam em partes distintas do ciclo, com o mesmo
  contador. A janela mínima é verificada também entre ciclos.
- Carga aberta com filas limitadas: registra perdas do gerador, latência HTTP e
  tempo desde o instante programado, para mostrar eventual espera no gerador.
- SQL após drenagem compara a referência dos peers, histórico e usuários com
  os contadores reconhecidos; verifica jobs falhos e novos deadlocks/timeouts.
- Respostas do candidato devem preservar totais exatos e limite de payload.
  O baseline permanece sujeito à sua semântica original de resposta.

`benchmark-fixture.py` só prepara o banco descartável com proprietário parado
e sem peers anteriores. Credenciais e manifesto completo permanecem privados.
`benchmark-backend.sh` monta os fontes originais exportados das revisões fixadas
ou o candidato, conservando lockfiles, imagem PHP e compilação Rust release.
Tracing detalhado de transições fica desativado para a medição. A comparação
inicial usa schema aditivo nos dois lados; o código original ignora `peer_ips`.
Isso deverá ser identificado separadamente de uma instalação original com seu
schema sem expansão na homologação final.

`benchmark-http.py` produz JSON resumido e amostras individuais compactadas em
`/opt/unit3d-dualstack/benchmarks/` na VM clientes. `benchmark-monitor.py` coleta
recursos do tracker, sem ler logs ou configurações privadas dos containers.
Os arquivos brutos permanecem disponíveis para comparar repetições. Não exportar
`benchmark-fixture.json`, `benchmark-key.json`, `.env` ou configurações de acesso.

## Critérios e sequência

1. Calibrar preparo, origens, respostas, contabilização e drenagem com ensaios curtos.
2. Investigar qualquer divergência antes de aumentar duração ou população.
3. Medir original/candidato com três repetições de 300 s de aquecimento e 900 s
   de medição, mesmos recursos e configurações dentro de cada par.
4. Cobrir populações 1.000/54.000/100.000, 0/50/100% dualstack, distribuição e
   concentração, volume fixo de requests e população fixa anunciando pelas famílias.
5. Completar capacidade sustentada, memória, backlog, churn de seis horas e
   janela de perda assíncrona após encerramento abrupto.

Limites aprovados: p95 e p99 até 10% acima do baseline, throughput pelo menos
95%, sem novos erros ou divergência financeira. Uma taxa oferecida baixa com
100% de respostas não estabelece a capacidade máxima do servidor. O payload
é medido em bytes e segue seu limite próprio, sem tolerância genérica de 10%.

## Primeira calibração distribuída e limites encontrados

1.000 peers, 100 torrents, 0% dualstack, 30 s de aquecimento e 60 s medidos:

| Backend | Versão | Taxa efetiva | p95 | p99 | Crédito final |
|---|---|---:|---:|---:|---|
| PHP | 9.2.0 original | 20 req/s | 19,096 ms | 20,635 ms | Divergente; falha legada reproduzida |
| PHP | Original + consumidores corrigidos | 20 req/s | 19,081 ms | 21,004 ms | 180.000 bytes, correto |
| PHP | Candidato dualstack | 20 req/s | 20,880 ms | 22,585 ms | 180.000 bytes, correto em 1.000 identidades |
| Rust | Original, preparo de listas incorreto | 1.000 req/s | 0,222 ms | 0,253 ms | 9.000.000 bytes, correto; performance descartada |
| Rust | Candidato, preparo de listas incorreto | 1.000 req/s | 0,231 ms | 0,264 ms | 9.000.000 bytes, correto; performance descartada |

Cada PHP recebeu 1.800 requests, incluindo aquecimento; cada Rust, 90.000.
Nenhum erro HTTP ou perda de oferta pelo gerador nessas rodadas. O PHP ficou
dentro de 10% em p95/p99 neste perfil curto. Isso não substitui as três repetições
longas da aceitação. Os primeiros resultados Rust não aprovam performance:
a inspeção do payload detectou que as listas eram suprimidas durante a carga.

No PHP original, `LTRIM` removia o tamanho máximo do lote (4.062), inclusive
itens recebidos após `LRANGE`. A reprodução controlada falhou nos dois
consumidores originais. A correção PHP `6d8e7437daa652fb02519584c456b15dceacffa4`
remove somente os itens lidos e passou com MySQL/Redis reais e sob a mesma carga.
O controle `legacy-fixed` monta a tag original com esses dois consumidores
substituídos; não é apresentado como a tag intacta. A rodada original com perda
permanece disponível, e seu custo não prova a entrega correta de todos os efeitos.

Resultados no diretório `lab/dualstack/results/benchmarks/`:

- `php-original-20261008T151056`: inválido para comparação, backend não iniciou.
- `php-original-20261008T151512`: calibração HTTP válida, contabilidade falhou.
- `php-legacy-fixed-20261008T152541`: controle corrigido aprovado; inspeção
  adicional por usuário confirmou zero divergências.
- `php-candidate-20261008T152922`: candidato aprovado no perfil curto.
- `rust-original-20261008T153254`: contabilidade passou; performance descartada pelo preparo de listas.
- `rust-candidate-20261008T153530`: contabilidade passou; performance descartada pelo preparo de listas.
- `rust-original-20261008T153910`: concentração em um torrent; mesmo limite de preparo, performance descartada.

As diferenças de lockfile foram investigadas: Composer só difere em fins de
linha; no Rust, `serde_json` tornou-se dependência direta na mesma versão já
travada transitivamente. Nenhuma versão/checksum de biblioteca mudou.

O preparo Rust preservava espaços ao redor dos nomes de variáveis do `.env`.
Ao acrescentar a configuração de rate limit sem espaços, escrevia a variável
duas vezes. O leitor usava a primeira, mantendo o limite original de entrega
de listas. Depois de esgotá-lo, responses de seeders tinham listas vazias,
embora anunciassem `numwant=25`. A correção normaliza os nomes antes das
substituições. O gerador agora exige a quantidade esperada de endpoints IPv4,
e IPv6 quando a população é inteiramente dualstack, além de recusar warnings.
As rodadas desse perfil foram repetidas abaixo; a matriz de clientes reais permanece
válida porque já exigia os endpoints nas capturas e nunca esgotou esse limite.

## Calibração corrigida e regressão em torrent concentrado

Rust, 1.000 peers, 0% dualstack, 1.000 req/s, 30 s de aquecimento e 60 s medidos.
Cada rodada recebeu 90.000 requests, contabilizou 9.000.000 bytes e verificou
as 1.000 identidades sem divergência. O throughput é de requests aceitos nessa
taxa oferecida; ainda não foi medida a capacidade máxima.

| Distribuição | Código | p95 (ms) | p99 (ms) | Lista por resposta |
|---|---|---:|---:|---|
| 100 torrents | Original | 0,220004 | 0,248117 | 2 peers IPv4 |
| 100 torrents | Candidato `859aa88` | 0,227338 | 0,258466 | 2 peers IPv4 |
| Um torrent | Original | 0,240633 | 0,274807 | 25 peers IPv4 |
| Um torrent | Candidato `859aa88` | 0,364426 | 0,413999 | 25 peers IPv4 |
| Um torrent | Candidato `4cb05fc` | 0,306872 | 0,344189 | 25 peers IPv4 |

Distribuído: +3,33%/+4,17%, aprovado somente no perfil curto. Concentrado:
+51,44%/+50,65% antes da correção, +27,53%/+25,25% depois. **O gate de 10%
continua reprovado.** As populações maiores e os ensaios prolongados não foram
iniciados após essa reprovação.

Rodadas correspondentes, na ordem da tabela:
`rust-original-20261008T154501`, `rust-candidate-20261008T155221`,
`rust-original-20261008T155458`, `rust-candidate-20261008T155719`,
`rust-candidate-20261008T160804`.

O profiler de CPU confirmou trabalho relevante na seleção: 20,92% das amostras
no iterador de seleção, 5,36% em `Peer::counts`, 1,92% no iterador do índice.
Código confirmado: `src/dualstack/response.rs` fazia uma passagem para contar
e outra para selecionar, consultando o mapa global de peers nas duas.
`rust-candidate-20261008T160106` é diagnóstico com profiler, sem valor de gate
de latência; suas verificações financeiras passaram.

O commit `4cb05fc` unificou essas passagens. Usa reservas limitadas a `numwant`
por tipo, preserva seleção uniforme, prioridade de seeders, TTL, conectividade,
exclusão do próprio usuário e os dois endpoints de cada peer. Não altera schema,
crédito, journal, persistência ou propriedade. A suíte `dualstack_mysql` completa
passou em 31,03 s, incluindo novo caso com duas sementes, três leechers e três
vagas, repetido 64 vezes. O código de resposta continua sem SQL síncrono.

Revisão final única desse incremento contra o plano: sem divergência funcional
identificada; a redução de custo foi medida, mas não satisfaz o gate restante.
O checkpoint preserva a melhoria sem declarar a homologação concluída.

## Custo restante e decisão de maior impacto

O código atual ainda percorre todos os peers do torrent em cada resposta,
inclusive `numwant=0`, para calcular totais com validade temporal exata.
Cada identidade é resolvida no `BTreeMap` global. A tag original lê totais
mantidos em memória e percorre seus peers apenas quando solicita listas.
O controle sem listas, repetido sem profiler, confirmou: original p95/p99
0,222009/0,250463 ms; candidato 0,276582/0,310636 ms (+24,58%/+24,02%).
Rodadas `rust-original-20261008T161402` e `rust-candidate-20261008T161624`.
Ambas passaram contabilidade por identidade e 90.000 requests sem erros.
Uma rodada diagnóstica anterior, `rust-candidate-20261008T161125`, usou profiler
e permanece separada das comparações. Isso demonstra que retirar a lista não
elimina o custo adicional; não atribui todo o tempo restante a uma única função.

Uma alternativa recomendada para investigação é um índice por torrent com
acesso direto aos estados dos peers, evitando a busca repetida no mapa global.
Isso preservaria o cálculo com TTL vigente e permitiria medir o ganho antes
de introduzir cache de contadores. **O ganho dessa alternativa ainda não foi
medido; não há promessa de que, sozinha, alcance 10%.**

Impactos confirmados pela leitura dos consumidores:

- `coordinator.rs`: atualização atômica de estado e índice na mesma seção crítica.
- `persistence.rs`: reconstrução do índice no bootstrap, depois dos endpoints.
- `response.rs`: leitura direta do índice por torrent, mantendo limite por peer.
- `admin.rs`: snapshots por torrent e contagem por usuário; a consulta atual por
  usuário usa `BTreeMap::range`, portanto não pode ser perdida numa troca simples
  por mapa hash.
- `retention.rs` e `deletion.rs`: remoção consistente das referências do índice,
  respeitando a drenagem e as barreiras atuais.

Uma alternativa mais complexa é manter contadores por torrent e um índice de
expiração. Exige atualizar todos esses caminhos para evitar contagem obsoleta,
desconto duplo e crescimento ilimitado durante rotação de IP. Não foi aplicada.

Antes de aceitar qualquer alteração estrutural: executar contratos MySQL,
expiração sem limpeza física, exclusões/retenção, administração, concorrência,
limite de memória durante substituições e repetir a concentração de 1.000 peers.
Somente depois de passar retomar os demais perfis e durações.

Manter o código atual e ampliar a tolerância seria uma mudança explícita do
critério de aceitação. Não foi feita. Nem a taxa de 1.000 req/s, nem os tempos
absolutos inferiores a 1 ms dispensam a regressão percentual acordada.

## Estado de encerramento desta rodada

Tracker e geradores encerrados, lease liberada e aliases temporários removidos.
Estado final conferido: 1.000 peers, 90.000 versões, 9.000.000 bytes nas
referências/históricos/usuários, nenhum job falho ou divergência financeira.
Os totais globais de deadlocks/timeouts também incluem os conflitos provocados
intencionalmente pela suíte de regressão; os snapshots de cada carga confirmam
que ela não acrescentou novos conflitos.

As amostras gzip contêm latência HTTP, atraso desde o agendamento e payload.
`comparison-*.json` registra os gates; `calibration-validity.json` identifica
as rodadas descartadas. Um resultado bruto com `status=passed` aprova suas
asserções funcionais, não aprova automaticamente o limite comparativo de 10%.
Inventários de imagens, kernel, CPU e memória estão nos arquivos `environment-*`.
O hash de fonte do inventário tracker foi capturado durante a investigação,
depois da edição local; os commits por rodada são os declarados neste relatório.

Revisão final única do harness contra o plano: origens reais, carga limitada,
fixtures determinísticas, contabilização por identidade, listas verificadas,
amostras brutas e critérios explícitos. Limites ainda abertos: a fixture contém
leechers residentes, portanto não implementa churn de seis horas; falta medir
capacidade máxima, perfis mistos e schema original sem expansão. Nenhuma dessas
etapas foi marcada como concluída.

## Índice direto por torrent e investigação de I/O

O usuário autorizou a otimização estrutural proposta e acrescentou a verificação
do SSD compartilhado. Implementação Rust `a9ab263`: um único estado por peer em
`IndexMap` por torrent e um índice ordenado de identidades para consultas por
usuário e manutenção. A resposta percorre diretamente os estados do torrent,
preservando TTL, amostragem, dois endpoints e totais lógicos. Bootstrap, remoção
e retenção usam a mesma estrutura. Não há cache de contadores, novo SQL no
announce, mudança no journal ou relaxamento de durabilidade.

Validações após a mudança:

- Dois testes de índice: 4.000 operações intercaladas comparadas com um mapa de
  referência e 10.000 substituições sem acumular identidades/estados.
- Contrato MySQL completo aprovado: crédito, concorrência, rollback, reentrega,
  bootstrap, TTL, retenção, administração, leases e deadlocks reais.
- Exclusões Rust aprovadas, incluindo crédito pendente, restart, cancelamento,
  outros recursos preservados e lotes de 200 sob contenção.
- Cinco testes de contrato compartilhado e 19 de protocolo/rede aprovados.
- Runner de remoção PHP: 57 testes e 746 asserções aprovados.

Revisão final única do produto contra o incremento aprovado: nenhuma divergência
funcional identificada. A ordem user/torrent/peer da manutenção foi preservada;
remoção física retira ambas as referências do índice. A alteração de ordem interna
do torrent não muda a amostragem uniforme dos peers elegíveis.

### Repetição controlada de 1.000 peers concentrados

Mesma carga de 1.000 req/s, 0% dualstack, 30 s de aquecimento e 60 s medidos,
com observadores de I/O equivalentes. Sem profiler de CPU nesta comparação.

| Código | Rodada | p95 (ms) | p99 (ms) |
|---|---|---:|---:|
| Candidato anterior `4cb05fc` | `rust-candidate-20261008T182353` | 0,301729 | 0,336214 |
| Índice direto `a9ab263` | `rust-candidate-20261008T183303` | 0,257212 | 0,289764 |
| Original repetido | `rust-original-20261008T183529` | 0,242375 | 0,281989 |

Ganho do índice sobre o candidato anterior: 14,75% no p95 e 13,82% no p99.
Diferença para o original repetido: +6,12%/+2,76%, **gate curto aprovado**.
Todas as rodadas aceitaram 90.000 requests, verificaram 1.000 identidades e
9.000.000 bytes sem divergências, erros ou descarte no gerador. Drenagem do
candidato: aproximadamente 1,01 s. Não é medição de capacidade máxima, nem
substitui as três repetições longas da homologação.

### O que o disco mostrou nessa carga

O disco da VM dados 121 está em `local-lvm`/`pve`, sobre `/dev/nvme0n1p3`:
KINGSTON SNVS250G de 232,9 GiB. MySQL: buffer pool de 128 MiB,
`innodb_flush_log_at_trx_commit=1`, `sync_binlog=1`, método `fsync`,
`innodb_io_capacity=200` e máximo 2.000. Nenhum parâmetro foi alterado.

Os números abaixo são deltas na janela medida, não médias desde o boot.

| Métrica | Original | Candidato anterior | Índice direto |
|---|---:|---:|---:|
| Escritas/s no disco virtual da VM dados | 130,5 | 475,7 | 467,2 |
| Tempo médio de escrita da VM (ms) | 0,393 | 0,350 | 0,345 |
| Tempo médio de flush da VM (ms) | 0,552 | 0,506 | 0,496 |
| Ocupação média do NVMe físico | 3,72% | 12,19% | 11,22% |
| Profundidade média da fila do NVMe | 0,081 | 0,216 | 0,190 |
| Leituras físicas do buffer pool | 0 | 0 | 0 |
| Esperas por espaço no redo / buffer livre | 0 / 0 | 0 / 0 | 0 / 0 |

**Inferência limitada:** a regressão curta não é explicada por saturação
sustentada do SSD observada nessas rodadas. O índice reduziu latência mantendo
carga e tempos de I/O próximos aos do candidato anterior. O caminho normal do
Rust continua sem aguardar SQL por request. Picos menores que a resolução de
dois segundos não são excluídos por esses agregados.

Há, entretanto, um custo de persistência que precisa continuar acompanhado:
o candidato fez cerca de 3,6 vezes mais escritas/s na VM que o original e
produziu aproximadamente 79 MB de redo, contra 9,7 MB, em janelas de ~58 s.
A nova persistência confirma referência, endpoints e efeitos juntos; a tag
original usa filas separadas. Isso não é atribuído à troca do índice, pois já
aparecia no candidato anterior. O teste de 1.000 peers cabe no cache; não
demonstra comportamento do banco com 54 mil/100 mil peers ou sob interferência
maior de outras VMs. Nenhuma redução de garantias foi aplicada para melhorar
os resultados.

Contadores brutos e resumos: `lab/dualstack/results/rust-index/`. O coletor e
o analisador estão versionados; o README do laboratório descreve a reprodução.

### Perfil misto e limite restante

Com 50% de peers dualstack, o primeiro par curto passou funcionalmente, mas
reprovou o gate de latência: original `183903` p95/p99 0,233309/0,267002 ms;
candidato `184232` 0,274836/0,315242 ms (+17,80%/+18,07%). A carga continua
em 1.000 req/s, com 1.000 peers num torrent, 90.000 requests e crédito lógico
de 6.000.000 bytes. O candidato preserva 1.500 endpoints. O original só publica
o caminho legado; o custo do payload adicional está registrado separadamente.

O gerador incluía decodificação, validação dos endpoints e asserções na latência.
Acrescentei duas medidas auxiliares, sem remover a métrica antiga ou dispensar
asserções: tempo até receber o corpo inteiro e tempo posterior de validação/
retorno da tarefa. Repetição equivalente, ainda sem profiler:

| Código e rodada | p95 total / p99 total (ms) | p95 leitura / p99 leitura (ms) | p95 validação (ms) |
|---|---:|---:|---:|
| Original `184807` | 0,232137 / 0,265750 | 0,203001 / 0,231255 | 0,031820 |
| Candidato `184550` | 0,265660 / 0,306877 | 0,224201 / 0,258206 | 0,046016 |

Só até receber o corpo, a diferença é +10,44%/+11,65%. Portanto, a validação
local explica parte da diferença, mas separá-la não basta para aprovar o perfil.
Percentis das parcelas não são subtraíveis nem aditivos. O SSD físico apresentou
ocupação média abaixo de 14% nesses pares, com fila média abaixo de 0,3; não
houve espera por espaço de redo/buffer livre. São amostras de carga pequena,
não uma garantia de capacidade futura.

Outro limite do harness apareceu nessa população: saldo correto não prova que
as atualizações com delta zero foram persistidas. A rodada `184232` fechou saldo
e 1.000 identidades, mas tinha 89.973 versões para 90.000 requests naquele
snapshot. O encerramento gracioso subsequente drenou o proprietário; não é
evidência de perda. O gerador agora aguarda também todas as versões antes de
declarar drenagem. Rodadas antigas continuam documentadas como verificações de
saldo, sem afirmar que mediram toda a janela assíncrona dos endpoints.

Repetição final `rust-candidate-20261008T185727`, com essa asserção reforçada:
90.000 versões confirmadas, 1.500 endpoints, 6.000.000 bytes em referência,
histórico e saldo, 1.000 identidades sem divergência, drenagem em 1,01 s.
P95/p99 totais 0,268996/0,315643 ms; leitura 0,229091/0,266801 ms. Contra o
original instrumentado `184807`, +15,88%/+18,77% no total e +12,85%/+15,37%
na leitura. A reprovação do perfil misto permanece; não escolher a rodada
mais favorável para dispensar o critério.

### Diagnóstico de escala sem HTTP ou SQL no trecho medido

`rust-selection-probe.rs` usa o coordenador candidato real e a mesma fixture,
com três repetições de 2.000 chamadas, após 200 chamadas de aquecimento.
O bootstrap e a renovação/liberação de lease ficam fora do trecho medido.
Há asserções de contagem e payload fora do cronômetro. Sem escritores concorrentes.

| População no torrent, 50% dualstack | Medianas, `numwant=0` | Medianas, `numwant=25` |
|---|---:|---:|
| 1.000 | 6,15–6,21 µs | 8,51–8,55 µs |
| 54.000 | 354–364 µs | 445–470 µs |

Esse ensaio é diagnóstico e não libera a homologação HTTP com 54 mil peers.
Confirma custo aproximadamente proporcional à população: mesmo sem listas,
`response.rs` percorre todos os peers para calcular os totais vigentes. A seleção
mantém o mutex do estado durante a passagem. No caso de 54 mil, a mediana de
0,45–0,47 ms por seleção representa, por estimativa, 45–47% de um segundo de
seção crítica por 1.000 chamadas; não é medição de capacidade total do tracker.

### Próximas opções e impactos verificados

Prioridade recomendada: **contadores incrementais com expiração indexada e
seleção por elegibilidade**. O índice direto resolveu as buscas repetidas,
mas ainda existe a passagem completa por request. O próximo desenho deve:

1. Manter totais lógicos e por família pela diferença entre contribuições antes
   e depois, dentro da mesma seção de sincronização das transições.
2. Manter um índice de vencimentos com remoção/substituição explícita, limitado
   à cardinalidade dos endpoints; não acumular entradas antigas em rotação de IP.
3. Resolver vencimentos antes da resposta, preservando TTL exato mesmo sem o
   job periódico. Não servir contadores obsoletos para ganhar performance.
4. Amostrar peers elegíveis sem percorrer todo o torrent, preservando uniformidade,
   prioridade de seeders, exclusão do usuário e ambos os endpoints selecionados.
5. Integrar bootstrap, announce, conectividade, expiração, retenção, exclusão e
   snapshots administrativos. O estado derivado precisa ser reconstruível.

É uma mudança maior que o índice recém-validado. Riscos concretos: decremento
duplo na expiração, divergência entre índice e peer, respostas com total obsoleto
e crescimento do índice durante substituições. Requer nova revisão do desenho,
contratos de TTL/concorrência/recuperação e comparação de performance; **não foi
implementada nesta investigação**. Não afrouxar o gate como alternativa implícita.

Em incremento separado, investigar **redução de regravações de `peer_ips`**.
`persistence.rs:328` remove todos os endpoints dos peers do lote e os reinsere,
inclusive os que não mudaram de endereço. Uma estratégia de upsert com exclusão
apenas dos endpoints ausentes pode reduzir trabalho; o ganho ainda não foi
medido e essa observação não atribui a ela todo o redo adicional. Deve manter
mesma transação, versões, fencing, locks ordenados, retries e projeção legada.
Testar troca/stop/expiração de uma família, rollback após cada fase e reentrega.
Não reduzir `sync_binlog`/flush nem aumentar tolerância para mascarar o custo.

O perfil HTTP de 100% dualstack, cargas HTTP de 54 mil/100 mil, capacidade máxima
e ensaios longos permanecem pendentes. A investigação de SSD sob populações
grandes também permanece aberta; o probe em memória não mede esse comportamento.

### Encerramento do checkpoint

Tracker e geradores encerrados, namespaces ausentes, aliases temporários
removidos e lease liberada. Snapshot final: 90.000 versões, 1.000 peers,
1.500 endpoints, 6.000.000 bytes em todos os saldos/referências, zero divergências
e zero jobs falhos. `results/rust-index/final-state.json` registra esse estado.
O runner do probe remove seu arquivo temporário e foi reexecutado para verificar
a limpeza. PHP não mudou nesta investigação. Sem push ou produção.

Revisão final única do harness deste incremento contra o plano: observadores
somente de leitura, métricas por janela, comparação com mesmos parâmetros,
asserções financeiras preservadas e fechamento reforçado por versões. Os probes
permanecem diagnósticos; não aprovam gates maiores. Pendente a decisão sobre a
próxima otimização estrutural, cujos impactos estão descritos acima.

## Validação complementar do Rust — 8 de outubro de 2026

Objetivo desta rodada: verificar o diagnóstico antes de escolher outra mudança.
Produtos preservados: Rust `a9ab263de2fe6473c86eeabfd0b6ca1c019f6070` e PHP
`6d8e7437daa652fb02519584c456b15dceacffa4`. Os 58 arquivos de fonte/Cargo
instalados no tracker correspondem ao manifesto SHA-256 local. Não houve nova
otimização, mudança de durabilidade, push ou implantação em produção.

Evidências e consolidação: `lab/dualstack/results/rust-validation/analysis.json`;
respostas numéricas, amostras compactadas e recursos em `results/benchmarks/`.
Cada comparação usou 1.000 req/s, 50% dualstack, 30 s de aquecimento e 60 s
medidos, com origens reais. Essas janelas são diagnósticas, não substituem as
três repetições de 5 + 15 minutos nem o ensaio de seis horas.

### Repetições com 1.000 peers

| Caso | Original p95 / p99 (ms) | Candidato p95 / p99 (ms) | Diferença p95 / p99 |
|---|---:|---:|---:|
| `numwant=0`, uma rodada | 0,221137 / 0,262495 | 0,235524 / 0,274688 | +6,51% / +4,65% |
| `numwant=25`, rodada 1 | 0,232949 / 0,272804 | 0,274757 / 0,321044 | +17,95% / +17,68% |
| `numwant=25`, rodada 2 | 0,236324 / 0,281417 | 0,268855 / 0,316473 | +13,77% / +12,46% |
| `numwant=25`, rodada 3 | 0,237827 / 0,279123 | 0,266692 / 0,315693 | +12,14% / +13,10% |

São tempos totais do gerador, incluindo a validação da resposta. A ordem dos
pares foi original/candidato, candidato/original, original/candidato. O controle
sem lista passa o gate curto; os três pares com lista reprovam. A mediana dos
percentis por rodada representa +13,77%/+13,38%; não é um percentil calculado
pela junção das amostras.

Separando o tempo até receber o corpo: medianas p95/p99 de
0,207499/0,243378 ms no original e 0,228389/0,267712 ms no candidato,
diferenças de +10,07%/+10,00%. As rodadas individuais variam aproximadamente
9–15%, portanto esse resultado fica perto do limite e não sustenta uma
reprovação uniforme muito acima dele. Não somar ou subtrair percentis das
parcelas para estimar outro percentil. As asserções mais extensas das listas
dualstack explicam parte da diferença total, não todo o custo observado.

### 54 mil peers e bloqueio no bootstrap

Com 54.000 peers distribuídos em 5.400 torrents, original/candidato encerraram
sem divergências em 54.000 identidades, com 6.840.000 bytes em cada referência,
histórico e saldo. O candidato confirmou todas as 90.000 transições.
P95/p99: original 0,233880/0,310033 ms; candidato 0,234762/0,277943 ms,
diferenças +0,38%/−10,35%, dentro do gate curto.

Desativamos somente os snapshots SQL periódicos do gerador nesses ensaios
maiores, igualmente para ambos: eles próprios percorrem tabelas e poderiam
influenciar o resultado. Checagens antes/depois, cada identidade, saldos e
versões continuam obrigatórias. I/O e recursos continuam amostrados. Sem esses
snapshots, não se afirma ter medido a evolução periódica do backlog em 54 mil.

Duas falhas distintas foram preservadas:

1. No primeiro candidato distribuído, o gerador verificou a conexão antes do
   listener abrir. O runner agora espera ambas as famílias, limitado a 180 s.
   A repetição passou; a tentativa sem carga não tem resultado de performance.
2. No candidato concentrado, a consulta de reconciliação de contadores no
   bootstrap excedeu o limite interno de 120 s. O Rust saiu com código 1,
   mas o `UPDATE` permaneceu executando no MySQL. Aos 339 s, o Performance
   Schema registrou 1.059.886.858 linhas examinadas, zero linhas alteradas e
   transação `RUNNING`, sem espera por lock. Em aproximadamente dois segundos,
   as leituras no índice `peer_ips_torrent_family_live` cresceram 6.664.490,
   contra 290 pela chave primária.

O `SELECT` agregado equivalente terminou em 0,291 s. Um `EXPLAIN` posterior
escolheu a chave primária; o plano da instrução preparada em execução não pôde
ser obtido (`EXPLAIN FOR CONNECTION` retornou erro 3012). A consulta antiga foi
cancelada pela conexão específica do banco descartável, e a repetição do mesmo
código/dados iniciou em 1,875 s. Isso comprova a sensibilidade ao plano de
execução; estatísticas transitórias após montar a fixture são uma hipótese para
a escolha inicial, não uma causa definitivamente isolada.

O par concentrado subsequente prepara explicitamente as estatísticas das quatro
tabelas antes de ambos os backends, com `-AnalyzeFixture`. Essa preparação
controla o ensaio; não corrige o produto nem elimina a pendência de robustez do
bootstrap/cancelamento. Evidências: `bootstrap-popular-failure.txt`,
`bootstrap-popular-sql.json`, `bootstrap-live.json`, `bootstrap-admin.json` e
`bootstrap-unchanged-retry.txt` no diretório da validação.

### Frequência de persistência e I/O

O original usa `FLUSH_INTERVAL_MILLISECONDS=3000`. O coordenador dualstack tem
tick de 100 ms (`src/dualstack/coordinator.rs:346`), com lote padrão de 200.
O controle adicional manteve o original e alterou apenas sua configuração para
100 ms. Não torna equivalentes as filas ou suas garantias transacionais; apenas
isola parte do efeito da frequência e da agregação de atualizações.

| Perfil, 1.000 peers / 50% dualstack | Escritas/s na VM | MiB/s escritos | Redo MiB/s |
|---|---:|---:|---:|
| Original, flush de 3 s, três rodadas | 118–133 | 2,15–2,28 | 0,157–0,158 |
| Original, controle de 100 ms | 476 | 5,54 | 0,524 |
| Candidato, tick de 100 ms, três rodadas | 432–497 | 7,36–7,69 | 1,54–1,55 |

A frequência explica parte importante da diferença anterior de IOPS. Ainda
há aproximadamente 2,95 vezes mais redo no candidato frente ao controle de
100 ms. Não atribuir todo o custo ao delete/insert de endpoints: também mudaram
agregação, versões, estado de protocolo e transações. O ganho de trocar essa
estratégia por upserts seletivos continua sem medição.

Em 54 mil distribuídos, o candidato gerou 612 escritas/s e 10,86 MiB/s na VM,
contra 327 e 6,34 no original. A fila média observada foi 0,30 no candidato,
com média de escrita de 0,33 ms e flush de 0,48 ms. Nenhuma espera por espaço de
redo ou buffer livre em ambos. Isso não evidencia saturação sustentada do banco
a 1.000 req/s nessa janela; não determina a capacidade máxima do SSD.

O host apresentou saltos nos contadores acumulados de tempo de escrita e tempo
ponderado do NVMe, também em algumas rodadas pequenas de ambos os backends.
Alguns deltas de aproximadamente 65–66 milhões de ms em intervalos de 2 s se
aproximam do uptime do host. As médias de espera/fila derivadas desses campos
ficam inconclusivas nessas janelas. Os dados brutos permanecem preservados;
nenhuma amostra foi excluída para melhorar o resultado. Os contadores na VM do
banco não apresentaram o mesmo padrão. SMART: sem alerta crítico, erros de
integridade ou entradas de erro; nenhuma ocorrência correspondente de timeout/
erro NVMe no log de kernel consultado. Isso não prova ausência de gargalo nem
estabelece a causa do contador anômalo. Ver `host-io-audit.txt` e
`host-large-time-deltas.json`; o analisador sinaliza os intervalos que requerem
investigação.

### Resultado concentrado e decisão recomendada

O par com estatísticas preparadas concluiu 90 mil requests em cada backend,
sem falhas, drops ou divergência. O candidato confirmou 90 mil versões e 81 mil
endpoints para 54 mil peers. Resultado do perfil concentrado:

| Métrica | Original | Candidato | Diferença |
|---|---:|---:|---:|
| p95 total | 0,427448 ms | 1,434875 ms | +235,68% |
| p99 total | 0,532958 ms | 1,677083 ms | +214,67% |
| p95 até receber o corpo | 0,392082 ms | 1,384520 ms | +253,12% |
| p99 até receber o corpo | 0,493403 ms | 1,616909 ms | +227,71% |
| CPU mediana do container | 15,49% | 63,57% | escala de 100% por CPU |

Com a mesma população distribuída, a CPU mediana do candidato foi 7,02%,
enquanto a escrita na VM passou de 10,86 para 10,90 MiB/s ao concentrar os peers.
Isso, junto do probe sem SQL já realizado e da varredura em
`src/dualstack/response.rs:127`, sustenta priorizar o custo de seleção/contagem
em memória. Não demonstra que o custo de I/O seja irrelevante em cargas maiores.
No concentrado candidato: fila média da VM 0,38, escrita 0,40 ms, flush 0,50 ms,
zero esperas por espaço de redo/buffer livre. O ganho de uma futura otimização
continua sem medição.

Fechamento: **13 ensaios com carga, 1.170.000 requests aceitos, zero erros,
zero drops, nenhuma divergência e nenhum deadlock/timeout de lock novo durante
as janelas de carga**. Os seis ensaios candidatos confirmaram suas 540 mil
transições. Isso não inclui as duas tentativas abortadas antes de gerar carga,
nem aprova o bootstrap que falhou. Nos quatro ensaios pequenos candidatos,
a estimativa periódica máxima foi de 113–124 versões ainda não confirmadas;
a drenagem final ficou em aproximadamente 1,0–1,1 s. A ausência de amostras
periódicas nos grandes impede afirmar estabilidade sustentada do backlog ali.

`achieved_rps` relaciona requests aceitos agendados na janela e sua duração;
não é uma busca de throughput máximo nem uma contagem estrita de respostas
concluídas antes do último instante. Não houve descarte e o máximo observado
de atraso total permaneceu abaixo de 14 ms nos pares grandes, mas uma futura
rampa de capacidade deve medir também conclusões por janela e atraso do gerador.

Próximo incremento recomendado, ainda não implementado:

1. **Corrigir a robustez do bootstrap**: tornar a reconciliação previsível mesmo
   com estatísticas desfavoráveis e garantir encerramento/rollback da operação
   SQL ao esgotar seu prazo. Preservar lease, exclusão entre proprietários e
   bloqueio da entrada enquanto o estado não estiver pronto. Regressão com
   carga concentrada recém-criada, plano desfavorável e timeout forçado.
2. **Depois, contadores incrementais, expiração limitada e seleção por índice**,
   com os cuidados de TTL, conectividade, contagem única e memória já descritos.
   O ensaio HTTP agora confirma a reprovação que o probe apenas antecipava.
3. **Tratar a redução de escrita separadamente**, mantendo transações,
   idempotência e durabilidade. O controle de 100 ms impede atribuir todo o
   aumento anterior de IOPS à tabela de endpoints.

Não iniciar a matriz longa antes desses gates. Permanecem pendentes 100%
dualstack, HTTP com 100 mil peers, repetições de 5 + 15 minutos, capacidade
máxima, backlog sustentado, churn de seis horas e janela de perda abrupta.
Não há recomendação de alterar o SSD ou o kernel com base nos contadores
inconclusivos do host.

Laboratório encerrado: nenhum container do tracker, listener, cliente real,
namespace ou alias temporário; lease inativa e consulta antiga cancelada.
O último estado corresponde ao original: 54 mil peers, 6.840.000 bytes nas
referências/históricos/saldos e zero divergências/jobs falhos. Versões zero nesse
snapshot são esperadas para o original; as versões dos candidatos estão em
seus próprios resultados. Os totais históricos de locks no servidor são
acumulados de ensaios anteriores; a validação usa a diferença antes/depois.

Revisão final única do incremento contra o plano: mudanças limitadas ao harness,
diagnóstico e evidências. Estatísticas preparadas identificadas separadamente;
falhas preservadas, sem alterar o gate. A revisão reforçou a recusa de host
incorreto e de container legado antes do reset. Sintaxe, cenários do guard e
consolidação aprovados; produtos e lockfiles permanecem nos commits informados.

## Referência operacional e levantamento de densidade

Após essa investigação, o operador definiu **250 peers por torrent** como pior
caso esperado, normalmente com densidade menor. Os 54 mil peers concentrados
permanecem como evidência exploratória; não são uma exigência operacional nova.
Isso não confunde a concentração com a população total residente, que pode ser
grande mesmo quando cada torrent tem poucos peers.

O [levantamento de densidade](dualstack-densidade.md) mede o candidato Rust
sem alterar seu código, com curvas por torrent, controles de interferência e
refinamento da faixa de degradação. Os dados anteriores, incluindo reprovações,
continuam preservados. O levantamento informativo não substitui uma comparação
formal original/candidato no perfil operacional, nem resolve a pendência de
bootstrap, a anomalia dos contadores do host ou os testes prolongados pendentes.
