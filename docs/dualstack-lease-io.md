# Verificação do acúmulo e do timeout da lease — 09/10/2026

**A espera de uma transação de persistência consegue bloquear a renovação da
própria lease e derrubar o Rust com crédito ainda em memória.** A reprodução
usou o mesmo binário do ensaio interrompido e apenas 20 requests/s. O mecanismo
foi confirmado pela cadeia de locks do MySQL, sem saturar o armazenamento.

**A causa física da lentidão da v2 continua sem confirmação.** Na carga natural
curta, 8.000 requests/s durante três minutos passaram com crédito integral e
drenagem. Isso demonstra capacidade nesse intervalo, sem excluir uma pausa
eventual do SSD compartilhado após horas. Não aprova as seis horas, o PHP ou
a comparação formal entre original e candidato.

## Isolamento e método

- Plano autorizado: `plans/2026-10-09-verificacao-lease-io.md`.
- VMs 120–122 do laboratório existente; nenhum serviço de produção acessado.
- Banco sintético clonado **dentro da VM**, em
  `unit3d_dualstack_probe_20261009`; nenhum dump, binlog ou passkey exportado.
- Container temporário `unit3d-ds-lease-probe`, HTTP direto na porta 8081,
  origens IPv4/IPv6 reais. O container e banco da v2 foram preservados.
- SHA-256 do binário:
  `8b825a1afb418f237803d5306abb0b57c2340ecb4b9f5871bc61dd290f3e4ace`.
- Rust no commit `9e8b54626334db11940e3ebf939cbf40ba4426a3`; PHP no commit
  `7c45115fc8b7ad83d12b0a44a5e656c12240ede4`; árvores de produto limpas.
- MySQL 8.0.46, `innodb_flush_log_at_trx_commit=1`, `sync_binlog=1`,
  buffer pool 128 MiB, redo 100 MiB, `io_capacity=200`, máximo 2.000,
  `REPEATABLE-READ`, timeout de lock 10 s. Configurações não alteradas.
- Lotes Rust de 500, TTL 7.200 s, conectividade desabilitada, arquivador ativo.
  Base com 10.000 peers e 20.000 endpoints; carga distribuída por 8.000 seeders,
  com contadores cumulativos iguais nos dois caminhos. Os controles de lock
  exercitam um único peer dessa base.
- Observação SQL e I/O a cada 250 ms nos controles e 1 s nas cargas. Os dados
  exportados são agregados, IDs de conexões e metadados de locks, sem SQL privado.

O bloqueador experimental segura uma linha de `users` por 1 ou 9 segundos.
Ele não bloqueia `tracker_ownership` diretamente. Assim a cadeia intermediária
precisa ser formada pelo próprio produto para confirmar a hipótese.

## Resultado dos controles

| Execução | Carga | Bloqueio | Aceitos | Resultado |
|---|---:|---:|---:|---|
| `control-none-v1` | 20/s por 10 s | nenhum | 200 | crédito 10.000, drenado |
| `control-short-v1` | 20/s por 10 s | 1 s | 200 | crédito 10.000, drenado, exit 0 |
| `control-long-v1` | 20/s, até falhar | 9 s | 142 | timeout da lease, exit 1, sem drenagem |

No controle longo, as **142 transições e 7.100 bytes de crédito** aceitos ficaram
sem persistência. As três tabelas contábeis permaneceram em zero e coerentes
entre si. O gerador registrou `IncompleteReadError` quando o processo encerrou;
o log do Rust contém exatamente:

```text
Error: Coordenador dualstack: Tempo limite de renovacao da lease excedido
```

A falha longa é o resultado esperado da reprodução, não um teste de resiliência
aprovado. Não houve OOM. O disco virtual escreveu 3,52 MiB/s, com espera média
de escrita de 0,293 ms e atividade de 3,88% nesse intervalo. Portanto não foi
necessário provocar um gargalo físico para alcançar esse caminho de falha.

### Cadeia confirmada no MySQL

| Conexão que espera | Recurso e lock solicitado | Quem bloqueia | Lock mantido |
|---|---|---|---|
| 32355, persistência Rust | `users`, X | 32361, bloqueador do ensaio | X em `users` |
| 32354, renovação Rust | `tracker_ownership`, X | 32355, persistência Rust | S em `tracker_ownership` |

