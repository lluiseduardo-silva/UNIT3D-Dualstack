# Reembolso e concorrência — checkpoint de 8 de outubro de 2026

As correções são independentes da habilitação de dualstack. O comando diário
`auto:refund_download` passou a chamar `App\Services\DownloadRefund`; não há
migração ou configuração de produção adicional. A consulta de estatísticas
de clientes deixa de selecionar `agent` no agrupamento por prefixo, onde esse
campo não era utilizado. A consulta por versão continua selecionando `agent`.

## Como o reembolso é confirmado

1. Enumerar até 100 pares `(user_id,torrent_id)` elegíveis, sem locks, em ordem
   da chave composta. A paginação não usa OFFSET nem carrega o histórico inteiro.
2. Iniciar transação e obter locks de usuários ordenados, depois dos históricos
   daquele lote, compatíveis com a ordem dos gravadores PHP e Rust.
3. Reavaliar filtros e referência após obter proteção. A consulta com joins de
   torrents/grupos é uma leitura consistente, sem `FOR UPDATE` sobre essas tabelas.
4. Calcular a meta acumulada usando a fórmula existente, convertê-la para bytes
   inteiros no MySQL e subtrair a referência anterior. Somar esses deltas por
   usuário e descontar do saldo corrente, com limite inferior zero.
5. Atualizar as referências dos históricos e confirmar junto com os saldos.
   O comando é dono dessas transações; não envolvê-lo numa transação externa.

Não há conversão de bytes para float em PHP, nem variável de sessão `@delta`.
O tipo `DOUBLE` legado de `torrents.size` não foi migrado: preserva-se a expressão
existente antes da conversão final para inteiro. O mesmo inteiro alimenta saldo
e histórico, evitando arredondamentos independentes. Redução legítima da meta
continua produzindo delta negativo, como na fórmula anterior.

Cada lote é atômico. Uma interrupção entre lotes deixa os anteriores confirmados;
reexecutar retoma sem desconto duplicado. Conflitos transitórios 1205/1213 ou
SQLSTATE 40001 têm cinco tentativas por lote, com espera de 25/50/100/200 ms fora
da transação. Outras falhas e esgotamento do retry são propagados. Não há lock
global de todo o tracker, mas os usuários envolvidos podem bloquear temporariamente
a persistência de announces. Isso foi medido, não presumido inexistente.

Históricos já marcados como reembolsados pelo bug antigo não permitem inferir
quanto deixou de ser abatido no saldo. Este patch não tenta corrigir retroativamente
esses valores. O critério de reseed e a semântica de “Single Seeds” não mudaram.

## Executar os gates de banco

Copiar os arquivos dos três repositórios para seus diretórios do laboratório,
preservando `.env` e dependências. Os runners exigem o host `unit3d-ds-tracker`,
trackers parados e banco `unit3d_dualstack_journal_test`. Não usar produção.

```bash
sudo bash /opt/unit3d-dualstack/lab/run-site-consumer-tests.sh
sudo bash /opt/unit3d-dualstack/lab/run-refund-contention-tests.sh
sudo bash /opt/unit3d-dualstack/lab/run-refund-rust-tests.sh
```

Executar sequencialmente: compartilham fixtures. O primeiro contém 31 testes;
o segundo força 16 processos sobre as mesmas chaves; o terceiro coordena o
Rust real com oito jobs PHP. As barreiras verificam esperas no InnoDB antes
de liberar os processos. Todos verificam crédito; os concorrentes verificam
também deadlocks/timeouts e reentrega. Rust tem quatro tarefas de persistência
com um único gravador SQL, totalizando nove concorrentes com os oito jobs.

## Reproduzir o ensaio HTTP curto

O host de clientes precisa de Python 3 e `pymysql`, já presentes no laboratório.
Não há nova dependência de produção. Os arquivos privados `fixture.json` e
`database.env` são lidos localmente; não entram no relatório. O gerador não
registra URLs/passkeys. As conexões usam endereços de origem reais, sem headers
que simulem IPs. O perfil concentra 36 peers em dois torrents; não representa
uma população de 54 mil peers nem transferência BitTorrent.

