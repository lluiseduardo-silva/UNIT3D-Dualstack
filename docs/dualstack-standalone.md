# Dualstack PHP standalone — checkpoint de desenvolvimento

Base: UNIT3D 9.2.0, branch `feat/dualstack`. Este fluxo não usa nem inicia o Rust.
O conjunto da feature ainda está em implementação; utilizar somente o laboratório.
O progresso e os critérios pendentes estão em
`docs/plans/2026-10-08-dualstack-execucao.md`.

## Configuração

| Configuração | Padrão | Efeito |
|---|---|---|
| `DUALSTACK_ENABLED` | `false` | Seleciona o novo fluxo HTTP PHP |
| `DUALSTACK_MAX_ENDPOINTS_PER_PEER` | `2` | Aceita 1 ou 2; não expulsa outra família para abrir uma vaga |
| `DUALSTACK_ENDPOINT_TTL` | `7200` | Validade independente de cada endpoint, em segundos |
| `DUALSTACK_INACTIVE_PEER_RETENTION` | `172800` | Retenção contábil; mínimo 7200 s |
| `DUALSTACK_MAX_PENDING_TRANSITIONS` | `100000` | Limite do journal; recusa ao atingir o teto |
| `DUALSTACK_MAX_CLEANUP_REQUESTS` | `1000` | Limite global de solicitações de limpeza pendentes |
| `DUALSTACK_ALLOW_PRIVATE_ADDRESSES` | `false` | Permite endereços privados no laboratório |
| `DUALSTACK_TRUSTED_PROXIES` | vazio | Lista de IPs/CIDRs separados por vírgula; `*` recusado |
| `DUALSTACK_REQUIRE_CONNECTIVITY` | `false` | Exige probe positivo para publicar um endpoint |
| `DUALSTACK_CONNECTIVITY_CACHE_ENTRIES` | `100000` | Limite do cache de provas TCP |
| `DUALSTACK_CONNECTIVITY_CACHE_TTL` | `1800` | Validade de um resultado de conectividade |
| `DUALSTACK_TRACE_TRANSITIONS` | `false` | Registra metadados de transições depois do commit, sem passkeys |
| `REDIS_ANNOUNCE_CONNECT_TIMEOUT` | `3` | Timeout de conexão Redis em segundos |
| `REDIS_ANNOUNCE_READ_TIMEOUT` | `3` | Timeout de leitura Redis em segundos |

`announce.rate_limit` continua controlando peers lógicos por usuário/torrent.
`announce.connectable_check` habilita os probes; `announce.connectable_check_interval`
controla sua frequência. Caso seja exigida conectividade positiva, habilitar e
executar o verificador. O cache usa `noeviction`; o laboratório também usa AOF.
Logs de HTTP/proxy/FPM devem excluir o caminho do announce, que contém a passkey.

## Processos

O coordenador `php artisan dualstack:work` é um serviço contínuo supervisionado,
fora do scheduler de cinco segundos. Existe um proprietário por instalação.
O serviço renova a lease SQL, mantém heartbeat Redis, persiste lotes e limpa
endpoints vencidos a cada 60 s. Sem heartbeat, o HTTP recusa novas transições.

Quando a checagem estiver habilitada, executar separadamente
`php artisan dualstack:probe`. O teste TCP tem timeout de 1 s e não bloqueia
o coordenador. Um resultado atrasado não pode alterar outro IP/porta/revisão.
TCP alcançável não equivale a uma transferência BitTorrent comprovada.

Encerrar o coordenador com SIGTERM: fecha a entrada, drena e libera a propriedade.
Usar `APP_ENV=local` no laboratório, ou a configuração efetiva do serviço em uma
futura implantação; `APP_ENV=testing` desativa os handlers de sinais do Laravel.
Na imagem derivada de FPM, definir `--stop-signal=SIGTERM` para o coordenador CLI.
O código de saída precisa ser zero; após falha, preservar o journal e recuperar
com uma nova geração antes de voltar a aceitar announces.

## Preparação do laboratório

Antes da ativação, fechar a entrada, drenar jobs/filas antigos, interromper
escritores legados, aplicar as migrações aditivas e executar o backfill offline.
O coordenador recusa filas legadas pendentes. Nunca habilitar dois backends sobre
estados independentes. As migrações mantêm as colunas de endereço legado.

A migração `2026_10_08_000003_add_dualstack_handoff_state.php` acrescenta o
marcador `php_journal_drained`. A aquisição PHP o reinicia; a liberação só o
confirma depois de fechar produtores e verificar journal e filas legadas vazios.
Também exige ausência de solicitações em `tracker_cleanup_requests`, acrescentada
pela migração `2026_10_08_000004_add_dualstack_cleanup_requests.php`. Aplicar essa
migração antes de iniciar o novo coordenador, com a entrada fechada e os processos
anteriores encerrados. Seu rollback preserva a tabela e os pedidos pendentes.
O Rust recusa a troca sem essa confirmação, mesmo se a lease PHP já expirou.
Depois de uma falha PHP, executar a recuperação/drenagem PHP antes de iniciar
Rust. Não forçar o marcador por SQL. A independência do modo standalone permanece.

No laboratório provisionado, `start-candidate-php.sh fresh` recria **somente**
`unit3d_dualstack_journal_test`, copiando fixtures sintéticas e zerando saldos.
O modo padrão `resume` preserva os dados existentes. O Rust permanece parado.
`stop-candidate-php.sh` retira a entrada antes de encerrar e drenar o coordenador.