A primeira aresta aparece em 35 amostras; a segunda, em 19. Horários UTC:

- 13:55:18,265: primeira observação do escritor esperando em `users`.
- 13:55:22,266: primeira observação da renovação esperando pelo escritor.
- 13:55:25,095: processo Rust termina com código 1.
- 13:55:26,769: ambas as esperas ainda aparecem no servidor.

O código explica essa sequência: a transação valida a geração com `FOR SHARE`
em `repos/UNIT3D-Announce/src/dualstack/persistence.rs:56`, antes de persistir
o lote (`:280`); a renovação precisa de `UPDATE` na mesma linha e possui limite
de três segundos (`:37`). A persistência inteira admite quinze segundos
(`:267`). Uma transação pode, portanto, permanecer dentro de seu orçamento
e ultrapassar o orçamento de renovação que ela mesma bloqueou.

O erro fecha a entrada em
`repos/UNIT3D-Announce/src/dualstack/coordinator.rs:199` e retorna pelo ramo
de erro do `select!` (`:395`); o caminho de parada normal chama `shutdown()`
em `:401`. Neste ensaio esse erro encerrou o processo sem persistir a fila.
Não há ciclo de deadlock: é uma cadeia de espera encerrada pelo timeout do
cliente Rust.

Há também um resultado relevante para a recuperação: a lease ainda tinha
aproximadamente **22 segundos de validade** quando o processo encerrou.
Depois da liberação do bloqueador, seu vencimento avançou aproximadamente
cinco segundos, embora o processo já tivesse saído. Em conjunto com as esperas
observadas após o exit, isso indica que o timeout local não confirmou o
cancelamento da operação no servidor. A futura correção precisa tratar o
resultado SQL incerto, sem assumir que timeout significa rollback confirmado.

## Carga sem bloqueador e armazenamento

| Métrica | `load-4000-v1` | `load-8000-v1` |
|---|---:|---:|
| Taxa programada / duração | 4.000/s / 30 s | 8.000/s / 180 s |
| Aceitos / erros | 120.000 / 0 | 1.440.000 / 0 |
| Throughput observado em intervalos de aproximadamente 10 s | 3.999,57–4.000,53/s | 7.999,36–8.000,77/s |
| Resposta p95 / p99 | 0,444 / 0,540 ms | 0,360 / 0,589 ms |
| Crédito em peers, histórico e usuários | 6.003.200 em cada conjunto | 72.000.000 em cada conjunto |
| Versões não persistidas / divergências por peer | 0 / 0 | 0 / 0 |
| Tempo da verificação final de drenagem | 0,060 s | 0,324 s |
| Escrita no disco virtual da VM de dados | 17,39 MiB/s | 33,24 MiB/s |
| Escritas / flushes por segundo na VM | 1.120 / 369 | 2.080 / 691 |
| Espera média por escrita / flush na VM | 0,330 / 0,459 ms | 0,368 / 0,460 ms |
| Atividade do disco virtual | 32,45% | 63,42% |
| Escrita total no NVMe físico | 18,94 MiB/s | 35,13 MiB/s |
| Escritas / flushes por segundo no NVMe | 1.661 / 390 | 3.008 / 717 |
| Menor validade restante da lease amostrada | 25,51 s | 25,48 s |
| Maior duração da consulta do observador SQL | 0,084 s | 0,203 s |

Na carga de 8 mil/s, o MySQL registrou 62 esperas de linha, somando 1,006 s;
nenhuma cadeia foi capturada nas amostras de um segundo. Isso não significa
ausência de waits curtos. Não houve incremento de `Innodb_log_waits` ou
`Innodb_buffer_pool_wait_free`. Esses contadores não excluem todos os tipos
de pressão de checkpoint; o maior afastamento entre LSN corrente e checkpoint
amostrado foi 73.645.201 bytes.

A pressão de I/O da VM (`some`, calculada pelo delta de tempo) foi de 17,13%
na carga maior, contra 8,59% na menor. PSI mede tempo de tarefas bloqueadas,
não porcentagem de utilização do SSD. A espera média observada nas operações
de arquivo redo foi 0,261 ms na carga maior; o máximo histórico de 5,918 s já
existia antes e não mudou. Não foi usado como se fosse uma pausa deste teste.

