# Campanha prolongada Rust — preparação e operação

**Atualização em 09/10/2026:** `soak-rust-six-hours-v3` concluiu seis horas,
com 171.427.236 announces aceitos, zero erros, drenagem e auditorias aprovadas.
O resultado e seus limites estão em [captura prolongada v3](dualstack-prolongado-v3.md)
e no checkpoint. Aprovação limitada ao perfil Rust; acompanhamento desativado.
O conteúdo abaixo preserva o histórico e o perfil das execuções v1/v2.

Execução autorizada em 08/10/2026. Os preparativos alteram exclusivamente o
laboratório; fontes PHP/Rust e geradores dos benchmarks históricos permanecem
iguais. O resultado das seis horas deve ser registrado depois do encerramento:
início confirmado não significa aprovação da campanha.

**Estado do checkpoint:** campanha `soak-rust-six-hours-v2` **interrompida**.
Início da carga em **09/10/2026 às 01:56:44 de Brasília**; Rust encerrado às
**04:22:06**, após timeout na renovação da propriedade do swarm. O supervisor
terminou às **04:22:19**. A auditoria encontrou 68.064 atualizações aceitas ainda
não persistidas; a drenagem falhou. O diagnóstico completo está no final deste
documento. O teste não foi reiniciado e o acompanhamento está pausado.
As seis horas não foram concluídas nem aprovadas. O checkpoint da correção do
inventário é `3d40f05`; a preparação original é `4d99ed9`.

A campanha v1 foi interrompida por falha do observador após aproximadamente
1h56. Suas evidências e o diagnóstico permanecem abaixo e em `previous_runs`
no checkpoint. A v2 começa uma duração completa de seis horas, depois da
correção e de um novo ensaio de cinco minutos aprovado.

Confirmação inicial da v2: 637.947 announces aceitos em aproximadamente 80 s,
zero erros e fila do coletor vazia. A primeira janela completou 480.000 requests,
7.999,92/s, resposta p95 de 0,3508 ms e p99 de 0,4593 ms. A auditoria/drenagem
permitiu avançar à janela seguinte. Os três observadores estão saudáveis e o
arquivador permanece ativo. Snapshots em `results/soak/six-hours-v2-start-*`.
Essas medidas confirmam o início, sem antecipar a aprovação final.

## Perfil da campanha

| Parâmetro | Valor |
|---|---|
| Plano | `lab/dualstack/plans/soak-rust-six-hours-v2.json` |
| Backend | UNIT3D-Announce candidato, commit `9e8b54626334db11940e3ebf939cbf40ba4426a3` |
| UNIT3D/schema | `7c45115fc8b7ad83d12b0a44a5e656c12240ede4` |
| População | 10.000 peers, 20.000 endpoints, 250 usuários |
| Distribuição | 40 torrents com 250 peers cada; 80% seeders |
| Duração | 21.600 segundos, além do encerramento/drenagem |
| Carga principal | 8.000 requests/s em janelas de até 60 segundos |
| Batch / TTL | 500 transições / 7.200 segundos |
| Rede | HTTP direto, IPv4/IPv6 de origem real, conexões persistentes |
| Resposta | `numwant=10`: dez peers e ambos os endpoints de cada um |
| Durabilidade | MySQL ROW/FULL, `sync_binlog=1`, `innodb_flush_log_at_trx_commit=1` |
| Arquivo | ZFS via VirtioFS; binlogs fechados a até 32 MiB/s |

O SHA-256 do binário de produto é
`8b825a1afb418f237803d5306abb0b57c2340ecb4b9f5871bc61dd290f3e4ace`.
O fingerprint dos fontes, normalizados para LF e incluindo testes/lockfile, é
`a0b448b667f756318200f17fda3e4fc6f2c3b75528c24a9ec9c0dfab80174659`;
os manifestos local e remoto estão em `results/soak/rust-source-*.json`.

Este é um ensaio de estabilidade do candidato. Não substitui a comparação
formal original/candidato, nem a campanha PHP standalone. TLS/proxy e
conectividade foram tratados na etapa anterior; as checagens de conexão estão
desligadas neste perfil de capacidade. A taxa de 8 mil/s é oferecida nas janelas;
há pausas entre elas para manutenção e auditoria, portanto a média das seis
horas será menor. Não é uma prova de carga ininterrupta sem pausas.

## Coleta e verificações

