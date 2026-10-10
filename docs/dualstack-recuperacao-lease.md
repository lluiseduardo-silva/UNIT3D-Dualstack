# Recuperação da lease Rust — 09/10/2026

O cenário que encerrava o Rust após três segundos de espera na renovação passou
a completar a persistência e continuar atendendo. A mudança mantém o fence SQL
por geração e os limites existentes de cada operação; não altera schema, PHP,
contabilidade ou durabilidade do MySQL.

## Comportamento implementado

- `repos/UNIT3D-Announce/src/dualstack/runtime.rs:34` coordena renovação e
  persistência sequencialmente. A renovação acontece entre operações, com
  cadência normal de cinco segundos, sem disputar o lock do próprio lote.
- `runtime.rs:17` supervisiona a operação em andamento. O vencimento da
  validade local de entrada (dez segundos) ou uma parada fecha a admissão,
  mas não descarta a operação por encerrar outro ramo concorrente.
- Falhas transitórias de persistência e renovação preservam a fila. Antes de
  reentregar, o runtime confirma a **mesma** lease (`runtime.rs:57`). O UPDATE
  exclusivo também espera qualquer transação anterior que ainda mantenha o
  fence compartilhado. As versões persistidas continuam impedindo crédito
  duplicado no replay.
- A entrada reabre apenas depois da confirmação e da drenagem (`runtime.rs:72`).
  Pausa temporária e encerramento definitivo são estados diferentes;
  `coordinator.rs:195` e o mutex do estado impedem que recuperação desfaça uma
  parada solicitada.
- O orçamento de recuperação é de 120 segundos, verificado entre operações
  que mantêm seus próprios limites. Perda/expiração confirmada da propriedade
  não provoca aquisição de outra geração. O erro final registra geração e
  quantidade de transições não confirmadas (`coordinator.rs:373`).

O SQL de `persistence.rs`, incluindo `FOR SHARE`, não foi modificado. O novo
runtime usa uma tentativa de lote por vez (`coordinator.rs:341`) para permitir
renovação entre retries. A API de `flush()` existente permanece disponível para
os consumidores/testes anteriores.

**Limite preservado:** o journal ainda é volátil. Crash, perda definitiva de
propriedade ou erro terminal podem impedir persistência. O processo antigo
não transfere silenciosamente sua fila para outra geração nem escreve após
um novo proprietário assumir. A correção cobre a recuperação segura de falhas
transitórias; não acrescenta um journal durável.

## Validação funcional

Execução na cópia `/opt/unit3d-dualstack/experiments/lease-recovery`, com o banco
`unit3d_dualstack_recovery_test`, VMs 120–122. Produtos/containers originais e
os dados da v2 foram preservados. Nenhuma configuração global do banco mudou.

Binário candidato:
`25a9860c6caad0d78e2c3f8073f6ecd6822c05cbcd1b45773d0994a7df6d6833`.
O manifesto conferiu os hashes normalizados de 77 arquivos de código, testes
e Cargo contra o workspace. O binário anterior continua com SHA-256
`8b825a1afb418f237803d5306abb0b57c2340ecb4b9f5871bc61dd290f3e4ace`.

Os 25 testes rápidos passaram. O contrato compartilhado foi executado depois
com `--include-ignored`: cinco testes, incluindo 12 casos/51 operações.
A suíte MySQL passou em 66,10 segundos, exercitando contabilidade, reentrega,
restart, respostas, endpoints, retenção, deadlock real, concorrência e os
cenários abaixo. O teste de escala do bootstrap continua separado e ignorado
nesta rodada. O único aviso de compilação é a depreciação preexistente de
`fetch_update` em `src/stats.rs:226`.

| Cenário real no MySQL | Resultado |
|---|---|
| Usuário bloqueado por 9 s | Processo continua, fila drena, crédito exato |
| Usuário bloqueado por 12 s | Entrada pausa; retry após timeout de lock; crédito exato e reabertura |
| Parada durante bloqueio de 9 s | Operação aguardada, fila drenada, lease liberada, entrada permanece fechada |
| Renovação bloqueada por mais de 3 s | Processo preserva a fila e drena depois do desbloqueio |
| Expiração simulada e aquisição por outro coordenador | Geração antiga não renova, não reabre e não persiste; nova geração confirma crédito uma vez |
| Commit confirmado seguido de reentrega | Nenhum crédito reaplicado |
| 100 lotes de uma transição | Drenagem em menos de 3 s, sem impor espera de 100 ms por lote cheio |
| Erro permanente de constraint | Entrada fechada, sem retry automático de erro permanente |

No HTTP, `recovery-block9-v2` repetiu o bloqueio de nove segundos a 20 requests/s:
**220 aceitos, zero erros, 220 versões e crédito 11.000 confirmado em peers,
histórico e usuários**. O processo terminou normalmente quando solicitado.
O observador capturou 36 amostras da espera em `users` e nenhuma espera da
renovação em `tracker_ownership`. Os logs registraram pausa com 176 transições
pendentes às 14:31:31,507Z e reabertura após drenagem às 14:31:31,519Z.

