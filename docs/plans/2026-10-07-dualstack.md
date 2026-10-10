# Plano aprovado: dualstack UNIT3D 9.2.0 / UNIT3D-Announce 0.3.1

Este arquivo registra o contrato aprovado na conversa e as etapas de execução.
Não autoriza publicação, push ou alteração de produção. Cada etapa termina com
verificação; falha no critério interrompe a execução antes da próxima etapa.

## Bases e organização

- UNIT3D v9.2.0: `8b88f4c8182eb3d3912ffef425c3224dcfd596f4`.
- UNIT3D-Announce v0.3.1: `fcd189e9aebf07a12a1f8cc39500819c3870925b`.
- Clones independentes em `repos/`, branch `feat/dualstack` em ambos.
- Preservar os lockfiles. Não incorporar `development`/`main` incidentalmente.
- Este repositório guarda laboratório, fixtures e evidências; os clones possuem
  seu próprio histórico Git e ficam fora do índice do repositório de coordenação.

## Identidade e armazenamento

`Peer = (user_id, torrent_id, peer_id)`. IPv4 e IPv6 são caminhos dessa identidade.
O tracker não prova a identidade da máquina física.

Manter em `peers`: identidade, agent, uploaded/downloaded, left/seeder,
active/visible, timestamps, state_version e deduplicação de conclusão/sessão.
Criar `peer_ips`, com PK `(user_id, torrent_id, peer_id, family)`:

- family 4 ou 6, IP binário compatível, port;
- connectable desconhecido/sim/não, last_announced_at, connectivity_checked_at;
- revision e timestamps;
- FK composta com cascata; índices por torrent e expiração;
- nenhum upload/download, BON ou seedtime por endpoint;
- nenhuma acumulação ilimitada de endereços antigos.

Limite configurável 1 ou 2 endpoints, padrão 2, sempre no máximo um por família.
Com limite 1, recusar família adicional sem expulsar a existente. Troca de IP ou
porta substitui somente o endpoint da mesma família. Limite de peers por
usuário/torrent continua contando identidades, não endpoints.

Manter as colunas antigas como projeção de rollback; novos leitores usam
endpoints. Remoção dessas colunas fica para migração posterior.

## Ciclo de vida e rede

- Primeiro announce cria peer/endpoint; segunda família acrescenta endpoint.
- `stopped` remove só o endpoint cuja origem corresponde ao endereço atual;
  porta zero é aceita. Repetição ou stopped de IP antigo não remove substituto.
- Cada endpoint expira pelo próprio last_announced_at. Padrão 7200 s, limpeza
  a cada 60 s, validade também verificada na seleção das respostas.
- Último endpoint removido torna o peer inativo. Retenção contábil inativa é
  separada da validade de publicação; não excluir com transições pendentes.
- Origem real da conexão/proxy explicitamente confiável; não cadastrar IPs
  arbitrários de parâmetros ip/ipv4/ipv6. Normalizar IPv4 mapeado em IPv6.
- Rejeitar inválidos, não especificados, multicast e link-local. Redes privadas
  somente quando explicitamente permitidas para o laboratório.
- Conectividade é por endpoint; resultado atrasado só vale se IP, porta e revisão
  ainda coincidirem. Peer conectável se algum endpoint vigente tem check positivo.
- Preservar opção de exigir ou não conectividade. Check TCP da 0.3.1 não será
  descrito como prova de transferência BT. Não importar verificador de main.
- Caches auxiliares de conectividade devem ter TTL e limite de entradas.

## Contabilidade e protocolo

Dentro de sessão ativa, para cada contador cumulativo:

```
delta = max(recebido - referencia, 0)
nova_referencia = max(referencia, recebido)
```

Sequência obrigatória de upload: IPv4 1000 (baseline), IPv6 1000 (+0), IPv6
1100 (+100), IPv4 atrasado 1050 (+0), IPv4 1200 (+100): total adicional 200.

