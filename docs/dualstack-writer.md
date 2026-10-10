# Otimização do escritor Rust

Incremento autorizado após [o diagnóstico](dualstack-throughput.md), seguindo
[o plano](plans/2026-10-08-writer-rust.md). Base Rust `a9ab263`; PHP `6d8e743`.

Implementado e validado no laboratório. Commits Rust `3483869` (cadência) e
`9446bfd` (endpoints). O padrão continua em lotes de 200; os resultados de maior
throughput abaixo usam `DUALSTACK_BATCH_SIZE=500`, que exige restart.

## Resultado e checkpoint

O candidato final sustentou 8.000 requests/s durante 180 s após 10 s de warmup:
1.520.000 announces aceitos, 1.440.000 amostras medidas, p95 de 0,192 ms e p99
de 0,252 ms. A fila oscilou até 5.316 transições, caiu de 1.205 para 875 entre
as amostras extremas e drenou em 0,272 s. O escritor ficou ocupado 81,6% do
tempo; Rust usou 39,7% e MySQL 78,2% de um núcleo, em média. Não houve crescimento
contínuo de backlog, erro HTTP, retry SQL ou divergência contábil.

As seis séries válidas deste incremento somam **8.720.000 announces**, 7.200.000
amostras medidas e 40 fases. Todas passaram na auditoria de amostras, payload,
crédito, versões e cardinalidade. A série interrompida por disco cheio foi
excluída desses totais. A suíte funcional com MySQL/Redis reais passou, incluindo
57 testes PHP/746 assertions no caminho de limpeza/exclusão; os demais testes
e a investigação dos problemas do harness estão descritos abaixo.

O restart com o binário de produto sem instrumentação preservou 10 mil peers,
20 mil endpoints, 1.520.000 versões e crédito de 76.000.000 bytes, iguais em
peers, histórico e usuários. Somente a geração do proprietário mudou de 1.678
para 1.679. Lease liberada, nenhuma query do teste ativa ou job falho. Os 144
endereços temporários foram removidos; não restam namespaces, containers do
tracker ou listener 8080. MySQL/Redis do laboratório permanecem disponíveis.

Evidência consolidada: `lab/dualstack/checkpoint-writer.json`,
`lab/dualstack/results/writer/summary.json`, `manifest.json`, logs funcionais,
snapshots de restart e análises/amostras `density-throughput-writer-*` em
`results/throughput`. Hashes distinguem produto e instrumentação; lockfiles e
o produto PHP permaneceram inalterados neste incremento.

Estes são testes intermediários em 40 torrents × 250 peers, 100% dualstack,
HTTP direto e conexões persistentes, sem probes de conectividade nem log de
announces. Continuam pendentes o gate de seis horas, a matriz completa de
população/família, os caminhos com proxy/TLS e os gates anteriores de torrents
densos. Os 8 mil/s são o patamar confirmado por três minutos neste laboratório;
10 mil/s ficam perto do teto e 12 mil/s acumulam fila. Não houve push, publicação
ou implantação em produção. Announces aceitos ainda não persistidos continuam
sujeitos à janela assíncrona de perda em encerramento abrupto.

## Cadência e configuração

O supervisor drena lotes cheios sem aguardar o timer de 100 ms. Um ciclo processa
até oito lotes ou 100 ms, verificados entre transações. Há yield e manutenção
entre ciclos; heartbeat e encerramento continuam supervisionados. O orçamento
não interrompe um commit: seu timeout de 15 s e os retries anteriores continuam
valendo (`src/dualstack/coordinator.rs:345`).

`DUALSTACK_BATCH_SIZE` aceita 1–500, padrão 200. Exige restart; o reload mantém a
recusa de alterar a política em execução (`src/config.rs:367`). Não aumenta o
limite de backlog, não cria escritores SQL paralelos e não altera o contrato PHP.

Validação inicial:

- Contrato compartilhado: 12 casos/51 operações; cinco testes Rust passaram.
- MySQL real: 100 transações pequenas drenadas em menos de três segundos;
  lotes 500/500/1; crédito único; replay, restart, rollback e falhas de lease.
- BON: quatro tarefas Rust serializadas e um consumidor BON, sem novo deadlock.
- Refunds: nove escritores SQL, 480 transições, 1.920 tentativas de persistência,
  160 comandos de reembolso; crédito correto e sem novos deadlocks/timeouts.
- Handoff PHP/Rust/PHP: 27 testes PHP, 474 assertions, journal pendente bloqueado,
  crédito e endpoints preservados nas três fases Rust.
- Rede/configuração: 19 testes; valores 0, 501 e não numérico recusados no startup.

O primeiro ensaio de refunds falhou na preparação: FK 1452, SQLSTATE 23000,
`refund-rust-consumer.php:36`, porque a fixture assumia um uploader `id=1` ausente
no banco recriado. O helper agora seleciona um usuário existente fora dos três
reembolsados. A repetição passou. Nenhuma alteração no produto PHP foi necessária.
Os logs de falha e repetição foram mantidos em `results/writer`.