`soak-load.py` renova também os leechers, para a população não desaparecer após
duas horas. As duas famílias compartilham os mesmos contadores cumulativos;
o gerador confere upload do peer, histórico e usuário individualmente depois
da drenagem de cada janela. Confere também versões, contadores únicos/por
família, tamanho e pareamento das respostas, seedtime, ausência de duplicação
de conclusão, BON inalterado e erros/locks do banco.

Três peers de controle exercitam rotação IPv6, parada/reinício da sessão e
expiração independente do IPv6. Os demais continuam sob carga. A rotação usa
32 endereços reservados e fecha a conexão antiga. Depois de duas horas, o
controle de expiração precisa continuar com IPv4 e recuperar IPv6. O teste de
cinco minutos não cobre o TTL real; o smoke de TTL 60 s cobre a mecânica.

`soak_metrics.py` usa histogramas com erro de quantização de até 0,1% + 1 µs,
registrando resposta HTTP (`received-began`), tempo em fila (`began-scheduled`),
execução incluindo validação (`ended-began`) e total desde o agendamento
(`ended-scheduled`). Nenhuma lista de amostras cresce em RAM. Cada amostra
binária tem 51 bytes; blocos de mil registros seguem por uma fila de no máximo
16 blocos até um escritor dedicado. Fila cheia ou falha do escritor interrompe
o teste; não descarta amostras silenciosamente. O heartbeat grava fora do loop
HTTP. Gzip em segmentos por janela, hash, fsync e manifesto ficam no ZFS.

`verify-soak-samples.py` confere SHA-256, CRC gzip, tamanho descomprimido e
cardinalidade usando leitura limitada em memória. Amostras completas e binlogs
permanecem privados no ZFS. `collect-soak.ps1` exporta somente JSON/JSONL seguros,
sem passkeys, identidades, ambientes privados ou binlogs.

## Gates curtos e problemas resolvidos

| Gate | Evidência / resultado |
|---|---|
| Quatro testes automatizados | Histograma, segmentos, falha do escritor e limites dos guards passaram |
| Coletor por 100 s a 20 mil registros/s | 2 milhões; RSS de 18.944 para 20.004 KiB; fila máxima de dois blocos |
| Falha real do observador | `soak-guard-v1`: supervisor detectou heartbeat parado, encerrou carga/tracker e retirou aliases |
| Funcional acelerado | `soak-smoke-v3`: 153.222 announces, 30 janelas, crédito exato, expiração/restauração exercitadas, zero erros |
| Integridade do smoke | 30 segmentos, SHA/CRC/cardinalidade aprovados |
| Impacto da cópia, versão final | `soak-copy-comparison-v2`: 1.224.036 announces, 20.000 endpoints, crédito exato de 60.000.000, zero erros |
| Ensaio representativo de cinco minutos | `soak-rehearsal-v1`: 2.389.580 announces, cinco janelas, crédito exato de 118.477.300, zero erros; supervisor e encerramento aprovados |
| Integridade do ensaio representativo | Todas as 2.389.580 amostras passaram por SHA-256/CRC/cardinalidade |

No ensaio de cinco minutos, o coletor teve RSS máximo de 62.336 KiB e fila
máxima de dois blocos. A contagem de binlogs arquivados passou de 26 para 28
durante a execução: mais 2.147.736.060 bytes confirmados e purgados pelo MySQL.
Ao terminar, não havia binlog fechado pendente; ficaram 24,64 GiB livres no
SSD de dados e 296,06 GiB no arquivo ZFS. O TTL real ainda será exercitado
durante as seis horas.

O ensaio inicial do coletor sem limite de taxa excedeu a fila e foi interrompido
como previsto. O smoke v1 passou funcionalmente, mas o supervisor interpretou
uma unidade systemd transitória já removida como erro no encerramento. A parada
agora aceita unidade ausente/inativa. No smoke v2, TTL de 15 s era menor que a
preparação do dataset; endpoints expiravam antes da carga. O perfil acelerado
foi corrigido para 60 s, sem alterar o TTL de produto de 7.200 s. As evidências
dessas falhas permanecem no repositório.

Comparação final: três pares alternados de 25 s, sem/com cópia de um binlog
fechado de 1 GiB, usando o algoritmo de arquivo real a 32 MiB/s. O timer
automático foi pausado em ambos os braços, apenas nesse ensaio curto, para
isolar a variável; o supervisor o restaura ao terminar. A cópia é contínua na
janela, conservadora frente ao ciclo intermitente do arquivador. O ensaio de
cinco minutos usa o timer automático normal, incluindo purga.

