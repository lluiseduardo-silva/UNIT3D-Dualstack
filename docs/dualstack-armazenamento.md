# Armazenamento do laboratório para a campanha prolongada

Preparado em 08/10/2026, sem iniciar o teste de seis horas e sem alterar os
produtos PHP/Rust. Proxmox 9.2.10 já tinha `virtiofsd` 1.13.2 instalado; não foi
necessário instalar NFS, criar exports de rede ou aumentar discos das VMs.

## Disposição e capacidade

Dataset exclusivo: `storage_pool/unit3d-dualstack`, com **quota e reserva de
300 GiB**, compressão LZ4, `atime=off`, `sync=standard`, `exec/setuid/devices=off`.
Cada VM recebe somente seu dataset filho via VirtioFS:

| VM | Filho e tag | Montagem na VM |
|---|---|---|
| 120 — tracker | `tracker` / `unit3d-ds-tracker` | `/mnt/unit3d-archive` |
| 121 — dados | `data` / `unit3d-ds-data` | `/mnt/unit3d-archive` |
| 122 — clientes | `clients` / `unit3d-ds-clients` | `/mnt/unit3d-archive` |

Montagens persistentes em `/etc/fstab`. As três foram verificadas depois de um
novo desligamento/início das VMs, sem comandos manuais de montagem.
O diretório subjacente no SSD tem atributo imutável: sem VirtioFS, a criação de
resultados falha em vez de consumir silenciosamente o disco local. O `nofail`
permite que a VM inicie para diagnóstico mesmo se o compartilhamento falhar.

MySQL, redo, binlog ativo, Redis, fontes e executáveis continuam no SSD.
`/opt/unit3d-dualstack/results` aponta para o ZFS nas três VMs. Na VM de clientes,
`density-results` e `benchmarks` também foram direcionados para lá. Foram
conferidos 583 arquivos por SHA-256; os diretórios `*.before-zfs` conservam a
cópia anterior no SSD. Diretórios privados, fontes e experimentos não foram
movidos. A coleta futura deve escrever nessas saídas ou diretamente no ZFS;
arquivos temporários arbitrários e logs Docker não mudam de destino por isso.

| Medida | Antes | Depois |
|---|---:|---:|
| Livre na VM de dados | 7,62 GiB | 26,00 GiB |
| Livre no thin pool compartilhado | 17,00 GiB | 35,58 GiB |
| Uso do thin pool | 87,60% | 74,05% |
| Livre dentro da quota ZFS do laboratório | — | 297,38 GiB |

Após purgar arquivos já arquivados, `fstrim /` na VM 121 devolveu blocos ao thin
pool. Nenhum disco ou volume de outro projeto foi modificado. O arquivo inicial
contém aproximadamente 19,33 GiB lógicos de binlogs; a ocupação física é menor
pela compressão. O orçamento não depende dessa taxa de compressão se repetir.

## Arquivamento dos binlogs

`archive-binlogs.py` foi instalado em
`/usr/local/sbin/unit3d-archive-binlogs.py` na VM de dados. Um timer systemd
habilitado chama o serviço 15 segundos depois de cada execução, com até dois
arquivos por execução, cópia limitada a **32 MiB/s** e timeout de 180 segundos.
A drenagem inicial, com o banco sem carga, usou 128 MiB/s. Há exclusão por
`flock`; chamadas MySQL têm timeout de 30 segundos. A memória de cópia é limitada
por blocos de 1 MiB, independentemente do tamanho dos arquivos.

O arquivador exige hostname do laboratório, UUID MySQL esperado, montagem
VirtioFS com tag e marcador corretos e ausência de replicação. Essa política
serve exclusivamente a este laboratório sem réplicas, não a uma implantação
genérica com réplicas desconectadas ou consumidores externos de binlog.

Para cada arquivo fechado:

1. Confere o índice MySQL e exclui o binlog ativo da seleção.
2. Copia para arquivo parcial, limitando a velocidade e calculando SHA-256.
3. Confere tamanho, hash da cópia e estabilidade do arquivo de origem.
4. Executa `fsync` no arquivo, renomeia e sincroniza o diretório; grava e
   sincroniza também um manifesto com UUID, nome, tamanho e hash.
5. Reconfere servidor e índice; somente então usa `PURGE BINARY LOGS TO` para
   remover o prefixo confirmado. Nunca apaga arquivos diretamente do datadir.