Revisão única do primeiro diff contra o plano: mudanças restritas à cadência,
configuração, documentação e regressões declaradas. Sem divergência de escopo.

## Comparação de carga

Usar as mesmas 40 swarms de 250 peers, 100% dualstack, ordem
embaralhada e três repetições. As cópias `writer-cadence` e `writer-endpoints`
recebem apenas instrumentação; hashes identificam o código de produto. Não
misturar estes resultados com os protótipos históricos em `summary.json`.

Cadência validada nas séries `cadence200-v2` e `cadence500-v1`: 3.450.000
announces, 2.760.000 amostras medidas e 18 fases. Todas passaram na auditoria
de amostras, saldos, referências, versões e cardinalidade. Com 200, as três
repetições a 6 mil/s terminaram com drenagem de 0,27–0,28 s. Com 500, a 12 mil/s,
as confirmações foram 9.842/9.842/10.316 por segundo; o backlog cresceu
2.158/2.160/1.688 por segundo. São janelas medidas de 20 s após 5 s de warmup,
sem certificação de carga sustentada prolongada.

O controle contemporâneo `reference200-v1` usa o produto anterior `a9ab263`,
com instrumentação e sem os protótipos de drenagem. Nas três repetições a
4 mil requests/s, confirmou aproximadamente 2 mil/s e acumulou aproximadamente
2 mil/s na fila; a drenagem final levou 25 s. Isso distingue resposta HTTP de
capacidade sustentável de confirmação. O candidato final com lotes de 200
confirmou 3.996/s, drenando em 0,27 s. Medianas de p95: 0,2528 → 0,2514 ms;
p99: 0,3143 → 0,3170 ms (+0,87%). Este comparativo passa a tolerância de 10%
nessa carga; não substitui a matriz completa de performance da feature.

A 6 mil/s e lote 200, o redo passou de 6,32 para 5,27 MB/s (-16,5%) ao trocar
a cadência corrigida pela persistência seletiva. A escrita observada no disco
da VM passou de 31,99 para 29,97 MiB/s (-6,3%). Todos os 750 mil announces da
série `endpoints200-v1` passaram na auditoria final de crédito e cardinalidade.

Com lote 500, medianas das três repetições:

| Taxa oferecida/s | Confirmações/s, só cadência | Confirmações/s, endpoints seletivos | Fila final seletiva |
|---|---:|---:|---|
| 6.000 | 5.996 | 6.002 | drenagem em 0,27 s |
| 8.000 | 7.998 | 7.994 | drenagem em 0,27 s |
| 10.000 | 10.016 | 10.353 | drenagem em 0,27–0,79 s; perto do teto |
| 12.000 | 9.842 | 10.289 | crescimento de 1.184–1.921/s; não sustentável |

Uma taxa confirmada acima da oferecida em uma janela significa recuperação da
fila do warmup. Não são requests extras nem evidência de capacidade permanente.
Não arredondar o ensaio de 12 mil/s para “12 mil/s sustentáveis”: as três
repetições encerraram a janela com aproximadamente 49–51 mil transições na fila.
Todas foram drenadas e auditadas, sem duplicação, erros HTTP ou retries SQL.

A 8 mil/s, a persistência seletiva reduziu redo de 7,94 para 6,58 MB/s (-17,1%),
escrita no disco da VM de 36,94 para 34,13 MiB/s (-7,6%) e tempo médio por lote
de 51,47 para 46,37 ms (-9,9%). A mediana do teto observado sob carga de
12 mil/s subiu 4,5%, com sobreposição entre as repetições; não é uma garantia
universal de ganho. As duas séries de lote 500 passaram na auditoria financeira,
totalizando 5,4 milhões de announces.

O limite continua na transação de persistência: perto de 12 mil requests/s, o
escritor passa aproximadamente 100% do tempo confirmando lotes de 500 em cerca
de 49 ms. Na repetição final, endpoints consumiram 13,85 ms, deltas financeiros
11,38 ms, commit 6,29 ms, peers 5,81 ms, leitura/fencing 5,38 ms e histórico
5,13 ms. São spans do caminho serial, não um perfil de CPU interno do MySQL.
O MySQL usa aproximadamente um núcleo agregado; a VM tem quatro vCPUs e
iowait mediano de 19,8% nessa carga. O tempo de espera dos mutexes de publish
e seleção foi inferior a 0,1 µs na média. Não há evidência aqui para começar
por sharding dos mutexes, Redis ou Nginx. HTTP direto exclui o proxy deste teste.