| Mediana | Sem cópia | Com cópia | Variação |
|---|---:|---:|---:|
| Resposta p95 | 0,3586 ms | 0,3652 ms | +1,82% |
| Resposta p99 | 0,4621 ms | 0,4853 ms | +5,03% |
| Throughput | 7.999,92/s | 7.999,84/s | -0,001% |

Os gates de resposta e throughput passaram. A fila do gerador variou:
p99 entre 3,20 e 14,50 ms sem cópia, e entre 5,56 e 7,42 ms com cópia. Esses
valores estão nos dados brutos, separados da resposta HTTP; não se atribui
causalidade à cópia a partir dessa oscilação. A versão anterior também passou,
mas ainda gravava heartbeat sincronamente no loop HTTP; a repetição final
validou a retirada desse I/O do caminho medido.

## Supervisão e parada

`soak-supervisor.py` roda como serviço systemd no Proxmox, com exclusão global.
Usa o guest agent das VMs; nenhuma chave SSH foi distribuída. Observadores
medem espaço, RSS/PSS/CPU, saúde dos serviços e persistência a cada cinco
segundos. A idade dos heartbeats é medida por relógio monotônico do supervisor.
O teste continua se o SSH ou o Codex se desconectar.

Paradas conservadoras: SSD dados <8 GiB, outros SSDs <1 GiB, ZFS <20 GiB,
thin pool <8 GiB, RAM disponível <512 MiB, heartbeat parado por 30 s,
arquivador sem atualização por 240 s, mais de 4 GiB fechados pendentes,
erro HTTP/contábil ou serviço perdido. A diferença observada de versões
precisa exceder 80 mil por 30 s para parar; metade desconta a defasagem de até
cinco segundos da coleta SQL a 8 mil/s. Auditorias entre janelas exigem drenar
em 30 s. Abaixo de 16 GiB físicos no thin pool, o supervisor pode executar
`fstrim /` somente na VM 121, no máximo uma vez a cada 300 s.

O encerramento interrompe o gerador, drena o Rust e remove somente os aliases
criados para o teste. MySQL, Redis, VirtioFS, dados e arquivador permanecem.
Falha de energia do host ainda pode perder a janela não persistida; fsync dos
segmentos não substitui a durabilidade dos requests ainda em memória.

## Comandos e evidências

Início pelo Windows, com uma chave já autorizada indicada pelo operador:

```powershell
./lab/dualstack/start-soak.ps1 `
  -PlanFile ./lab/dualstack/plans/soak-rust-six-hours-v2.json `
  -IdentityFile <chave-ssh-do-laboratorio>
```

Não executar novamente com o mesmo nome, nem enquanto houver um tracker ativo.
O início recria somente o schema isolado `unit3d_dualstack_journal_test`.

No Proxmox:

```sh
cat /storage_pool/unit3d-dualstack/supervisor/soak-rust-six-hours-v2/status.json
systemctl status unit3d-soak-supervisor-soak-rust-six-hours-v2.service
# Parada antecipada, com drenagem:
systemctl stop unit3d-soak-supervisor-soak-rust-six-hours-v2.service
# Após o encerramento:
python3 /root/unit3d-soak/verify-soak-samples.py soak-rust-six-hours-v2
```

Coleta resumida no Windows: `collect-soak.ps1 -Name soak-rust-six-hours-v2
-IdentityFile <chave-ssh-do-laboratorio>`. As amostras completas estão em
`/storage_pool/unit3d-dualstack/clients/results/soak/soak-rust-six-hours-v2/samples`.
O resultado definitivo deve combinar `final.json`, status do supervisor,
verificação dos segmentos e séries de memória, backlog e arquivo. Não inferir
aprovação a partir de um serviço simplesmente encerrado.

