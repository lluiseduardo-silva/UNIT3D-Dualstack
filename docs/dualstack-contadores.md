# Contadores e preferência visual

Em Configurações gerais → Torrent, o usuário escolhe `ipv4`, `ipv6`, `sum`
(peers únicos) ou `auto`. `sum` continua sendo o padrão e conta uma instância
dualstack apenas uma vez. O título do número exibido identifica o modo efetivo.

`auto` usa as famílias dos endpoints vigentes dos peers ativos em seeding. Se
não houver seeding, usa os demais peers ativos. Ambas as famílias ou nenhuma
atividade resultam em `sum`. Não depende do IP da sessão web nem de conexão TCP
comprovada. A escolha permanece em `users.peer_count_mode`; o resultado fica em
`users.peer_count_auto_mode`. Salvar `auto` resolve imediatamente; o comando
`php artisan auto:resolve_peer_count_mode` atualiza diariamente, em lotes de 500
usuários e com uma escrita agregada por lote. O agendamento impede sobreposição.

O recurso requer schema expandido e `DUALSTACK_ENABLED=true` no UNIT3D, tanto no
modo standalone quanto com Rust novo. Manter o TTL configurado no site igual ao
TTL do backend proprietário. O cálculo usa o estado já persistido e ignora
endpoints com `last_announced_at + TTL <= agora`. No modo legado, a preferência
fica guardada, a exibição usa os totais anteriores e o job não consulta endpoints.

A preferência altera a apresentação em listas, cartões, agrupamentos, detalhes,
histórico, favoritos, atividade, estatísticas e listas administrativas. Filtros,
ordenação, BON, reseed, graveyard e limites continuam usando os totais lógicos.
Nenhum accessor substitui `torrent.seeders` ou `torrent.leechers`.

## API de torrents

Com dualstack ativo, a API REST acrescenta a `attributes`:

```json
{
  "seeders": 3,
  "leechers": 5,
  "seeders_ipv4": 2,
  "seeders_ipv6": 2,
  "leechers_ipv4": 3,
  "leechers_ipv6": 4
}
```

Os campos existentes permanecem totais únicos, para qualquer preferência do
usuário. Os quatro campos novos não aparecem quando dualstack está desativado.
O caminho de busca carrega os seis contadores em um lote SQL por página, para
funcionar mesmo com índice anterior à mudança e manter coerência entre totais
e famílias. O cache de busca conserva sua validade anterior de 5–6 minutos e
separa respostas legadas das respostas dualstack. Não há consulta por resultado
ou por endpoint e nenhuma mudança no caminho de announce Rust.

## Validação desta etapa

`lab/dualstack/run-preference-tests.sh` executa 23 casos novos e os 13 testes do
adaptador administrativo: 36 testes, 220 asserções no MySQL 8.0.46 do laboratório.
Todos os templates Blade compilaram. A suíte cobre salvamento/autorização,
resolução diária, prioridade do seeding, expiração parcial, ausência de atividade,
modo legado, renderização sem SQL adicional, projeções das listas e APIs.
O teste da busca simula somente o resultado do motor de busca; usa o controller,
cache e MySQL reais. Não representa homologação do serviço Meilisearch.

Regressão BON: uma regra existente pagou 30 pontos por usuário/torrent antes e
depois de acrescentar endpoints e outro peer, em todos os modos visuais e com
ambas as configurações de backend. O seedtime não foi alterado pelo pagamento.
Isso não substitui os ensaios de seedtime do processamento de announce.

Sem revisão visual completa no navegador, benchmark ou implantação em produção.
Evidência bruta: `lab/dualstack/results/php-preference-tests.txt`.

## Conectividade usada no BON existente

Com dualstack ativo, o job de alocação e a tela de ganhos usam a mesma fonte SQL:
um peer é conectável para BON somente se tiver um endpoint com checagem positiva
e `last_announced_at + endpoint_ttl > agora`. IPv4 e IPv6 têm o mesmo peso nessa
decisão. Conectividade desconhecida, negativa ou expirada não comprova acesso.
O cálculo não espera a rotina de limpeza atualizar a projeção `peers.connectable`.

A remuneração continua agregada uma vez por usuário/torrent, com as mesmas
condições, variáveis, multiplicadores e operações existentes. A contagem de
torrents elegíveis mostrada por regra usa a mesma conectividade agregada do job,
inclusive numa regra `connectable = 0` com vários peers. O modo visual não muda
o cálculo. Nenhuma regra nova por família foi acrescentada.

O site consulta endpoints persistidos também quando o proprietário é Rust; não
chama o binário para calcular BON. No modo legado, continua lendo `peers` sem
acessar `peer_ips`. Permanecem os filtros anteriores de atividade, seeding e
idade mínima do job, assim como o atraso normal da persistência assíncrona.

Validação funcional: **83 testes / 925 asserções**, mais 20 verificações dos
consumidores, no MySQL real. O primeiro ensaio concorrente revelou uma pendência:
deadlocks entre a alocação e gravadores do journal, reproduzidos também com a
consulta BON legada e os gravadores dualstack atuais. Os créditos finais
permaneceram corretos com retries, mas aquele gate não passou. Essa evidência
histórica permanece registrada; a correção da disputa está descrita abaixo.

A alocação agora lê os ganhos com SELECT comum e incrementa somente `users`,
em lotes de até 500 IDs ordenados, dentro de uma única transação. Não mistura
joins do swarm no UPDATE de saldos. Em REPEATABLE-READ, a leitura usa o snapshot
da transação; os incrementos usam o saldo corrente e valores decimais exatos.
A idade dos torrents usa um único instante do MySQL para todos os lotes.
Uma falha reverte a alocação inteira; o retry existente repete a transação toda.

Validação atual: 90 testes / 978 asserções funcionais e 20 checks dos consumidores;
dois gates de concorrência PHP com 50 asserções cada; teste do gravador Rust
concorrendo com o job PHP real. Todos passaram, sem novos deadlocks/timeouts e
sem diferença de crédito. Inclui fronteira de 500 usuários, rollback, retry,
arredondamento e mudança do relógio entre lotes. Evidências e comandos no runner
`run-bon-tests.sh`, `run-bon-rust-tests.sh` e no documento de execução.

## Seedboxes e clientes do perfil

A marca de alta velocidade considera qualquer endpoint vigente de um seeder
ativo cujo IP esteja cadastrado como seedbox. TTL, expiração e troca de IP não
dependem da coluna legada. Não se exige nova comprovação de conectividade.
O job lê um snapshot e atualiza somente a marca dos torrents, em lotes de 500,
sem locks de escrita sobre os peers. Modo legado continua disponível.

No perfil, dualstack mostra uma linha por peer lógico/torrent e 25 linhas por
página. Cada linha reúne os dois caminhos, portas e checagens; caminhos expirados
são identificados e peers sem caminho vigente saem da lista ativa. O proprietário
e a moderação podem ver os IPs; terceiros nem carregam esses dados. O `peer_id`
permanece interno. O agrupamento anterior é mantido quando dualstack está desligado.

Regressão ampliada: 118 testes / 1.215 asserções e 20 checks dos consumidores.
BON e marcação de seedboxes passaram com cinco processos e cinco esperas forçadas
por cenário, em ambos os modos, sem novos deadlocks/timeouts. Perfil: três
consultas para 1 ou 50 peers e HTML real validado. Não é um benchmark nem revisão
visual completa do navegador. Evidências `results/site-final-*.txt`.