Antes da correção, o mesmo bloqueio no mesmo binário-base terminava com 142
aceitos não persistidos e exit 1; ver `dualstack-lease-io.md`. As cardinalidades
diferem porque a execução anterior terminava antecipadamente.

## Ajustes do laboratório durante a validação

O primeiro teste de transferência expirava a lease em apenas `agora - 1 s`.
Uma renovação iniciada antes desse instante ainda podia satisfazer o predicado;
o próximo proprietário recebeu `Owned`. O MySQL fixa funções como
`UTC_TIMESTAMP()` no início da consulta, inclusive antes da espera do lock.
[Referência oficial MySQL 8.0](https://dev.mysql.com/doc/refman/8.0/en/date-and-time-functions.html).
A fixture passou a usar um instante anterior a todas as consultas pendentes;
a nova geração é adquirida pelo próprio produto. O SQL de lease não mudou.

A segunda execução passou na suíte, mas o shell falhou ao terminar porque seu
arquivo havia sido atualizado enquanto o comando Docker executava. A execução
final foi repetida sem alterar arquivos em uso e saiu com código zero. Os logs
das duas tentativas foram preservados em `mysql-first.txt` e `mysql-second.txt`.

A primeira inicialização HTTP falhou antes de executar o binário: faltava o
mountpoint `.env` dentro da cópia montada como somente leitura. A preparação
passou a criar um arquivo vazio antes do bind mount da configuração privada.
`recovery-block9-v1-lifecycle.jsonl` preserva a tentativa; a v2 passou. Não houve
tráfego aceito nem alteração no produto decorrente desse ajuste de montagem.

## Carga curta e encerramento

Comparação com `load-4000-v1` e `load-8000-v1` de `results/lease-probe`, usando
os mesmos recursos, parâmetros e gerador. Trata-se de uma rodada por perfil,
sem aquecimento dedicado; não substitui a campanha formal original/candidato.

| Métrica | 4.000/s por 30 s | 8.000/s por 180 s |
|---|---:|---:|
| Aceitos / erros | 120.000 / 0 | 1.440.000 / 0 |
| Versões pendentes / divergências individuais | 0 / 0 | 0 / 0 |
| Crédito em cada conjunto contábil | 6.003.200 | 72.000.000 |
| Resposta p95 / p99 | 0,474 / 0,581 ms | 0,378 / 0,606 ms |
| Variação p95 / p99 ante a medição anterior | +6,73% / +7,58% | +4,93% / +2,74% |
| Throughput em intervalos de aproximadamente 10 s | 3.999,52–4.000,46/s | 7.990,26–8.009,73/s |
| Verificação final de drenagem | 0,062 s | 0,324 s |
| Escrita do disco da VM de dados | 16,37 MiB/s | 33,30 MiB/s |
| Peers / endpoints | 10.000 / 20.000 | 10.000 / 20.000 |

As medições curtas ficaram dentro da tolerância de latência de 10%, mantendo
a taxa programada e crédito integral. Não medem o throughput máximo. Nenhuma
espera de lock foi capturada nas amostras de um segundo das cargas naturais;
isso não exclui esperas menores que a resolução de coleta.

O container candidato foi encerrado normalmente e removido. A auditoria final
confirmou lease liberada, zero conexões ou locks pendentes no banco candidato,
um endpoint por família e nenhum tamanho de IP inválido. O arquivador continuou
ativo. Banco/cópia de diagnóstico permanecem no laboratório.

O banco da v2 conserva 69.060.362 versões, crédito 3.424.366.900, 10.000 peers,
20.000 endpoints e geração 1.951 expirada. O container original ainda tem exit
1 e término às 07:22:06Z. O banco da verificação anterior também permaneceu
inalterado. A causa física da pausa histórica continua sem atribuição conclusiva.

## Evidências e reprodução

Plano: `docs/plans/2026-10-09-recuperacao-lease.md`.
Commit Rust: `36823b5fab72940c0dcb90b0ed456b28c18160cc` (local, sem push).
Resultados: `lab/dualstack/results/lease-recovery/`.
`prepare-lease-recovery.py` cria cópia e banco exclusivos. O modo `restore`
recria **somente esse banco**, exigindo lease inativa e ausência de conexões.
`run-lease-recovery-tests.sh` executa os gates `unit`, `contract`, `mysql`, `build`.
`run-lease-probe.ps1 -Recovery` usa o candidato e o banco separado; os modos
anteriores continuam disponíveis. `analyze-lease-probe.py --directory lease-recovery`
consolida as séries públicas. Credenciais, passkeys e fixtures privadas continuam
somente no laboratório. Nenhuma execução de seis horas foi iniciada.

Após a interrupção por limite de uso, a conferência final confirmou os 77
arquivos de código/lockfiles do manifesto, os 30 checks da suíte MySQL e as
três execuções HTTP. `validation.json` registra os gates e `manifest.json`
preserva os hashes das evidências. Uma consulta posterior ao laboratório
confirmou 1.440.000 versões, crédito 72.000.000, 20.000 endpoints válidos,
lease inativa e zero conexões ou esperas pendentes no banco candidato.
O container candidato já estava removido; os testes concluídos não foram
repetidos na retomada. A validação curta da correção está concluída.
