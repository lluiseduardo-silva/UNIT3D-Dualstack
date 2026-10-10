# Retorno ao legado e reativação do dualstack

O retorno mantém o schema expandido e usa `peers.ip`/`peers.port` como projeção de
um endereço por peer. Depois de escritores originais executarem, `peer_ips` e
`protocol_state` deixam de ser fontes confiáveis. É necessário reconciliá-los
antes de iniciar um coordenador novo.

## Comandos e pré-condições

A migração `2026_10_08_000006_add_dualstack_legacy_reconciliation.php` acrescenta
`tracker_ownership.legacy_reconciliation_required`. Aplicar essa migração antes
de iniciar os coordenadores desta revisão. Ela é aditiva e retomável, assim como
as anteriores; não executar `migrate:rollback` para retornar o binário.

`dualstack:legacy` exige `DUALSTACK_ENABLED=false`, configuração efetiva atualizada
e `--offline`. O parâmetro confirma que **todos** os escritores foram interrompidos:
announces, workers, scheduler, sincronizadores e qualquer tarefa administrativa
que altere peers, históricos ou contadores. Os binários originais não conhecem a
lease nem o marcador; o comando não consegue bloquear um processo antigo ainda
em execução.

O comando verifica a ausência de proprietário ativo, journal, lotes legados
(`peers`, `histories`, `announces`), jobs prontos/reservados/atrasados na conexão e
fila padrão configuradas, limpezas e remoções pendentes. O produtor original
`ProcessAnnounce` usa essa fila padrão. Filas adicionais configuradas pelo operador,
jobs falhos que serão reexecutados e processos externos também precisam ser
resolvidos antes do procedimento. Não apagar filas para conseguir passar nas
verificações. Manter os mesmos banco, Redis, prefixos e configuração de filas em
todas as fases.

## Versão nova → versão original

1. Fechar a entrada no proxy e pausar tarefas que alterem o swarm. Deixar os
   consumidores drenarem e encerrar o coordenador graciosamente. Conferir erros,
   backlog e saldo. Uma lease expirada, sozinha, não prova drenagem do Rust.
2. Com todos os escritores parados, desativar dualstack na configuração do
   **código novo** e atualizar o cache de configuração conforme a instalação.
3. Executar com o código novo:

   ```sh
   php artisan dualstack:legacy prepare --offline
   ```

   O marcador permanece no MySQL mesmo depois de reinicializações. Os novos
   coordenadores PHP e Rust recusam aquisição sem alterar a geração. O comando
   também fecha a disponibilidade do proprietário PHP no Redis.
4. Iniciar somente o backend original escolhido, usando o schema expandido e a
   projeção legada. No Rust, verificar o modo de origem: conexão direta exige
   remover `REVERSE_PROXY_CLIENT_IP_HEADER_NAME`; atrás de proxy confiável, manter
   a configuração correspondente. Não enviar um header artificial para simular
   a origem de rede.
5. Conferir o backend antes de reabrir a entrada. Durante esse retorno há somente
   um caminho publicado por peer e as regras de contabilidade são as da tag
   original. O procedimento não corrige defeitos preexistentes dos binários antigos.

## Versão original → versão nova

1. Fechar novamente a entrada, pausar tarefas, drenar os consumidores originais
   e encerrar todos os escritores. Guardar os totais antes da troca.
2. Ainda com `DUALSTACK_ENABLED=false`, usando o código novo:

   ```sh
   php artisan dualstack:legacy reconcile --offline --batch=500
   ```

3. Se houver falha, manter a entrada fechada. O marcador continua ativo. Corrigir
   a causa indicada e repetir **o mesmo comando**; não limpar o marcador manualmente.
   O lote aceita 1–2.000 peers. Reexecutar não credita tráfego nem reinicia versões.
4. Ativar dualstack, atualizar a configuração e iniciar **um** coordenador. Seu
   bootstrap recarrega as referências e endpoints confirmados, processa expirações
   e assume uma nova geração antes de disponibilizar announces. Conferir contadores,
   filas e saldo antes de liberar o proxy.

Se a versão original já escreveu sem que `prepare` tivesse sido executado, manter
tudo offline, executar `prepare` com o código novo e então `reconcile`. O backfill
inicial não substitui esse procedimento: ele só considera `state_version=0` e
preserva endpoints existentes.

## O que a reconciliação altera

- Percorre todos os peers pela chave composta, incluindo os já versionados.
  Por lote, substitui atomicamente os endpoints pelo endereço legado vigente.
  Endereços IPv4 mapeados são normalizados; endereços privados exigem configuração.
  IP/porta inválidos de um peer ativo e vigente interrompem o procedimento.
- Peers inativos ou expirados não publicam endpoints. IP antigo da outra família
  não volta à lista. A checagem positiva legada é preservada; `false` vira
  desconhecido, pois também representava ausência de verificação.
- Limpa o estado de protocolo desatualizado, deriva a conclusão observada do peer
  ou histórico e usa o timestamp legado do histórico como referência temporal.
  Preserva upload/download de referência, versões, geração da sessão, saldos,
  BON, reembolsos, seedtime e `completed_at`.
- Recalcula atividade do histórico e os seis contadores do torrent pela identidade
  lógica. A exigência configurada de conectividade continua valendo.