Os LXC observados escreveram aproximadamente 0,071 MiB/s no NVMe durante a
carga maior. Essa concorrência foi pequena nesse intervalo; não reproduz o
perfil de concorrência do incidente. Os diretórios QEMU não expuseram `io.stat`
por VM; a VM de dados foi medida pelo seu próprio disco virtual. As métricas
do dispositivo físico incluem todo o host.

O contador de tempo de escrita/atividade do NVMe apresentou quatro intervalos
inconsistentes na carga maior. O analisador preserva os dados e deixa a média
de espera/atividade física sem valor, em vez de fabricar uma estimativa.
Contagens de bytes/operações e os contadores do disco virtual permaneceram
utilizáveis. Os máximos e percentis calculados de médias por intervalo não
são percentis de latência de cada operação individual de disco.

## Conclusão e próximo ajuste

1. **Confirmado:** atraso na transação de dados pode bloquear a renovação e
   provocar encerramento com perda da fila em memória, mesmo sob carga baixa.
2. **Confirmado nesse intervalo:** o ambiente persistiu 8 mil requests/s por
   três minutos. A capacidade média de escrita não ficou abaixo da entrada.
3. **Não confirmado:** que o SSD físico ou outro serviço específico causou a
   pausa da v2. A curta duração e a concorrência baixa não permitem excluir
   esse gatilho; os dados antigos não possuem a resolução necessária.

O próximo ajuste deve tratar a renovação e a recuperação do coordenador Rust:
fechar novas entradas durante incerteza, preservar o trabalho aceito enquanto
for seguro recuperar, confirmar o resultado da transação e a propriedade
antes de continuar. A validação deve repetir este bloqueio e incluir outro
proprietário assumindo uma nova geração. **Remover o lock de proteção ou apenas
aumentar o timeout não resolve, por si só, a segurança da troca de proprietário
e a perda da fila.** Melhorar o SSD pode reduzir o gatilho; não elimina esse
comportamento confirmado do produto. Nenhuma correção do produto foi feita
nesta verificação.

## Encerramento e reprodução

Os controles normais e as duas cargas drenaram. O novo container foi parado
e removido. A auditoria final confirmou 10.000 peers, 20.000 endpoints, um
por família, nenhuma violação de tamanho de IP, nenhuma conexão pendente ou
lock em espera no banco novo e lease liberada. O banco de diagnóstico e a
configuração privada permanecem no laboratório para reprodução.

Os agregados da v2 continuam em 69.060.362 versões, crédito 3.424.366.900,
10.000 peers e 20.000 endpoints; sua geração é 1.951 e a lease está expirada.
O container original mantém exit 1 e término às 07:22:06Z. A v2 não reiniciou.

Scripts: `lease-probe-admin.py`, `lease-probe-client.py`,
`lease-probe-observer.py`, `run-lease-probe.ps1` e `analyze-lease-probe.py`, em
`lab/dualstack`. O runner requer os módulos do laboratório já instalados e
o banco preparado. `prepare` recusa banco existente; `reset` atua apenas no
banco de diagnóstico com lease inativa. Não executar reset no banco da v2.

Resultados públicos: `lab/dualstack/results/lease-probe/`, com séries brutas,
ciclo de vida, resultado contábil individual agregado, análise e manifesto
SHA-256. Para recalcular: `python lab/dualstack/analyze-lease-probe.py`.
O gerador executa auditoria por peer no próprio laboratório, sem exportar
suas identidades privadas. Os scripts Python e PowerShell passaram na análise
de sintaxe e foram executados contra o MySQL real. Durante a preparação,
uma tentativa de reset com revisão zero foi rejeitada pela constraint;
o harness foi ajustado para revisão inicial 1 antes de gerar tráfego.

Atualização posterior: a correção e seus gates passaram em cópia separada.
Ver [recuperação da lease](dualstack-recuperacao-lease.md). O diagnóstico e
as evidências anteriores permanecem preservados; o ensaio de seis horas
continua sem aprovação.
