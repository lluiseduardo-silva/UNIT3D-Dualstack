# Reconciliação e cancelamento na inicialização Rust

Incremento autorizado em continuidade à revisão de pendências. Base Rust
`9446bfd`, PHP `6d8e743`, coordenação `d2df124`. Plano em
[2026-10-08-bootstrap-rust.md](plans/2026-10-08-bootstrap-rust.md).

## Correção

A consulta antiga avaliava seis EXISTS correlacionados para cada peer. A nova
agrupa endpoints por `(user_id,torrent_id,peer_id)`, obtendo uma linha com as
famílias presentes; consulta cada peer pela chave primária e agrega por torrent.
Torrents sem peers elegíveis recebem zero. Visibilidade, atividade e política
de conectividade são preservadas (`src/dualstack/persistence.rs:182`).
O GROUP BY impede a fusão da tabela derivada; a ordem da junção e a chave
primária eliminam o caminho de busca por todos os endpoints do torrent.
[Regra de materialização do MySQL](https://dev.mysql.com/doc/refman/8.0/en/derived-table-optimization.html).

A reconciliação continua sem TTL dentro da mesma transação protegida por geração;
a expiração inicial produz as transições seguintes antes de abrir a entrada.
Não altera upload/download, histórico financeiro, versões, schema ou dependências.
Não muda o caminho normal de announce ou de persistência.

O bootstrap agora reserva conexões de trabalho e controle. Ambas são fechadas
ao sair, sem devolver operação pendente ao pool. Em falha, prazo excedido ou
cancelamento da future, uma tarefa de limpeza encerra somente a conexão de
trabalho. Aguarda sua saída de PROCESSLIST antes de liberar a propriedade
(`src/dualstack/bootstrap.rs:9`). O prazo normal continua em 120 s; os testes
podem informar prazo menor pela entrada de validação do coordenador.

KILL sinaliza a interrupção e não espera toda a limpeza terminar. Por isso o
acknowledgment isolado não serve de confirmação. A operação usa a mesma conta
SQL para encerrar sua própria conexão, sem adicionar privilégios globais.
[Semântica e permissões do MySQL](https://dev.mysql.com/doc/refman/8.0/en/kill.html).

O encerramento tem orçamento de cinco segundos. Sem confirmação, a inicialização
retorna erro explícito e não libera a propriedade (`BootstrapCancellation`).
A limpeza após cancelamento depende do runtime ainda ativo. Encerramento abrupto
do processo/VM não executa essa tarefa; sua medição permanece no item de falhas
sob carga. Nenhuma garantia de perda zero foi acrescentada.

## Evidência funcional

- Controle anterior: dois segundos após cancelar a future, a consulta continuava
  no servidor. O harness encerrou exclusivamente aquela conexão; rollback completo.
- Candidato: a conexão saiu em aproximadamente 2–4 ms após o cancelamento.
- Timeout interno de 250 ms: retornou somente com consulta encerrada e rollback
  confirmado; uma consulta paralela não foi interrompida.
- Conexão de controle sabotada: erro explícito, propriedade ainda vigente e
  nenhuma confirmação parcial. Limpeza manual isolada e recuperação verificadas.
- Contadores com IPv4-only, IPv6-only, dualstack, invisíveis/inativos, conectividade
  desconhecida/negativa e expiração independente: corretos, sem crédito novo.

O primeiro controle teve uma asserção incorreta no harness: durante o fence,
o segundo proprietário pode receber timeout na aquisição do lock, além de
`Owned`. Ambos impedem a entrada. Corrigida essa expectativa, o controle passou.
A primeira compilação do candidato expôs uma limitação de inferência de lifetimes
de `raw_sql` em tarefa Send; o comando usa o Executor direto, sem atualizar SQLx.
Tentativas e execução aprovada estão em `lab/dualstack/results/bootstrap/`.

## Escala e regressão

MySQL 8.0.46, REPEATABLE-READ, quatro vCPUs por VM. Fixtures 100% dualstack,
80% seeders, 20% leechers; 250 peers por torrent no layout distribuído. O layout
concentrado é um controle adverso, acima do perfil operacional informado pelo
usuário. Cada população/layout passou por três inicializações completas.

| Peers | Torrents | Consulta nova | Inicialização completa, mínimo–máximo |
|---:|---:|---:|---:|
| 1.000 | 4 | 3,05 ms | 45,9–83,4 ms |
| 1.000 | 1 | 3,08 ms | 48,7–50,2 ms |
| 54.000 | 216 | 128,20 ms | 1,71–1,91 s |
| 54.000 | 1 | 124,20 ms | 1,69–1,88 s |
| 100.000 | 400 | 247,25 ms | 3,11–3,38 s |
| 100.000 | 1 | 237,50 ms | 2,81–2,92 s |

Seis cenários e 18 aberturas aprovados. Nenhum ANALYZE TABLE corretivo foi
executado; a atualização automática de estatísticas do MySQL permaneceu ativa.
Todos os planos candidatos fizeram lookup `eq_ref` pela chave primária de
`peers`. As operações `Handler_read_*` totalizaram aproximadamente cinco por
peer, incluindo leitura dos endpoints e tabelas temporárias. São contadores de
operações de acesso, **não ROWS_EXAMINED**; as estimativas do EXPLAIN também não
são contagens reais de linhas examinadas.

O controle antigo força o índice desfavorável observado no diagnóstico anterior.
Com 1.000 peers, levou 131 ms distribuídos e 514 ms concentrados; nos quatro
casos maiores foi interrompido deliberadamente após dois segundos. Os resultados
truncados são limites inferiores, não tempos completos nem baseline típico do
código anterior. A consulta candidata terminou dentro desse orçamento em todos
os casos; não foi necessário reproduzir outra espera de 120 segundos.

Cada abertura validou os seis contadores, dois endpoints por peer, backlog zero,
versões e referências financeiras preservadas. O fechamento de 100 mil peers
confirmou 200 mil endpoints, 80 mil seeders e 20 mil leechers únicos; peers,
histórico e usuários ficaram sem crédito novo. Geração 1892 liberada, nenhuma
consulta ativa daquele banco (`results/bootstrap/closure.json`).

Regressão completa aprovada (`results/bootstrap/regression-v1.txt`): contrato
compartilhado, MySQL/replay/rollback/retries, deadlocks reais, retenção, limites,
BON, reembolsos, troca PHP/Rust/PHP, limpeza/exclusão e 19 testes de rede/utilitários.
O caminho de limpeza/exclusão executou 57 testes PHP e 746 assertions; o de
journal/handoff, 27 testes e 474 assertions. A repetição funcional final confirmou
o cancelamento com usuário sem SUPER/CONNECTION_ADMIN nos grants diretos.

A auditoria de fontes encontrou duas diferenças antigas somente nos testes do
laboratório: formatação de `dualstack_history.rs` e texto de diagnóstico de
`dualstack_refund.rs`. Os fontes de produto e lockfiles já eram idênticos.
Sincronizados esses dois arquivos com o checkout, os contratos de histórico e
reembolso foram executados novamente. O hash anterior foi preservado em
`source-tracker-before-test-sync.json`; `source-local.json` e
`source-tracker.json` conferem todos os fontes Rust, testes e arquivos Cargo.
O contrato de histórico repetido passou em PHP (258 assertions) e Rust
(23 operações); o de reembolso confirmou 480 transições com reentrega, sem novo
deadlock ou timeout. O fechamento final registrou geração 1895 inativa, nenhuma
consulta pendente, tracker parado e nenhum namespace ou alias de carga.

## Reprodução e entrega

Com os fontes deste checkpoint instalados no laboratório isolado:

1. Preparar `unit3d_dualstack_journal_test` com `initialize-journal-test.php`.
2. Executar `run-bootstrap-tests.sh`, mantendo os serviços de announce parados.
3. Executar `run-writer-tests.sh` para a regressão com MySQL/Redis reais.
4. Executar `run-bootstrap-scale.ps1 -IdentityFile <chave-local>`. O runner recusa
   resultados existentes, verifica mais de 3 GiB livres na VM de dados e recria
   somente o banco descartável entre cenários. `-Populations`, `-Layouts` e
   `-Revision` permitem investigar uma tentativa sem sobrescrever a anterior.
5. Coletar os hashes com `bootstrap-source.py`, o fechamento com
   `inspect-bootstrap.py` e auditar com `summarize-bootstrap.py`.

O controle negativo histórico foi executado contra `9446bfd` com a versão inicial
do harness, antes de acrescentar os testes da nova API de timeout. A opção de
controle negativo não é um resultado esperado no produto corrigido.

Evidências: `lab/dualstack/results/bootstrap/summary.json`, planos EXPLAIN,
logs brutos, ambientes e `manifest.json`. Checkpoint:
`lab/dualstack/checkpoint-bootstrap.json`. O warning de `Atomic::fetch_update`
em `src/stats.rs:226` já existia e permanece fora deste incremento.

O disco de dados terminou com aproximadamente 7,40 GiB livres; tracker, 6,31 GiB;
o thin pool compartilhado tinha aproximadamente 16,82 GiB físicos disponíveis
(ocupação de 87,73%). Estes valores são o snapshot da rodada. Nenhuma expansão,
purga de binlog ou alteração de durabilidade foi feita neste incremento.

O gate desta correção não substitui a comparação formal original versus candidato,
a medição da janela de perda abrupta, memória/cache sob rotação, proxy/TLS/probes
e o ensaio de seis horas. As próximas cargas extensas ainda precisam caber no
orçamento de armazenamento; não houve push, publicação ou produção.

## Revisão final

Revisão única do diff contra o plano: correção limitada à inicialização, sem
alterar persistência normal, política financeira, schema, lockfiles ou produto
PHP. Há dois ajustes de instrumentação explícitos: contadores `Handler_read_*`
e EXPLAIN no lugar de afirmar ROWS_EXAMINED por execução; controle adverso
interrompido em dois segundos, com resultados incompletos identificados. Nenhuma
divergência funcional ficou pendente neste incremento.

Commit Rust: `9e8b54626334db11940e3ebf939cbf40ba4426a3`. Os fontes executados
conferem com esse checkpoint. O gate de bootstrap está aprovado; os limites da
campanha geral permanecem os descritos acima.