Na VM de clientes, `prepare-client-rotation.sh` adiciona um IPv6 secundário à
interface privada validada. Executar `candidate-php.py` com os caminhos privados
da fixture e do arquivo de credenciais. O JSON de saída omite esses segredos.
`export-transition-trace.php` exporta somente campos permitidos das transições;
não copiar o log bruto da aplicação para os resultados versionados.

## Limpeza solicitada pelo usuário ou pela administração

Com dualstack standalone ativo, os botões registram uma solicitação durável no
MySQL. A resposta confirma o pedido; o encerramento dos endpoints é assíncrono.
O site não apaga peers nem altera histórico diretamente. As autorizações
existentes e a recusa de limpeza com tracker externo continuam em vigor.

A solicitação fixa o corte no momento da admissão: mais de 70 minutos sem
announce para o usuário, ou 120 minutos na ação administrativa. Cada endpoint é
reavaliado no estado corrente do journal, portanto um announce posterior ao
snapshot SQL protege o endereço renovado. Uma família recente ou outro peer ativo
preserva a atividade correspondente. O peer lógico e suas referências contábeis
seguem a retenção existente, sem novo crédito por upload/download ou conclusão.

O coordenador procura pedidos a cada cinco segundos quando a fila está ociosa e
processa até 25 peers por iteração. Publica transições pelo mesmo journal e só
remove a solicitação após a persistência e o reconhecimento dos efeitos. A fila
tem limite global e no máximo um pedido pendente por usuário, mais um da
administração. Pedidos repetidos enquanto aquele escopo está pendente não gastam
outra cota. Depois da conclusão, uma nova solicitação é uma nova operação.

Cota e pedido são gravados na mesma transação. Sem proprietário PHP com lease
vigente, com fila cheia ou cota esgotada, a admissão é recusada. A disputa entre
admissão e encerramento usa o mesmo lock de propriedade: um pedido aceito impede
certificar a drenagem até ser processado. Erros ambíguos de conexão podem impedir
a confirmação ao navegador; a mensagem não promete que a transação foi revertida.

SIGTERM e `dualstack:work --once` drenam os pedidos com a entrada fechada. Há um
limite de 120 segundos para essa fase; se excedido, o processo falha e mantém os
pedidos para recuperação. Não iniciar Rust nem forçar `php_journal_drained` nessa
situação. A próxima geração PHP retoma o journal e os pedidos persistidos.

## Exclusões de usuários e torrents

Aplicar também `2026_10_08_000005_add_dualstack_removal_state.php` antes de iniciar
os novos backends. A migração é aditiva, retomável e preservada no rollback.
`deleted_at` registra a intenção; `tracker_removal_state` indica 0 (ainda não
selada), 1 (tráfego anterior confirmado, exclusão em curso) ou 2 (concluída).

Com dualstack ativo, os controllers, a exclusão em lote de torrents similares
e a poda automática deixam peers/histórico para o coordenador. Ele bloqueia
novos announces do alvo, confirma o journal até uma fronteira finita e remove
até 200 peers ou históricos por lote. Endpoints são removidos em cascata e os
contadores deduzem cada peer lógico uma vez. Crédito confirmado permanece.
Uma reentrega antiga não recria estado de uma exclusão selada.

O polling ocioso ocorre a cada cinco segundos. A API Rust bloqueia o alvo já
na exclusão administrativa; o marcador SQL permite retomar depois de falhas.
Respostas e snapshots omitem peers bloqueados durante a limpeza. O encerramento
drena exclusões com prazo limitado; falha preserva o marcador para recuperação.
Os conjuntos de exclusão são restaurados no bootstrap. Não há consultas MySQL
novas no caminho de announce Rust.

No modo externo, o site exige `coordinated_deletion=true` nas capacidades antes
de alterar o alvo. Um backend sem essa capacidade recebe recusa explícita.
Não apagar manualmente os marcadores nem restaurar registros via SQL com um
coordenador em execução: restauração administrativa não faz parte desta entrega.

## Garantias verificadas e limites

Os testes confirmam contabilidade única, persistência idempotente, concorrência,
dois endpoints por peer, troca de endereço, expiração parcial, limites, resposta
compacta e origem observada. O progresso posterior de integração Rust e API
administrativa está em [execução do plano](plans/2026-10-08-dualstack-execucao.md).
A preferência visual, o job diário e os contadores REST estão descritos em
[contadores e preferência](dualstack-contadores.md); segue a revisão dos demais
consumidores do site. BON por família foi retirado da entrega obrigatória em
08/10/2026; preservam-se as regras atuais e a obrigação de verificar que dualstack
não duplica BON ou seedtime. Um incentivo opcional a IPv6 ainda não está pronto;
os enums adicionados ao schema são apenas preparação estrutural.

A referência Redis avança junto da inclusão no journal. SQL e seus efeitos são
confirmados numa transação; a mensagem só é reconhecida depois. A resposta lista
o estado SQL confirmado, com filtro temporal, portanto pode refletir o atraso da
persistência assíncrona. Não há promessa de perda zero de announces ainda não
confirmados em encerramento abrupto; a janela sob carga ainda será medida.

O ensaio de falhas reais confirmou recusa HTTP com MySQL/Redis indisponíveis,
preservação de uma transição pendente e recuperação em nova geração, sem crédito
duplicado. Depois de restaurar os serviços, a lease anterior pode levar até
30 s para expirar; o supervisor deve aguardar ou repetir a aquisição, sem
forçar a troca do proprietário. O laboratório reiniciou o coordenador somente
depois da expiração observada no MySQL. Redis foi encerrado com sincronização
do AOF; a durabilidade de comandos não sincronizados não foi inferida desse teste.