Primeiro announce desconhecido não credita tráfego anterior. Segundo `started`
por outra família não reinicia sessão. Contadores menores não baixam referência
ativa. Após encerramento de todos endpoints, novo started pode estabelecer nova
sessão uma vez. `key` permanece aceito, sem virar PK ou dividir peer isoladamente.
Fatores freeleech/double upload aplicam uma vez ao delta. Conclusões, seedtime e
histórico preservam granularidade usuário/torrent; outro endpoint ou peer ativo
impede encerrar o histórico prematuramente.

Separar intervalo por caminho da referência contábil única. Rotação de IP não
reinicia limite da mesma família. Não inventar teto anticheat ausente nas tags;
o teto temporal citado pelo operador integra sua matriz de homologação.

Manter seeders/leechers como totais únicos; acrescentar seeders_ipv4,
seeders_ipv6, leechers_ipv4, leechers_ipv6. `sum` é união deduplicada.
Calcular deltas pelo estado anterior/posterior, não por linhas de join.

Resposta compacta: peers IPv4, peers6 IPv6, complete/incomplete únicos.
`numwant` limita peers lógicos selecionados; retornar ambos endpoints elegíveis
de cada selecionado. Estatísticas independem do truncamento e de numwant=0.
Bytes das listas: `6*N4 + 18*N6 <= 24*numwant_efetivo`.

## Site e independência

- Reseed continua com menos de 3 seeders únicos; preservar controles existentes
  e encerramento de pedidos. Não criar critérios/bloqueios por família nem nova
  lista de solicitantes bloqueados. Esta decisão substitui a proposta inicial.
- Graveyard usa seeders=0, equivalente a ambas famílias zeradas; preservar idade
  mínima e demais condições. Preferência visual não altera regras do domínio.
- BON preserva seeders/leechers e remuneração existente, com uma remuneração
  usuário/torrent; connectable agregado por qualquer endpoint. Conforme revisão
  de escopo do usuário em 08/10/2026, BON por família deixa de ser requisito da
  entrega. Continua obrigatória a validação de que dois endpoints não duplicam
  o pagamento nem o seedtime.
- Um incentivo a IPv6 poderá ser um complemento opcional das regras atuais,
  configurado pelo administrador, se houver suporte completo e validado. A base
  atual é apenas estrutural: endpoints, contadores e enums aditivos no schema;
  cálculo, validação e editor ainda não oferecem BON por família. Portanto,
  implementar esse incentivo fica fora desta entrega e não bloqueia dualstack.
  Incentivar o uso pelo usuário exige avaliar os endpoints dele no torrent;
  a quantidade de seeders IPv6 do swarm não comprova uso individual de IPv6.
  Preservar o schema já aplicado, sem criar regras ou alterar pagamentos.
- peer_count_mode: ipv4/ipv6/sum/auto, padrão sum. Job diário resolve auto por
  peers ativos seeding; se ausentes, demais peers ativos; ambas ou nenhuma família
  resulta sum. Guardar opção e resolução separadamente, sem sobrescrever auto.
- Preferência só altera apresentação. APIs mantêm campos legados e acrescentam
  contadores por família. Telas: uma linha por peer, endpoints associados e
  mesmas permissões sobre os endereços.
- UNIT3D completo sem instalar/executar Rust. Contrato comum por fixtures, sem
  dependência de runtime entre os projetos.

## Etapas e verificações

1. Preparação/baseline: clones fixados, versões registradas, laboratório, gerador
   determinístico e comportamento original. Demonstrar overwrite, intervalos,
   respostas, banco e crédito. 54 mil peers e 27–98 ms são dados do operador,
   não medições nossas. Não alterar processamento antes deste gate.
2. Schema/contrato: migração aditiva, backfill retomável, famílias/PK/FK/índices,
   contadores e preferências. Verificar no MySQL real limite de endpoints,
   idempotência de backfill e preservação dos totais anteriores.
3. PHP standalone: Redis compartilha referência entre processos e registra
   transições (identidade, versão, snapshot lógico/endpoints, deltas e histórico).
   Referência+enqueue atômicos; lotes ordenados em transação MySQL; state_version
   deduplica. Ack só após commit; reconciliar caches/pendências; não aceitar
   silenciosamente se fila/armazenamento falhar. Carregar endpoints em lote.
   Verificar múltiplos processos/workers, com Rust ausente.