A próxima investigação possível é reduzir custo das consultas de endpoints e
deltas, mantendo ordem de locks, idempotência e commit conjunto. Não foi
implementada uma troca de estratégia financeira neste incremento. O ensaio
também não isola quanto um SSD melhor acrescentaria: o ganho precisa de um
controle em outro armazenamento mantendo as demais condições.

## Escritas de endpoints

Cada transição guarda duas flags calculadas contra o estado anterior na mesma
seção de sincronização (`src/dualstack/coordinator.rs:251`). Depois dos guards
de versão e geração, o consumidor coalesce a última mudança de cada família;
upsert atualiza somente caminhos alterados e DELETE remove somente famílias
encerradas (`src/dualstack/persistence.rs:305`). A referência financeira e o
snapshot completo do peer continuam confirmados na mesma transação.

`peer_ips.updated_at` passa a registrar a última alteração daquele endpoint;
um announce na outra família não o modifica. Uma nova encarnação do endpoint
atualiza também `created_at`, revisão, IP/porta e resultado de conectividade.
O schema e o contrato de leitura permanecem compatíveis com PHP.

O teste real usa deltas de `Com_insert`/`Com_delete` e snapshots completos dos
endpoints, sem outros escritores no servidor isolado:
renovação de uma família, contador alterado sem alteração de endpoint,
troca de IP, probe antigo, remoção/reinserção coalescida, replay parcial,
rollback depois dos endpoints e expiração independente. Todos passaram, assim
como a suíte anterior, BON/refunds, handoff e exclusão de usuários/torrents com
crédito pendente (`results/writer/step2-validation-run6.txt`).

A revisão única do segundo diff contra o plano não encontrou divergência:
somente flags de mudança, persistência seletiva e os testes correspondentes.
Nenhuma mudança de schema, saldo, protocolo de confirmação ou contrato PHP.

A primeira instrumentação tentou criar triggers: MySQL recusou o protocolo
prepared (1295) e, após usar SQL direto, exigiu SUPER com binlog ativo (1419).
A versão final do teste usa SHOW GLOBAL STATUS; não foram elevados privilégios
nem alterada a política de binlog. Os dois logs de tentativa foram preservados.
O CHECK usado para injetar rollback invalida statements preparados: foram
observadas seis repreparações, que também afetam `Com_insert`. Por isso, as
asserções de quantidade exata de SQL usam schema estável; após o DDL, o teste
verifica rollback, estado final e crédito. A decodificação do timestamp da
fixture também foi corrigida. As tentativas e a execução final estão preservadas.

### Interrupção ambiental da primeira série

`density-throughput-writer-cadence200-v1` passou a fase de 4 mil/s e falhou na
fase de 6 mil/s. Às 22:44:02 UTC, o MySQL registrou erro 28: disco cheio ao
gravar `binlog.000013`. A VM de dados estava em 100% de uso; o volume MySQL
ocupava 11 GiB. O processo do banco não reiniciou e não houve OOM. Os observers
Docker também falharam durante esse intervalo. A confirmação de lotes parou,
o heartbeat excedeu três segundos e o Rust fechou a entrada.

Não atribuir essa interrupção à cadência nem usar a série como medição de teto.
Havia transições aceitas ainda em memória, e não foi certificado o saldo final
da série interrompida. Os artefatos foram preservados; a repetição usa nome v2.

O disco da VM 121 (`unit3d-ds-data`) foi ampliado de 16 para 24 GiB, após verificar
27,8 GiB livres no thin pool. A partição ext4 cresceu online, deixando 7,8 GiB
livres. O primeiro growpart não conseguiu criar temporário no disco cheio;
TMPDIR=/run permitiu concluir. Nenhum timeout, fsync ou configuração de binlog
foi relaxado, nem foi removido histórico SQL. O runner agora exige mais de 2 GiB
livres antes de iniciar uma série; o observer registra espaço disponível.

Antes do ensaio sustentado, o disco de dados passou de 24 para 32 GiB. O pool
tinha 20.213.891.072 bytes físicos disponíveis; a expansão online deixou
9.740.034.048 bytes livres na VM. A operação ocorreu entre séries, com o tracker
parado. O thin pool é compartilhado e tem volumes virtuais sobrealocados:
capacidade virtual livre na VM não substitui a verificação de espaço físico no
Proxmox. A campanha de seis horas exigirá orçamento de armazenamento e retenção
dos binlogs; nenhuma política de retenção foi alterada nesta etapa.

## Revisão e limites do incremento

Revisão final única do diff de coordenação contra o plano: instrumentação
isolada, fontes identificados, fixtures e resultados novos separados dos
históricos, ensaios financeiros/restart auditados e laboratório encerrado.
Os ajustes do harness e de capacidade responderam a falhas observadas e estão
documentados. Não houve alteração adicional no produto PHP, sharding, mudança
de locks ou de política financeira. Os dois diffs de produto foram revisados
nas respectivas etapas; nenhuma divergência de escopo permaneceu.
