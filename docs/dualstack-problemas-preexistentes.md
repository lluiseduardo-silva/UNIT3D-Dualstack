# Correções independentes do dualstack

Registro de 09/10/2026. Separar a origem do defeito da ocasião em que ele foi
encontrado. Os três primeiros casos abaixo pertencem ao UNIT3D PHP, inclusive
quando o site usa Rust para announces. Não atribuir esses ganhos ao desempenho
do Rust original. Nenhuma dessas correções será aplicada à tag usada como baseline.

## Defeitos preexistentes confirmados

| Problema e reprodução | Correção | Evidência e limite |
|---|---|---|
| Filas legadas removiam itens ainda não processados. Um produtor acrescentava outro item depois de `LRANGE`; `LTRIM` removia o máximo do lote (4.062), em vez da quantidade realmente lida. | PHP `6d8e7437daa652fb02519584c456b15dceacffa4`: remover somente `count($peers)` / `count($histories)`. Código atual: `app/Console/Commands/AutoUpsertPeers.php:96` e `AutoUpsertHistories.php:113`. | Reprodução dos dois consumidores em `tests/Integration/LegacyBatchQueueTest.php`. [Original com divergência contábil](../lab/dualstack/results/benchmarks/php-original-20261008T151512.json), [controle original com apenas esses consumidores corrigidos](../lab/dualstack/results/benchmarks/php-legacy-fixed-20261008T152541.json). O controle recebeu 180.000 bytes corretamente. Não confundir `legacy-fixed` com a tag intacta; a correção não transforma a fila legada num journal idempotente para crashes. |
| Reembolso de dois torrents do mesmo usuário: os históricos registravam 2.000 bytes reembolsados, mas o saldo caía de 10.000 para 9.000, em vez de 8.000. O `UPDATE` com joins e `@delta` não somava as linhas por usuário. | PHP `b380d2f69`: `App\Services\DownloadRefund` soma deltas inteiros por usuário; protege usuários e históricos em ordem, reavalia elegibilidade e confirma o lote atomicamente. Código: `app/Services/DownloadRefund.php:70`. | [Falha original](../lab/dualstack/results/site-history-consumers.txt), [testes corrigidos](../lab/dualstack/results/refund-final-tests.txt), [concorrência Rust/PHP](../lab/dualstack/results/refund-rust-contention.txt). O arquivo antes da correção era idêntico ao da tag: blob `ef9cadfc9b8f9bf39c1a7f379457de1ab44badd9`. Não recompõe valores históricos já marcados incorretamente. [Método, riscos de lock e medições](dualstack-reembolso-concorrencia.md). |
| Estatísticas de clientes selecionavam `agent` sem agrupá-lo na consulta por prefixo. MySQL com `ONLY_FULL_GROUP_BY` recusava com erro 1055. | PHP `c55e8a4fd`: retirar a coluna não usada nesse agrupamento; preservar a consulta por versão. Código: `app/Http/Controllers/StatsController.php:358`. | [Reprodução e erros](../lab/dualstack/results/site-history-consumers.txt); teste de regressão em `tests/Integration/DualstackSiteConsumersTest.php`. Blob anterior idêntico à tag: `68d561ce1ad5a0da1c7762245439de8d51822f08`. Falha reproduzida com o código idêntico, não com uma instalação integral independente da tag. |

Os hashes curtos de correção identificam commits do repositório aninhado
`repos/UNIT3D`. Os caminhos de código da tabela são relativos a esse projeto.
Os artefatos acima são históricos; esta documentação não os apresenta como
novas execuções de 09/10.

## Risco da consulta BON legada, com limite de atribuição

O controle com a consulta BON legada produziu **22 deadlocks**, contra 27 na
consulta que também lia endpoints. Os dois ensaios usavam os gravadores
dualstack novos. O extrato [bon-locks.json](../lab/dualstack/results/bon-locks.json)
mostra inversão entre `users` e `torrents`. Isso confirma o risco da consulta
legada nesse cenário; **não prova a mesma incidência com todos os gravadores
originais** e não deve ser contado como reprodução integral do UNIT3D 9.2.0.

PHP `58b7d804e4f25be738abca194be573864e09f3e5` separou leitura agregada e escrita
de saldos, ordenando usuários e preservando transação, decimais e retry.
[Funcional: 90 testes/978 asserções](../lab/dualstack/results/bon-lock-fix-functional.txt),
[controle legado corrigido](../lab/dualstack/results/bon-lock-fix-legacy-control.txt)
e [Rust/PHP](../lab/dualstack/results/bon-rust-contention-fixed.txt): créditos
exatos e zero novos deadlocks/timeouts. Nenhuma fórmula BON por família foi criada.

## Casos que não entram na lista de defeitos originais corrigidos

- Lease/persistência da execução prolongada v2: defeito do coordenador novo,
  corrigido no Rust `36823b5`; [diagnóstico e v3](dualstack-prolongado-v3.md).
- Custo de seleção de peers no candidato dualstack: regressão da implementação
  nova, posteriormente otimizada; não atribuir ao código original.
- Inventário de binlogs da v1, interpretação do número de escritores SQL,
  configuração de rate limit no gerador e falha Windows em `os.O_DIRECTORY`:
  problemas ou limitações do laboratório, não defeitos do tracker original.
- Filas independentes de peers/históricos/usuários no Rust original: limitação
  arquitetural relevante para atomicidade, mas não a apresentar aqui como perda
  reproduzida em crash sem um ensaio específico e seus resultados.
- O aviso de depreciação `fetch_update` existe na compilação original; não foi
  corrigido nem implica falha funcional demonstrada.

## Comparações de desempenho

O ensaio prolongado do original também expôs IPv4 mapeado em `peers6` após
renovação, com listener `::`. [Reprodução e limites](dualstack-rust-original-prolongado.md)
distinguem o comportamento do produto da expectativa incorreta do auditor.
O candidato normaliza a origem em `repos/UNIT3D-Announce/src/dualstack/peer.rs:110`.
O comportamento da tag é preexistente, mas não foi demonstrada falha de
transferência em cliente real neste cenário; não contabilizar como tal.

Comparar a tag original intacta com o candidato mede o conjunto da alteração,
incluindo os diferentes mecanismos de persistência. Controles com apenas uma
correção são experimentos adicionais, nomeados separadamente. Não remover um
defeito do baseline silenciosamente nem usar sucesso HTTP como prova de crédito.