Há exclusão MySQL por instalação entre comandos. Cada transação confere que a
conexão ainda possui essa exclusão; uma reconexão não permite continuar sem lock.
Lotes confirmados antes de uma falha podem ser repetidos. A liberação do marcador
só ocorre depois de todos os lotes, históricos e contadores estarem reconciliados.
Não se trata de uma única transação para o swarm inteiro: a indisponibilidade
operacional e o marcador impedem a exposição de estado parcial.

O retorno Rust novo → PHP novo usa a drenagem e transferência de propriedade já
existentes; não executar `prepare/reconcile` nesse caso, pois ambos entendem os
endpoints. A reconciliação legada descartaria desnecessariamente o segundo caminho.

## Validação de 8 de outubro de 2026

Somente laboratório Proxmox, banco `unit3d_dualstack_journal_test`; baseline
preservado. PHP 8.4.26, Rust 1.99.0, MySQL 8.0.46, Redis 7.2.16.

| Verificação | Resultado |
|---|---|
| PHP, reconciliação e regressão do journal | 40 testes / 593 asserções aprovados |
| Rust, contrato MySQL e bloqueio durante reconciliação | aprovado, incluindo retry/deadlock/restart e publicação sem SQL |
| PHP 9.2.0 original: job e consumidores de announce | crédito 100 → 200, filas drenadas |
| PHP novo depois da reconciliação | crédito 200 → 300, sem duplicação ao reanunciar |
| Rust 0.3.1 original: announce HTTP IPv4 real | aceito; crédito 300 → 400 e encerramento gracioso |
| Rust novo depois da reconciliação | referência 1.400 restaurada; saldo 400 → 500 e dois endpoints |

Os fontes originais vieram de `git archive` dos commits fixados, com identificação
verificada no próprio arquivo: PHP `8b88f4c8182eb3d3912ffef425c3224dcfd596f4` e Rust
`fcd189e9aebf07a12a1f8cc39500819c3870925b`. Os lockfiles foram preservados. Não houve
alteração nesses fontes. No PHP original, o teste executa o job e consumidores
reais por CLI; não constitui uma nova rodada HTTP da tag PHP.

Asserções cobrem interrupção entre lotes, reconexão PDO, duas conexões MySQL
disputando manutenção, preservação das filas, migração repetida, referência fora
de ordem, repetição de conclusão, endpoint expirado e reaplicação sem crédito.
A cadeia das tags originais usa um peer; não mede tempo de rollback de um swarm
grande, throughput nem transferência BitTorrent.

Evidências:

- `lab/dualstack/results/legacy-final-tests.txt`
- `lab/dualstack/results/legacy-php-roundtrip.txt`
- `lab/dualstack/results/legacy-original-http.json`
- `lab/dualstack/results/legacy-rust-roundtrip.txt`
- `lab/dualstack/checkpoint-legacy.json` (inclui o contrato Rust observado nesta execução)

Duas correções do harness foram necessárias e não alteraram o produto: criar o
mountpoint `.env` antes de montar o arquivo em diretório somente leitura; remover
o header de proxy herdado para o teste direto do Rust original. A primeira falha
impediu a inicialização do container; a segunda recusou o request antes do
processamento. O preflight confirmou saldo 300/referência 1.300 antes da repetição.

## Reprodução no laboratório

1. Sincronizar os arquivos candidatos e `lab/dualstack/*` para os diretórios
   correspondentes em `/opt/unit3d-dualstack` da VM tracker. Os scripts do laboratório
   ficam em `/opt/unit3d-dualstack/lab`, sem o subdiretório `dualstack`.
2. Executar `sudo bash /opt/unit3d-dualstack/lab/run-legacy-reconciliation.sh`.
   O argumento opcional `php` limita a rodada à suíte PHP. Esse script recria
   **somente o banco isolado**, portanto não executar junto a outros ensaios.
3. Exportar os dois commits com `git archive --format=tar`, verificar cada um com
   `git get-tar-commit-id`, extrair em `originals/UNIT3D` e
   `originals/UNIT3D-Announce` na VM tracker e gravar os hashes verificados em
   `originals/php.commit` e `originals/rust.commit`. As cópias são exclusivas deste
   ensaio. O vendor PHP da candidata é montado separadamente; os lockfiles não
   diferem da base.
4. Na VM tracker, executar `run-legacy-originals.sh php`, seguido de
   `run-legacy-originals.sh rust-start`, ambos com `sudo bash` e caminho completo.
5. Na VM clientes, copiar `legacy-original-http.py` ao lado de `baseline.py` e da
   fixture privada em `/opt/unit3d-dualstack`, então executar com `sudo python3`.
6. Só depois de o request passar, executar `run-legacy-originals.sh rust-finish`
   na VM tracker. O script encerra o original, confere drenagem, reconcilia e roda
   o teste da candidata. Guardar saída e código de retorno; ao usar `tee`, habilitar
   `set -o pipefail` para não esconder uma falha.

Todos os containers de announce deste ensaio foram encerrados. Permanecem como
próximos itens a transferência com clientes BitTorrent reais e a matriz completa
de performance/churn. Este resultado não autoriza implantação em produção.
