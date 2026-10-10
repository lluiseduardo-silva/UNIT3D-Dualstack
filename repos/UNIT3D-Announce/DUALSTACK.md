# Dualstack — candidato baseado em 0.3.1

`DUALSTACK_ENABLED=true` conecta o handler ao coordenador em memória e ao
consumidor transacional. O modo fica desativado por padrão. Esta entrega ainda
não está homologada para produção: integração das regras do site, clientes BitTorrent reais e benchmarks permanecem em desenvolvimento.

Antes de iniciar, aplicar as três migrações aditivas no UNIT3D, interromper a
entrada, drenar o backend anterior e executar backfill/reconciliação. O Rust
exige confirmação SQL de drenagem quando o último proprietário foi PHP.
Se o PHP caiu com journal pendente, recuperar e drenar com o próprio PHP.

Cada identidade `(user_id,torrent_id,peer_id)` guarda um endpoint por família.
`MAX_PEERS_PER_TORRENT_PER_USER` continua limitando peers lógicos;
`DUALSTACK_MAX_ENDPOINTS_PER_PEER` aceita 1 ou 2. `ANNOUNCE_MIN_ENFORCED`
passa a valer por família. O segundo caminho compartilha contabilidade,
conclusão e seedtime. `numwant` limita peers; cada selecionado pode fornecer
6 bytes em `peers` e 18 em `peers6`. Totais independem desse truncamento.

O TTL de endpoint tem padrão 7200 s, com seleção temporal e limpeza a cada
60 s. A referência contábil permanece em memória, com fila limitada por
`DUALSTACK_MAX_PENDING_TRANSITIONS` (padrão 100000). Persistência a cada 100 ms,
em lotes de até 200 transições, com versões e todos os efeitos no mesmo commit.
Esses intervalos não constituem garantia de latência nem de perda zero em crash.

Em TCP, headers de origem só são usados quando a conexão vem de IP/CIDR listado
em `DUALSTACK_TRUSTED_PROXIES`. A lista vazia usa a origem da conexão. O proxy
deve sobrescrever o header configurado ou acrescentar corretamente a origem à
direita. Socket Unix pressupõe proxy local confiável. `ip`, `ipv4` e `ipv6`
da query não cadastram endereços. Redes privadas exigem configuração explícita.

Os probes mantêm o teste TCP da tag, com timeout de 500 ms, no máximo 128 em
voo e cache limitado/expirável. `DUALSTACK_CONNECTIVITY_CACHE_ENTRIES` e
`DUALSTACK_CONNECTIVITY_CACHE_TTL` controlam esse cache, substituindo o cache
legado neste modo. IP, porta e revisão protegem contra resultados atrasados.
TCP aceito não comprova handshake ou transferência BitTorrent.

O supervisor renova a lease entre operações do escritor, com cadência de cinco
segundos quando o banco responde normalmente. O fence SQL permanece no lote.
Após dez segundos sem confirmação recente, a entrada fica pausada; a operação
em andamento continua até seu resultado ou timeout próprio. Erros transitórios
de persistência/renovação preservam a fila em memória e permitem novas tentativas
por até 120 s, verificadas entre operações limitadas. Uma renovação confirmada
da mesma geração e a drenagem são necessárias para reabrir a entrada.

Lease expirada ou substituída não é readquirida automaticamente. Erros definitivos
fecham a entrada e registram geração e quantidade de transições não confirmadas.
A fila continua volátil: crash, perda definitiva da propriedade ou falha terminal
podem impedir sua persistência. Não há replay da fila antiga sob outra geração.

SIGTERM fecha a entrada definitivamente, aguarda a operação em voo e drena antes
de liberar a posse. Reserve pelo menos 180 s no timeout do gerenciador de processos
para o orçamento de drenagem e encerramento HTTP. Mudanças na política dualstack
exigem restart; o endpoint de reload retorna 409 se tentarem alterá-la.

Validação no laboratório: contrato de 12 casos/51 operações, suíte MySQL com
18 blocos, 30 passos HTTP nas duas famílias, SIGTERM/restart e recusa de um
segundo processo. A API administrativa agora representa endpoints explicitamente, conforme o contrato abaixo.


A retenção usa `INACTIVE_PEER_TTL` (padrão da tag: 1814400 s; mínimo 7200 s
neste modo). A cada 60 s o coordenador remove lotes de até 200 peers inativos
sem transições pendentes. Reserva essas identidades durante o DELETE cercado
pela lease, sem segurar o mutex em I/O. Peers recentes ou ativos permanecem.
O histórico de usuário/torrent e sua versão/conclusão são preservados. Uma
reconexão depois da remoção estabelece nova referência sem creditar o passado.
Falha ou cancelamento da limpeza fecha a entrada e exige novo bootstrap.


A rota administrativa autenticada `GET /announce/{APIKEY}/capabilities` retorna
`dualstack`, `peer_schema`, `peer_count` e `max_endpoints`. Modo legado usa schema
0 e `dualstack=false`; dualstack ativo usa schema 1 e `peer_count=unique`.
`GET .../torrents/{id}` inclui a mesma capacidade, totais lógicos, os quatro
contadores por família e um objeto `peers`, com chave `user_id-HEX(peer_id)`.

No schema 1, upload/download/left são strings decimais uint64. Cada peer tem
`endpoints[]` com família, `ip_address`, porta, conectividade nullable, timestamps
e revisão, além de estado agregado e versões. Endpoints expirados não aparecem;
peers inativos permanecem com lista vazia até sua retenção. IP/porta no nível do
peer são apenas projeção de compatibilidade, nunca a fonte para novos leitores.
O UNIT3D novo aceita tanto o contrato legado quanto o schema 1, sem apresentar
um backend antigo como dualstack. Contadores de usuário vêm do mesmo estado
lógico. Refresh de metadados não sobrescreve contadores correntes do coordenador.

Validação administrativa: 22 blocos MySQL, 13 testes do leitor/renderização PHP,
30 passos HTTP reaprovados e integração real UNIT3D -> Rust, com seis peers,
onze endpoints, uint64 máximo exato e quatro consultas para carregar a tela.
Double upload/freeleech e volta aos fatores normais foram exercitados nas duas
famílias, com o fator aplicado uma vez ao delta lógico.