No tracker, com os backends parados, executar `refund-load.php prepare` em
`unit3d-ds-php:baseline`, com `DB_DATABASE=unit3d_dualstack_journal_test`, mounts
do UNIT3D em `/app` e do laboratório em `/lab`. Isso recompõe somente o banco
de ensaio, incluindo 12 históricos elegíveis. Iniciar o backend escolhido
com `start-candidate-rust.sh resume direct` ou `start-candidate-php.sh resume`.

Nos clientes, para PHP:

```bash
sudo bash /opt/unit3d-dualstack/lab/prepare-refund-sources.sh add
sudo python3 /opt/unit3d-dualstack/lab/refund-http-load.py \
  --backend php --profile without-refund --rate 1000 --seconds 20 --warmup 5 \
  --source-offset 0 --output /opt/unit3d-dualstack/results/refund-control.json
```

Para a segunda execução, iniciar no tracker um container do mesmo PHP, rede
host, banco e mounts acima, executando `sh -c 'sleep 7; php /lab/refund-load.php
work 28'`. Iniciar imediatamente o gerador com `--profile with-refund`,
`--source-offset 36` e outro arquivo de saída. Os sete segundos permitem que
o primeiro desconto real coincida com a janela medida. Os jobs seguintes
exercitam reentrega. O runner Rust de carga pode usar `--source-offset -1`
(padrão), sem aliases, e taxas de 1.000 ou 2.000; o controle e seu par devem
usar a mesma configuração. Não concorrer com outras suítes ou compilações.

As execuções comparadas reutilizam a população e aumentam os contadores.
O segundo ensaio Rust, a 2.000 req/s, já tinha a meta reembolsada: os jobs
exercitaram releitura/locks e idempotência. O primeiro, a 1.000 req/s, e o
ensaio PHP incluíram desconto real durante tráfego.

No final, aguardar o job e conferir seu exit code; parar e drenar o backend;
remover seu container e executar `prepare-refund-sources.sh remove` no host de
clientes. A lista registra somente os aliases que esse script adicionou.

## Evidências e alcance

Resultados detalhados no [plano de execução](plans/2026-10-08-dualstack-execucao.md),
com dados brutos em `lab/dualstack/results/refund-*.json` e `.txt`.

| Perfil | Req/s controle → reembolso | p99 controle → reembolso |
|---|---:|---:|
| Rust, meta 1.000 | 1.000 → 1.000 | 0,262 → 0,264 ms |
| Rust, meta 2.000 | 2.000 → 1.999,95 | 0,293 → 0,297 ms |
| PHP, meta 1.000 | 213,4 → 209,4 | 223,117 → 221,957 ms |

VMs de quatro vCPUs e 8 GiB; MySQL 8.0.46, Redis 7.2.16, PHP 8.4.26 e Rust
1.99.0. Imagens em `lab/dualstack/images.env` e `Dockerfile.php`. O PHP usou
FPM/configuração do laboratório e tracing de transições; Rust usou build release
e perfil direto. Cada backend é comparado ao próprio controle. Sem alteração
de pool ou otimização de runtime neste incremento.

O PHP preservou 98,13% do throughput do controle e não demonstrou 1.000 req/s.
O gerador limita requests em voo a 36 e registra agendamentos que não conseguiu
oferecer; não os conta como requests aceitos. A referência de 250 req/s do
criador foi informada pelo usuário e não foi reproduzida no mesmo ambiente.
Não concluir regressão comparando esses ambientes.

Os seis perfis aprovados tiveram zero erro, saldos corretos e persistência
conferida. O backlog é estimado por respostas reconhecidas menos versões SQL,
amostrado a cada 500 ms. Nos arquivos desta execução, `drain_seconds` começa
depois de encerrar o amostrador: é tempo da conferência, não latência total
de drenagem desde o último request. A prova de perda em crash não foi repetida.

Preservados dois resultados inválidos do harness: lote Rust maior que o máximo
aceito e carga PHP com 429 por concentrar clientes em dois IPs. Não contam como
aprovação; o código/limites do produto não foram alterados para ocultá-los.

Faltam a matriz de performance completa, população maior, aquecimento longo,
três repetições, teste de seis horas, rollback original e clientes BitTorrent
com transferência. Estes números validam este ajuste sob os perfis descritos.