4. Rust: preservar IndexMap; endpoints limitados; nenhum SQL síncrono por
   announce. Mutação+enqueue na mesma seção de sincronização, sem I/O nela.
   Coordenador de lotes ordenados aplica snapshot e efeitos atomicamente, com
   versões, retry limitado e backlog limitado. Atualizar bootstrap, expiração,
   conectividade, API e shutdown. Verificar restart e ausência de SQL por request.
5. Integração: API peer/endpoints/contabilidade/estado agregado, negociação de
   capacidade e modo legado explícito. Adaptar consumidores do site. Um backend
   proprietário por swarm com exclusão compartilhada e geração/fencing. Não
   balancear PHP/Rust independentes. Verificar paridade usando mesmos parâmetros.
6. Implantação/retorno (laboratório): expandir schema desativado; parar entrada,
   drenar filas, pausar escritores; backfill/reconciliar; carregar backend;
   ativar e acompanhar. Testar Rust novo -> PHP novo mantendo dualstack e novo ->
   original com projeção de um endereço. Se legado escrever, reconciliar de novo
   antes de reativar. Não remover colunas legadas nesta entrega.

## Laboratório e aceitação

Três VMs novas, 4 vCPU/8 GiB cada: tracker, dados e clientes. Inventariar antes
de criar. Rede isolada com IPv4/IPv6 reais e namespaces; não simular família
somente via header. MySQL 8.0/Redis 7.2 iniciais, digests/versões/isolation/locks
registrados. Homologação do operador espelha suas versões.

Matriz obrigatória: v4->v6 e inversa; simultaneidade; deltas iguais/fora de ordem;
started/completed duplicados; stopped parcial/repetido/IP antigo/porta zero;
rotação IPv6; expiração independente; falha de família; 3 peers dualstack e
rejeição do quarto; peer_id igual em usuários diferentes; numwant=0/truncamento;
restart/reentrega; proxies/IPs inválidos; BON/seedtime; reseed/graveyard; auto.

Concorrência no MySQL/Redis reais: múltiplos workers, expiração/stop/update,
lotes pequenos sobre mesmas chaves, crash antes/depois do commit e antes do ack,
indisponibilidade temporária, probes atrasados, dois proprietários e handoff
com pendências. Inspecionar versões/filas/contabilidade e locks/deadlocks.

Clientes reais: qBittorrent/libtorrent e Transmission, versões registradas;
verificar endpoints, handshake, transferência/hash, v4-only/v6-only e falha de
caminho. Evidências correlacionam usuário/torrent/HEX(peer_id)/família/evento/
versão/delta; não registrar passkeys ou credenciais.

Comparar original/candidato separadamente por backend, hardware/build/config
iguais; 0/50/100% dualstack, 1k/54k/100k peers, swarms distribuídos/concentrados,
mesmo volume de requests e mesma população de clientes. Três repetições de
5 min aquecimento+15 min medida; soak de 6 h. Não confundir mais announces
legítimos com custo por request. Parâmetros em lab/dualstack/manifest.json.

Gates: zero divergência de crédito/identidade/contagem; p95/p99 <= 1,10x,
throughput >=0,95x, sem aumento de erros; zero SQL novo por request Rust; backlog
estável/drena; memória medida e limitada na rotação; endpoints <=2; payload pela
fórmula (não tolerância genérica de 10%); standalone completo; retries/restart
não reaplicam créditos confirmados. Medir janela de perda não persistida, sem
prometer perda zero ou ampliá-la silenciosamente.

Entregáveis: dois projetos alterados, migrações/backfill/reconciliação, fixtures
e testes, laboratório reproduzível, resultados brutos/comparativos, ativação/
handoff/rollback, documentação de configurações/contadores/preferências.

Fora de escopo: vários IPs da mesma família; dependência PHP->Rust; nova política
reseed por IP; conversão automática da remuneração BON; produção; tradução entre
redes (um peer IPv6-only pode não ser acessível a um cliente IPv4-only).