O SQL mantém o índice de binlogs consistente, conforme a
[documentação do MySQL](https://dev.mysql.com/doc/refman/8.0/en/purge-binary-logs.html).
Uma reexecução verifica o arquivo existente; divergência interrompe a operação.
Se cair entre cópia e purga, o arquivo pode ser reutilizado. Se cair depois da
purga, o índice MySQL já não o seleciona. Manifestações de erro ficam no journal.

Foi desativada persistentemente **apenas a expiração automática por idade**
(`binlog_expire_logs_auto_purge=OFF`), para não concorrer com a verificação.
Os valores anteriores estão em `/etc/unit3d-binlog-archive.json`, privado.
Permanecem: binlog ON, ROW/FULL, `sync_binlog=1`,
`innodb_flush_log_at_trx_commit=1`, redo de 100 MiB e binlog máximo de 1 GiB.
O parâmetro de idade continua em 30 dias, mas está inativo. O ZFS não tem
limpeza automática: atingir o limite interrompe o arquivamento, sem purgar a
origem. Binlogs e credenciais não são exportados para o Git.

## Evidência de validação

- Gravação/leitura de 1 MiB e `fsync` em cada VM, com hashes iguais no host.
- Quatro controles reais: ausência de montagem, arquivo corrompido,
  exclusão concorrente e reexecução. Nenhum alterou o índice de binlogs.
- Oito testes automatizados, incluindo parcial interrompido, falha de escrita/
  sincronização injetada e rejeição de symlink. A falha de espaço é simulada;
  não foi preenchido o pool do host.
- Montagens, redirecionamentos, configuração MySQL e timer confirmados após
  reiniciar as três VMs. MySQL/Redis foram encerrados de forma limpa e iniciados
  manualmente, preservando sua política anterior `restart=no`.
- Snapshot de peer, endpoints, histórico, crédito e propriedade idêntico ao
  anterior. Nenhum tracker ou gerador de carga ficou em execução.

Teste curto de interferência: três pares de 25 segundos, 200 commits/s, uma
linha de 16 KiB no schema de testes. Cada cópia concorrente arquivou um binlog
de aproximadamente 1 GiB. A tabela de sonda foi removida ao terminar.

| Repetição | p95 sem/com cópia (ms) | p99 sem/com cópia (ms) |
|---|---|---|
| 1 | 4,03 / 5,03 | 4,69 / 6,35 |
| 2 | 4,55 / 4,46 | 30,59 / 5,57 |
| 3 | 4,41 / 4,96 | 24,82 / 27,95 |

Todos os 30.000 commits foram confirmados, sem erros e com aproximadamente
200 commits/s. O p95 mediano subiu **0,55 ms / 12,44%**. O p99 oscilou também
sem cópia; a amostra não sustenta afirmar que o arquivador melhora esse percentil.
Na terceira repetição, a leitura adicional no SSD foi 31,94 MiB/s; não houve
incremento de `Innodb_log_waits`, `Innodb_row_lock_waits` ou
`Innodb_buffer_pool_wait_free`.

**Isto valida funcionamento e capacidade de arquivo, não aprova o limite de
10% de latência do tracker.** Antes de seis horas, comparar a aplicação com e
sem arquivamento em uma carga curta representativa. Baseline e candidato devem
usar a mesma política de arquivo. A necessidade de ler binlogs no SSD permanece
mesmo com seu destino no ZFS; o teste não mediu o teto do pool ZFS.

## Operação e retorno

Na VM de dados:

```sh
sudo systemctl status unit3d-binlog-archive.timer
sudo journalctl -u unit3d-binlog-archive.service -n 30
sudo python3 /opt/unit3d-dualstack/lab/inspect-archive.py
```

Nas três VMs, antes de qualquer campanha:

```sh
sudo python3 /opt/unit3d-dualstack/lab/archive-preflight.py
```

O preflight exige pelo menos 200 GiB livres no arquivo, 20 GiB no SSD de dados
(2 GiB nos demais), montagem correta e, na VM de dados, timer ativo, estado
recente e menos de 2 GiB de binlogs fechados pendentes. Não inicia carga.

Para interromper a manutenção, parar primeiro o timer e aguardar o serviço
terminar. Se o arquivador for desativado permanentemente, restaurar pelo MySQL a
política anterior registrada no JSON; o SSD voltará a acumular binlogs pela
retenção antiga. Não usar `RESET MASTER` ou `rm` no datadir.

Antes de retirar VirtioFS, encerrar consumidores, copiar os resultados atuais
de volta para um destino com espaço e conferir hashes. Os backups `before-zfs`
não contêm resultados produzidos depois do redirecionamento. Retirar links e
entradas correspondentes do fstab; desmontar e remover o atributo imutável do
diretório subjacente. Desligar a VM antes de retirar o dispositivo. Configurações
originais das VMs: `/root/unit3d-dualstack-storage-before` no host. Os datasets
arquivados devem permanecer até haver decisão explícita sobre sua retenção.

## Próxima etapa registrada naquele checkpoint

O armazenamento está preparado. Antes da campanha longa ainda faltam:

- Coleta contínua com memória limitada: `density-http.py` atualmente acumula
  amostras em RAM e escreve o gzip no final. Essa estratégia não serve para
  seis horas na VM de 8 GiB.
- Guardas durante a carga para espaço livre, idade/backlog do arquivo e falhas
  do serviço, com interrupção da carga antes de esgotar o SSD. O preflight atual
  verifica somente o início, não substitui esse monitor.
- Ensaio curto do gerador adaptado e da aplicação com arquivo ativo, antes de
  autorizar pela validação o início das seis horas.

Fontes reproduzíveis em `lab/dualstack/*archive*`, `storage-commit-probe.py`;
saídas brutas e hashes em `lab/dualstack/results/storage`; checkpoint em
`lab/dualstack/checkpoint-storage.json`. Nenhum push ou uso de produção.

A continuidade desses preparativos e da execução autorizada está registrada
em [dualstack-prolongado.md](dualstack-prolongado.md) e
`lab/dualstack/checkpoint-soak.json`. As pendências acima descrevem a situação
histórica do checkpoint de armazenamento, não o estado posterior da campanha.
