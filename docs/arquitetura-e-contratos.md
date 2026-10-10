# Arquitetura e contratos da implementação

## Modelo

Identidade lógica: `(user_id, torrent_id, peer_id)`. O parâmetro BT `key` não cria outra identidade. `peer_id` é binário; para correlação, usar representação hexadecimal junto com usuário e torrent. A identidade não prova uma máquina física.

`peers` conserva estado e referências de upload/download, atividade, visibilidade, seeder, versões e estado de sessão. `peer_ips` usa a identidade composta mais `family` (4 ou 6), endereço binário, porta, conectividade, último announce e revisão. A chave limita um endpoint por família; FK composta com cascata, restrições de família/tamanho e índices suportam consulta e expiração. Não há crédito, BON ou seedtime por endpoint.

Código: [migrações aditivas](../repos/UNIT3D/database/migrations/), [transição PHP](../repos/UNIT3D/app/Services/Dualstack/PeerTransition.php), [peer Rust](../repos/UNIT3D-Announce/src/dualstack/peer.rs).

## Contrato observável

| Evento/condição | Comportamento |
|---|---|
| Announce pela outra família | Atualiza somente aquele caminho; referência contábil compartilhada |
| Troca de IP/porta | Substitui o endpoint da mesma família; revisão protege contra resultado de probe atrasado |
| `stopped` | Retira o endpoint da origem corrente; a outra família permanece; aceita porta zero conforme contrato |
| Expiração | TTL por endpoint; atividade de IPv4 não renova IPv6 |
| Contadores cumulativos repetidos/atrasados | Não reaplicam crédito nem fazem a referência avançada recuar |
| Segundo `started` / conclusão | Não abrem uma segunda unidade contábil; sessão e conclusão têm deduplicação |
| Limite por usuário/torrent | Conta identidades, não endpoints; três peers podem ter até seis caminhos |
| Resposta | `peers` e `peers6`; seleção por peer lógico; totais não dependem do truncamento da lista |
| Conectividade | Estado por endpoint: desconhecido, positivo ou negativo; TCP positivo não prova transferência BitTorrent |
| Origem | Endereço observado ou proxy explicitamente confiável; parâmetros arbitrários não cadastram outra origem |

Endereços IPv4 mapeados são normalizados. Endereços inadequados, incluindo link-local, são recusados. Uso de endereços privados é configuração explícita do laboratório. Probes assíncronos com IP/porta/revisão antigos não alteram o endpoint novo. Ver [rede, TLS e cache](dualstack-tls-memoria.md).

## Rust: processamento e persistência

O [HTTP](../repos/UNIT3D-Announce/src/dualstack/http.rs) processa announces no estado em memória, sem nova consulta síncrona MySQL por request. O [coordenador](../repos/UNIT3D-Announce/src/dualstack/coordinator.rs) produz transições versionadas. A [persistência](../repos/UNIT3D-Announce/src/dualstack/persistence.rs) confirma referências e efeitos relacionados transacionalmente, impedindo reaplicação de crédito em retries confirmados.

O [runtime](../repos/UNIT3D-Announce/src/dualstack/runtime.rs) serializa renovação da propriedade e persistência; falhas transitórias pausam admissão e preservam fila enquanto a recuperação é segura. Confirma a mesma geração antes de retomar. Não adquire silenciosamente outra geração para reaplicar uma fila antiga. Orçamento de recuperação: 120 s, verificado entre operações com limites próprios.

Lotes configuráveis de 1–500, padrão 200; os ensaios a 8 mil/s usam 500. Lotes cheios não esperam obrigatoriamente o tick de 100 ms. [Escritor](dualstack-writer.md) explica cadência, garantias e medição do custo.

**O journal Rust continua volátil.** Crash pode perder transições ainda não persistidas. [Queda abrupta](dualstack-falha-abrupta.md) demonstra preservação do estado confirmado e recuperação de delta cumulativo posterior no cenário ensaiado; não garante recuperação de todos os eventos ou seedtime.

## Consumidores e interface

Totais globais são a união das identidades. Preferências `ipv4`, `ipv6`, `sum` e `auto` alteram apresentação; sem atividade, `auto` resolve para `sum`. Reseed mantém menos de três seeders únicos no total; graveyard exige nenhum seeder disponível em qualquer família, preservando demais regras. Fórmulas BON não ganham remuneração por família. A independência do PHP standalone é preservada.

Ver [contadores](dualstack-contadores.md), [serviços PHP](../repos/UNIT3D/app/Services/Dualstack/), [API Rust](../repos/UNIT3D-Announce/src/dualstack/admin.rs) e [contrato do produto](../repos/UNIT3D-Announce/docs/dualstack.md).

## Ativação, troca e retorno

Entrada fechada, drenagem verificada e exclusão dos escritores são pré-condições. Os binários antigos não conhecem a lease nova; uma lease expirada não prova que filas foram drenadas. O retorno ao legado mantém o schema aditivo e utiliza a projeção `peers.ip/port`. Para reativar dual-stack após escrita legada, executar reconciliação offline; backfill inicial não a substitui.

O [procedimento completo e seus testes](dualstack-rollback-legado.md) é a referência operacional. Não executar `migrate:rollback` para simplesmente retornar os binários. O experimento de cache [B](../lab/dualstack/capacity-cache-b.patch) está separado e não integra os fontes deste pacote.