Foi configurado acompanhamento nesta conversa a cada 15 minutos, ID
`acompanhar-ensaio-dualstack-de-seis-horas`, com aviso somente por mudança
relevante, falha ou conclusão. Foi pausado após a interrupção da v1 e reativado
em 09/10 para acompanhar exclusivamente a v2. Após a falha e a coleta da v2,
foi pausado novamente, sem reiniciar nem alterar o teste.
A execução
e as proteções residem no Proxmox. O acompanhamento pelo Codex depende de o
computador e o aplicativo permanecerem ligados, conforme a
[documentação oficial OpenAI](https://learn.chatgpt.com/docs/automations?surface=app).

## Revisão do checkpoint contra o plano

Revisão final única: o diff acrescenta coletor, gerador, observadores,
supervisor, instalador, planos, coleta/análise e evidências previstos. Não há
diff nos dois produtos nem nos geradores históricos. Os ajustes de encerramento
idempotente, TTL do smoke e I/O do heartbeat resolvem falhas da preparação
documentadas acima. Nenhuma ampliação funcional de escopo foi necessária.

## Resultado interrompido e diagnóstico — 09/10/2026

Às 01:28:15 de Brasília, o observador da VM de dados encerrou com
`RuntimeError: rotation_during_inventory_retry_later`. O stack trace está em
`results/soak/six-hours-observer-failure.txt`. O supervisor detectou o heartbeat
parado, registrou `observer_stale_data`, interrompeu o gerador, drenou o Rust e
retirou os aliases. O banco e o arquivador continuam disponíveis.

**Causa confirmada no coletor da revisão `7ee71f4`:** `archive-binlogs.py:112` obtém a lista de
binlogs e o nome do ativo em duas consultas separadas. Uma rotação entre
`SHOW BINARY LOGS` e `SHOW MASTER STATUS` faz a comparação de segurança em
`archive-binlogs.py:117` rejeitar aquele inventário. O observador chama essa
função em `soak-observer.py:65` e propaga a exceção em `:90`, sem nova tentativa.
O supervisor então aplica corretamente seu limite de 30 s sem heartbeat em
`soak-supervisor.py:107`. Não houve falha de announce Rust que disparasse a
interrupção.

Naquela revisão, `reproduce-inventory-race.py` executa as mesmas funções do arquivador com
respostas simuladas para uma rotação entre consultas. Reproduz exatamente a
exceção; uma nova leitura estável passa. Não faz I/O no laboratório e não
altera o código em execução. Evidência: `six-hours-inventory-race.json`.

| Verificação após a drenagem | Resultado |
|---|---:|
| Duração do gerador, incluindo encerramento | 6.967,16 s |
| Announces aceitos / amostras verificadas | 55.270.470 / 55.270.470 |
| Segmentos com SHA-256, CRC e cardinalidade corretos | 115 |
| Erros HTTP/validação de respostas | 0 |
| Janelas completas de 60 s | 114 |
| Throughput mínimo das janelas completas | 7.998,93 requests/s |
| Mediana do throughput das janelas | 7.999,95 requests/s |
| Mediana dos p95 / p99 de resposta por janela | 0,3463 / 0,4507 ms |
| Crédito em peers, histórico e usuários | 2.740.483.300 em cada conjunto |
| Divergências peer/histórico e usuário/crédito | 0 |
| Soma de versões persistidas | 55.270.470 |
| Peers / endpoints / usuários | 10.000 / 20.000 / 250 |
| Seeders / leechers únicos | 8.000 / 2.000 |
| Conclusões duplicadas / BON adicional | 0 / 0 |
| Deadlocks / timeouts de lock / failed jobs | 0 / 0 / 0 |
| RSS Rust máximo / última amostra | 88,28 / 31,83 MiB |
| RSS máximo do gerador | 63,65 MiB |
| Menor espaço livre SSD dados / thin pool | 23,64 / 33,13 GiB |
| Maior idade do arquivo / backlog fechado | 52,79 s / aproximadamente 1 GiB |

A última janela foi cortada pelo supervisor após 11,21 s e 89.665 requests.
Seu campo `completed_rps=1494,42` usa o denominador planejado de 60 s
(`soak-load.py:272`); não é uma queda espontânea de throughput. O resumo bruto
conserva esse número e `six-hours-stop-analysis.json` separa as 114 janelas
completas. Os percentis apresentados são medianas dos percentis das janelas,
não percentis globais dos 55 milhões de requests.

A diferença observada de 226.484 versões no último snapshot usava a última
amostra SQL do observador já encerrado. Não demonstra backlog real daquele
tamanho. A auditoria final somente leitura confirmou todas as 55.270.470
transições persistidas, crédito exato e propriedade liberada (`live=0`).
O Rust já não está em execução e os aliases foram removidos.

O arquivador estava saudável antes da falha e permaneceu saudável depois dela.
Após o encerramento, havia 74 binlogs arquivados, nenhum fechado pendente,
24,76 GiB livres no SSD de dados e 289,68 GiB no arquivo. MySQL permaneceu com
ROW/FULL, `sync_binlog=1` e `innodb_flush_log_at_trx_commit=1`. As verificações
finais estão em `six-hours-final-accounting.json`, `six-hours-samples-check.json`,
`six-hours-summary.json` e `archive-after-six-hours-stop.json`; as amostras e
binlogs completos continuam privados no ZFS.

**Limites e próximo passo:** a campanha parou antes do TTL de 7.200 s, portanto
expiração/restauração real do IPv6 e estabilidade por seis horas não foram
validadas. A correção indicada é repetir somente o inventário que falhou por
rotação, com tentativas, atraso e orçamento total limitados; preservar a
checagem do arquivo ativo e continuar falhando para erros reais de banco,
montagem, integridade ou falta persistente de atualização. Validar rotação
concorrente e esgotamento do retry antes de uma nova campanha com outro nome.
Na conclusão do diagnóstico da v1, esse ajuste ainda não havia sido aplicado.
O escopo permanece no laboratório, sem mudar o announce ou a contabilidade.
A autorização e a execução da correção estão registradas abaixo; não houve
aprovação de PHP ou do comparativo original/candidato.

## Correção autorizada e preparação da execução v2 — 09/10/2026

A correção modifica somente o inventário compartilhado pelo arquivador e pelo
observador. `archive-binlogs.py:112` relê a lista e o arquivo ativo quando os
dois discordam. São no máximo três tentativas, com pausas de 100 e 200 ms e
orçamento total de cinco segundos. Cada subprocesso MySQL recebe o tempo ainda
disponível. Timeout, falha SQL, inventário vazio/inválido ou ausência do ativo
continuam sendo erros, sem retry genérico. A resposta só é publicada quando
lista e ativo correspondem. As regras de hash, fsync, purga e o limite do
supervisor permanecem iguais.

Validação da correção:

- 15 testes automatizados passaram, incluindo recuperação, três rotações
  consecutivas, orçamento consumido por consultas/pausas, timeout e rejeição
  de erros SQL, formato inválido e ausência do arquivo ativo.
- `test-inventory-rotation.py` forçou 23 rotações **reais** no MySQL: vinte
  casos de recuperação após uma rotação e um caso de falha após três rotações
  consecutivas. A execução mais lenta levou 0,982 s. A leitura estável posterior
  funcionou e os agregados de peers, histórico, usuários e endpoints ficaram
  iguais aos anteriores.
- `reproduce-inventory-race.py` agora verifica que a sequência do incidente
  se recupera dentro da mesma chamada. A evidência original da falha v1 foi
  preservada.
- `update-archive-module.py` aguardou o serviço terminar, guardou o módulo
  anterior e instalou a nova versão por troca atômica. Drenou os arquivos
  fechados de teste usando o arquivador com verificação normal, atualizou o
  estado do serviço e reativou o timer. Nenhuma configuração MySQL mudou.

SHA-256 do módulo instalado:
`2ba8220183490679cb6843fe7930153fc801d784e054e47ec923e740caaddb9e`.
As evidências estão em `results/soak/inventory-retry-*`. O binário Rust continua
com o hash registrado no perfil. O ensaio `soak-rehearsal-v2` passou usando os
mesmos parâmetros de cinco minutos. As duas campanhas têm diretórios distintos
da v1, cujas evidências foram preservadas.

| Gate da correção | Resultado |
|---|---:|
| Announces aceitos / erros | 2.389.031 / 0 |
| Janelas / throughput mínimo e mediano | 5 / 7.999,92 e 7.999,95 requests/s |
| Mediana dos p95 / p99 de resposta por janela | 0,3244 / 0,4321 ms |
| Crédito em peers, histórico e usuários | 118.449.800 em cada conjunto |
| Versões persistidas | 2.389.031 |
| Peers / endpoints | 10.000 / 20.000 |
| Divergências contábeis / deadlocks / timeouts / failed jobs | 0 / 0 / 0 / 0 |
| Segmentos e amostras com SHA/CRC/cardinalidade aprovados | 5 / 2.389.031 |
| RSS máximo do Rust / gerador | 33,64 / 60,90 MiB |
| Fila máxima de amostras | 2 blocos |
| SSD dados / arquivo livres após encerramento | 23,97 / 289,49 GiB |

O supervisor confirmou `passed` depois da drenagem. A auditoria SQL somente
leitura confirmou crédito individual, versões, propriedade liberada e remoção
dos aliases. O arquivador continuou ativo, sem binlog fechado pendente no final;
as configurações de durabilidade permaneceram iguais. Resultados em
`rehearsal-summary-v2.json`, `rehearsal-final-accounting-v2.json`,
`rehearsal-samples-check-v2.json` e `archive-after-rehearsal-v2.json`.
Este gate não cobre o TTL de duas horas nem aprova a duração de seis horas.

A revisão única do diff contra `plans/2026-10-09-inventario-binlogs.md` não
encontrou divergência de escopo: retry limitado, testes com rotação real,
instalação atômica e ensaio curto; nenhum produto ou parâmetro de carga mudou.
Com os gates aprovados, foi iniciada `soak-rust-six-hours-v2`, por seis horas
completas. Início UTC: `2026-10-09T04:56:44Z`; fim previsto UTC:
`2026-10-09T10:56:44Z`. O acompanhamento de 15 minutos foi reativado para a v2.

## Interrupção da v2: timeout da lease e perda da fila em memória — 09/10/2026

**Causa imediata confirmada:** às `07:22:06.925Z` (04:22:06 de Brasília), o Rust
registrou `Coordenador dualstack: Tempo limite de renovacao da lease excedido`
e saiu com código 1, sem OOM. O gerador detectou uma resposta de erro/aviso
(`tracker_response`); o supervisor registrou `load_errors`. O container parado
foi preservado, assim como os dados e as amostras. Evidência:
`results/soak/six-hours-v2-rust-exit.json`.

O timeout de renovação é de três segundos em
`repos/UNIT3D-Announce/src/dualstack/persistence.rs:37`. A falha fecha a entrada
em `src/dualstack/coordinator.rs:199`. No `select!` de `:395`, o erro do
heartbeat retorna diretamente; `shutdown()` aparece no ramo de parada normal
em `:401`. Esse caminho explica por que o erro encerrou o processo com
transições ainda na memória. Não é a falha de rotação de inventário da v1.

O arquivador também excedeu seu orçamento de cinco segundos às `07:22:08Z`.
A primeira consulta consumiu quase todo o orçamento; `SHOW MASTER STATUS`
recebeu apenas 0,039 s restantes. Houve `binlog_inventory_timeout`, sem
divergência de nomes por rotação. O timer recuperou o serviço às `07:22:24Z`
por seu ciclo normal. Não foi necessário intervir. Ver
`six-hours-v2-archive-timeout.txt` e `archive-binlogs.py:112`.

**Indícios de I/O, com limite de atribuição:** os contadores acumulados do
MySQL registram espera máxima de 5,9184 s no arquivo de redo InnoDB, 5,0493 s
no temporário InnoDB e 4,1632 s em `SHOW BINARY LOGS`. As séries de um minuto
do Proxmox mostram aumento da pressão de I/O da VM 121 perto da interrupção,
sem saturação de CPU: uso em torno de 30% dos quatro vCPUs. Não houve restart
MySQL, OOM, deadlock ou timeout de lock registrado. São sinais compatíveis com
uma pausa de I/O, mas os máximos SQL são acumulados desde o início do servidor
e não localizam cada espera no instante do incidente. Não há evidência suficiente
para atribuir exclusivamente ao SSD físico, ao host ou à cópia para ZFS.
Fontes: `six-hours-v2-mysql-diagnostics.json` e `six-hours-v2-data-rrd.json`.

**A drenagem não passou.** O script de parada exige exit code zero antes de
remover o container (`lab/dualstack/benchmark-backend.sh:57`). O erro foi
capturado pelo supervisor, mas seu campo `reason` preserva a primeira causa
(`soak-supervisor.py:174`), portanto `load_errors` não comprova drenagem.
Os aliases foram removidos e a lease já está expirada; o Rust está parado.
As linhas `cleanup` referem-se aos serviços de carga/observação, não confirmam
a persistência integral do tracker.

| Verificação da v2 | Resultado |
|---|---:|
| Duração do gerador, incluindo encerramento | 8.724,16 s (aproximadamente 2h25) |
| Announces aceitos / erro de resposta | 69.128.426 / 1 |
| Segmentos e amostras com SHA-256/CRC/cardinalidade aprovados | 143 / 69.128.426 |
| Janelas completas / mínimo e mediana do throughput | 142 / 7.999,10 e 7.999,95 requests/s |
| Mediana dos p95 / p99 de resposta por janela | 0,2475 / 0,3322 ms |
| Requests principais na janela interrompida, sem resumo de latência | 395.401 |
| Crédito esperado das amostras aceitas | 3.427.770.100 bytes |
| Crédito persistido em peers, histórico e usuários | 3.424.366.900 bytes em cada conjunto |
| Crédito ainda não persistido | **3.403.200 bytes** |
| Versões persistidas / diferença para requests aceitos | 69.060.362 / **68.064** |
| Peers com diferença de crédito / usuários afetados | 7.997 / 200 |
| Peers / endpoints / violações do limite de dois endpoints | 10.000 / 20.000 / 0 |
| Seeders / leechers únicos | 8.000 / 2.000 |
| Expiração independente de IPv6 e restauração no TTL real | Confirmadas pelo gerador |
| BON adicional / conclusões duplicadas / seedtime fora do teto | 0 / 0 / 0 |
| Deadlocks / timeouts de lock / failed jobs | 0 / 0 / 0 |
| RSS máximo Rust / gerador | 114,06 / 64,45 MiB |
| Fila máxima do coletor | 2 blocos |
| SSD dados / arquivo livres após a interrupção | 24,36 / 281,48 GiB |

`audit-soak-samples.py` leu os registros privados no próprio laboratório,
com memória limitada, e comparou o maior contador aceito e o número de
announces de cada peer com o SQL. Exportou apenas agregados. A auditoria
admite zero ou uma versão extra no peer de expiração, como o gerador; não
confunde expiração com crédito duplicado. Os déficits por peer são de oito
a dez versões. A diferença agregada de 68.064 representa aproximadamente
8,51 segundos à taxa de 8 mil/s. A consistência entre as três tabelas persistidas
foi preservada; a contabilização de todos os announces respondidos não foi.
O campo `final.audit` contém a última janela completa, portanto não foi usado
como referência do crédito da janela interrompida.

As amostras binárias e binlogs permanecem no ZFS; nenhum foi exportado.
Há 156 binlogs arquivados e nenhum fechado pendente após a falha. O arquivo
e suas verificações continuam ativos. As séries completas, resumo e auditoria
estão em `results/soak/soak-rust-six-hours-v2`, `six-hours-v2-summary.json`,
`six-hours-v2-stop-analysis.json`, `six-hours-v2-samples-check.json` e
`six-hours-v2-final-accounting.json`. Os percentis excluem a janela interrompida;
não são percentis globais. O pico de memória e os 79.895 de diferença observada
de versões não demonstram sozinhos vazamento ou backlog integral, pois as
amostras SQL têm defasagem. A perda final foi medida diretamente.

**Próximo passo recomendado, ainda não executado:** tratar a recuperação e o
encerramento após timeout de renovação preservando a exclusão entre gerações;
parar novas entradas imediatamente e testar recuperação/drenagem com atraso
de I/O controlado, inclusive perda definitiva da propriedade. Aumentar apenas
o timeout do arquivador não resolve a saída do Rust nem a perda observada.
Acrescentar diagnóstico seguro da resposta rejeitada e registrar explicitamente
a falha de drenagem são complementos necessários do laboratório. Atribuir a
pausa ao armazenamento exige métricas de latência de disco com maior resolução
em um ensaio posterior. Nenhuma dessas alterações ou nova execução foi feita.
Não há aprovação das seis horas, do PHP ou da comparação original/candidato.

## Verificação posterior da hipótese — 09/10/2026

A verificação autorizada foi executada em outro banco e container, preservando
a v2. O bloqueio controlado confirmou a cadeia `users → persistência → lease`
e reproduziu o encerramento do mesmo binário com 142 transições não persistidas,
a apenas 20 requests/s. Os controles sem bloqueio e com bloqueio de um segundo
passaram. Uma carga natural de 8.000 requests/s por três minutos também passou:
1.440.000 aceitos, crédito integral e drenagem.

O mecanismo de falha do coordenador está confirmado; a atribuição da pausa
histórica ao SSD físico continua sem confirmação. Relatório, limitações da
instrumentação e próximo ajuste em [dualstack-lease-io.md](dualstack-lease-io.md).
O checkpoint específico é `lab/dualstack/checkpoint-lease-io.json`. Nenhuma
alteração no produto ou reinício do teste de seis horas foi realizado.
