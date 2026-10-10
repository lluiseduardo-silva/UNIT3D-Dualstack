# Problemas, correções e atribuição

Separar origem do defeito de ocasião da descoberta. As versões originais usadas como baseline não receberam correções silenciosamente. Os testes e falhas anteriores permanecem no [acervo](../lab/dualstack/results/).

## Preexistentes confirmados

| Caso | Evidência | Correção incluída | Limite |
|---|---|---|---|
| Consumo `LRANGE` / remoção `LTRIM` de itens não lidos | Teste concorrente dos dois consumidores legados | Remover a quantidade lida; [teste](../repos/UNIT3D/tests/Integration/LegacyBatchQueueTest.php) | Não cria journal durável no legado |
| Reembolso multi-torrent do mesmo usuário | Histórico 2.000, saldo 10.000→9.000 em vez de 8.000 | Agregação por usuário e locks ordenados; [serviço](../repos/UNIT3D/app/Services/DownloadRefund.php), [teste](../repos/UNIT3D/tests/Integration/DownloadRefundContentionTest.php) | Não repara automaticamente saldos históricos incorretos |
| Estatísticas incompatíveis com `ONLY_FULL_GROUP_BY` | Erro MySQL 1055 no código idêntico à tag | Remover coluna não usada no agrupamento; [regressão](../repos/UNIT3D/tests/Integration/DualstackSiteConsumersTest.php) | Reprodução do componente, não nova instalação integral da tag |
| IPv4 mapeado publicado em `peers6` no original | Listener `::`, renovação no baseline prolongado | Normalização no [peer Rust](../repos/UNIT3D-Announce/src/dualstack/peer.rs) | Não foi demonstrada falha de transferência causada por esse comportamento |

Os três primeiros casos pertencem ao UNIT3D PHP, não a ganhos de CPU do Rust. Detalhes, blobs e logs em [preexistentes](dualstack-problemas-preexistentes.md) e [concorrência de reembolso](dualstack-reembolso-concorrencia.md).

## Interação entre consulta legada e novos gravadores

O controle BON com consulta legada apresentou 22 deadlocks; a consulta que também lia endpoints, 27. Ambos usavam novos gravadores dual-stack. Correção: separar leitura agregada/escrita de saldos, ordenar usuários e manter transação/retry/fórmula. Os controles corrigidos tiveram crédito exato e zero novos deadlocks/timeouts. Isso comprova a interação ensaiada, não a mesma incidência de toda a tag original. [Relatório](dualstack-contadores.md).

## Introduzidos na implementação dual-stack

| Caso | Diagnóstico | Solução e prova |
|---|---|---|
| Seleção cara em torrents densos | Perfil de seleção e controles sem lista | Índice/seleção revisados; [benchmarks](dualstack-benchmarks.md), [densidade](dualstack-densidade.md) |
| Bootstrap com plano SQL inadequado | Consultas correlacionadas e operação que continuava no servidor após cancelamento local | Agregação por identidade, joins e encerramento da conexão da consulta; [18 boots](dualstack-bootstrap.md) |
| Cadência limitando persistência | Lote 200 a cada 100 ms ≈2.000 confirmações/s | Drenagem de lotes cheios, lote configurável e endpoints seletivos; [escritor](dualstack-writer.md) |
| Timeout da lease e saída com fila em memória | Persistência segura lock S da propriedade enquanto espera usuário; renovação pede X | Runtime coordena operações e recupera mesma geração; [reprodução](dualstack-lease-io.md), [correção](dualstack-recuperacao-lease.md) |
| Integração da origem atrás de proxy | Middleware de confiança não integrado ao caminho efetivo | Ajuste e matriz de rede/HTTPS; [TLS](dualstack-tls-memoria.md) |

A cadeia da lease foi reproduzida a 20 req/s com lock de 9 s; 142 transições/7.100 bytes aceitos ficaram sem persistir antes da correção. Não houve saturação de disco nesse controle. A correção passou com locks de 9/12 s, parada durante bloqueio, reentrega após commit e nova geração. A causa física da pausa histórica do soak v2 permanece indeterminada.

## Custo identificado no candidato, sem atribuição exclusiva à feature

O A1/B/A2 isolou o efeito de desativar o cache em oito consultas dinâmicas do candidato. B reduziu memória e aumentou CPU, mas permanece experimental e não incorporado. Esse controle não incluiu a tag original: não demonstra que todo o mecanismo de retenção ou todo o consumo observado surgiu com dual-stack. A comparação estabelece o benefício e o custo da intervenção naquele candidato, não a ausência do mesmo padrão no legado. Ver [capacidade](dualstack-capacidade-recursos.md).

## Laboratório e instrumentos

| Caso | Classificação e tratamento |
|---|---|
| Bind IPv6 por nome de interface no libtorrent | Falha antes de conectar; tracker entregava endpoint correto; configuração do harness ajustada e caso negativo repetido |
| Captura sem últimos announces | Buffer do tcpdump; modo imediato e nova captura |
| Inventário de binlogs em rotação | Corrida do observador; coleta/retry corrigidos e calibração repetida |
| Disco cheio durante ensaio intermediário | Resultado excluído dos totais válidos; evidência preservada e armazenamento preparado |
| Mountpoint `.env` ausente | Falha de inicialização antes de tráfego; arquivo vazio de bind preparado |
| Defasagem dos observadores | Falsa tendência de fila; alinhamento temporal e resolução de detecção testados |
| Expectativa de IPv4 em quatro bytes no original | Auditor passou a aceitar representação mapeada somente no original, sem modificar produto |
| `os.O_DIRECTORY` indisponível no Windows | Limite do teste de durabilidade do coletor; validado no alvo Linux sem reduzir garantia |

Não atribuir essas falhas ao produto original nem ocultá-las como execuções aprovadas. Os relatórios de [clientes](dualstack-clientes-reais.md), [armazenamento](dualstack-armazenamento.md), [soak](dualstack-prolongado.md), [baseline](dualstack-rust-original.md) e [capacidade](dualstack-capacidade-recursos.md) preservam os diagnósticos.
