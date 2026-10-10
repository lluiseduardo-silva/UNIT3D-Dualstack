# Testes, cobertura funcional e reprodução

As mudanças funcionais e correções são acompanhadas de testes unitários e/ou de integração, além dos cenários de rede e carga. Isso é cobertura de regras e fluxos; não se apresenta um percentual medido de cobertura de linhas. Suítes de datas distintas podem se sobrepor: não somar suas contagens como testes únicos.

## Mapa verificável

| Área | Testes/código | Execução e evidência |
|---|---|---|
| Schema, backfill e restrições | [PHP schema](../repos/UNIT3D/tests/Integration/DualstackSchemaTest.php) | [schema](../lab/dualstack/results/schema/), 8 testes / 38 asserções no checkpoint |
| Transições e paridade | [fixture comum](../lab/dualstack/fixtures/peer-v1.json), [Rust](../repos/UNIT3D-Announce/tests/dualstack_contract.rs), [PHP](../repos/UNIT3D/tests/Integration/DualstackPeerContractTest.php) | 12 casos / 51 operações; [contrato](../lab/dualstack/results/contract/) |
| MySQL, retries, crédito e recuperação | [Rust MySQL](../repos/UNIT3D-Announce/tests/dualstack_mysql.rs), [support](../repos/UNIT3D-Announce/tests/support/), [PHP journal](../repos/UNIT3D/tests/Integration/DualstackJournalTest.php) | [lease recovery](../lab/dualstack/results/lease-recovery/), incluindo locks reais, reentrega após commit e perda de propriedade |
| BON, reembolso e consumidores | [integração PHP](../repos/UNIT3D/tests/Integration/), [Rust BON](../repos/UNIT3D-Announce/tests/dualstack_bon.rs), [Rust refund](../repos/UNIT3D-Announce/tests/dualstack_refund.rs) | [contadores](dualstack-contadores.md), [reembolso](dualstack-reembolso-concorrencia.md) |
| Limpeza, exclusão e handoff | [Rust deletion](../repos/UNIT3D-Announce/tests/dualstack_deletion.rs), [handoff](../repos/UNIT3D-Announce/tests/dualstack_handoff.rs) | [checkpoint de exclusão](../lab/dualstack/checkpoint-deletion.json), [handoff](../lab/dualstack/checkpoint-handoff.json) |
| Rollback/reconciliação | [PHP legacy](../repos/UNIT3D/tests/Integration/DualstackLegacyTest.php), [Rust legacy](../repos/UNIT3D-Announce/tests/dualstack_legacy.rs) | [relatório](dualstack-rollback-legado.md), 40 testes / 593 asserções PHP e contrato Rust, além de originais reais |
| Clientes reais | [harness](../lab/dualstack/real-clients.py) | [oito cenários Rust](dualstack-clientes-reais.md), [JSONs](../lab/dualstack/results/real-clients/) |
| Proxy/TLS/cache | [Rust rede](../repos/UNIT3D-Announce/src/dualstack_network.rs), [PHP proxy](../repos/UNIT3D/tests/Integration/DualstackProxyTest.php) | [39 testes PHP / 493 verificações e 19 Rust](dualstack-tls-memoria.md) |
| Bootstrap | [Rust bootstrap](../repos/UNIT3D-Announce/tests/dualstack_bootstrap.rs) | [18 inicializações e conferências SQL](../lab/dualstack/results/bootstrap/summary.json) |
| Queda abrupta | [runner SIGKILL](../lab/dualstack/run-rust-crash.py) | [relatório e dois controles](dualstack-falha-abrupta.md) |
| Instrumentos | [test_capacity_metrics.py](../lab/dualstack/test_capacity_metrics.py), [test-soak.py](../lab/dualstack/test-soak.py), [test-rust-comparison.py](../lab/dualstack/test-rust-comparison.py) | Calibração, alinhamento temporal, oráculo do original e limites de plataforma documentados |

A [matriz JSON](data/validation-matrix.json) oferece caminhos por requisito. Logs do repositório comprovam as execuções históricas, não execução automática na máquina do leitor. O pacote contém os testes; não baixa dependências, conecta a serviços ou executa carga ao ser aberto.

## 1. Verificar o pacote offline

```sh
python tools/verify-package.py
```

Verifica conteúdo, hashes e referências de entrada. Os bytes das evidências são preservados; para código/documentação, conversão LF/CRLF de checkout é reconhecida. Pacotes e patches permitem verificar os fontes sem depender dos commits históricos em um clone deste repositório de commit único.

## 2. Recalcular análises públicas sem acessar infraestrutura

Os comandos abaixo usam apenas arquivos locais e não executam benchmarks. Direcione saídas novas para fora dos artefatos originais.

```sh
python lab/dualstack/summarize-soak.py lab/dualstack/results/soak/soak-rust-six-hours-v3
python lab/dualstack/summarize-soak.py lab/dualstack/results/soak/rust-original-six-hours-v1
python lab/dualstack/analyze-original-soak.py lab/dualstack/results/soak/rust-original-six-hours-v1
python lab/dualstack/compare-capacity-cache.py lab/dualstack/results/capacity /caminho/novo/cache-comparison.json
```

Para conferir automaticamente essas reanálises contra os resultados preservados e aplicar os dois patches às bases originais, execute:

```sh
python tools/recheck-evidence.py --output .local/evidence-recheck.json
```

Esse comando requer Python 3.9+ e Git. Cria uma área nova em `.local/`, preserva os artefatos originais e compara as árvores Git reconstruídas com o manifesto. Não conecta a serviços, instala dependências ou executa carga.

`summarize-soak.py` escreve JSON em stdout. Scripts históricos que escrevem `summary.json` ou `manifest.json` no próprio diretório devem ser usados numa cópia dos dados, para preservar o registro original. A [proveniência](entrega-e-proveniencia.md) explica limites dos manifestos antigos e o inventário completo desta entrega.

As amostras integrais dos soaks e snapshots privados ficaram no ZFS do laboratório. Seus hashes, cardinalidades e resultados de replay estão incluídos, mas **não é possível refazer offline aquele replay integral somente com este pacote**. Séries públicas de observadores, janelas e resumos permitem reproduzir a análise de recursos e throughput. Amostras públicas comprimidas de ensaios curtos foram mantidas.

## 3. Executar testes do produto em ambiente descartável

O alvo validado é Linux com as versões/imagens registradas. Usar [lockfiles](../repos/UNIT3D-Announce/Cargo.lock), [imagens](../lab/dualstack/images.env), MySQL 8.0.46 e Redis 7.2.16. Os runners `run-*.sh` documentam dependências e nomes dos bancos de teste. Não apontá-los para banco real: alguns recriam fixtures e bancos de laboratório.

No Rust, a suíte rápida pode ser invocada no diretório do produto com `cargo test --locked --lib`. Testes ignorados que exigem serviços não estão cobertos por esse comando; a execução completa exige os runners com MySQL/configuração adequados. [Runner de recuperação](../lab/dualstack/run-lease-recovery-tests.sh), [MySQL](../lab/dualstack/run-rust-mysql.sh), [contrato](../lab/dualstack/run-rust-contract.sh), [bootstrap](../lab/dualstack/run-bootstrap-scale.sh) e [rollback](../lab/dualstack/run-legacy-reconciliation.sh) são pontos de entrada.

O PHP usa testes em `tests/Integration`, serviços reais e os helpers de preparação. Consultar [standalone](dualstack-standalone.md), [migrações e contrato](arquitetura-e-contratos.md). A independência do PHP foi validada sem Rust, mas não confundir essa suíte funcional com benchmark PHP×PHP concluído.

## 4. Reproduzir o laboratório e cargas

O [guia do laboratório](../lab/dualstack/README.md) registra provisionamento, redes e baseline inicial. Caminhos `/opt/unit3d-dualstack`, `/storage_pool/...`, VMs 120–122 e IPs privados são valores daquele ambiente; revisar antes de provisionar. Credenciais/fixtures privadas devem ser geradas localmente. Não reutilizar identificadores de uma execução existente.

Os snapshots distribuídos em `repos/` não possuem histórico próprio. Helpers que chamam `git archive <commit histórico>` exigem uma cópia de desenvolvimento separada com as bases e patches, ou adaptação explícita para os arquivos em `packages/`. Não assumir que `git rev-parse HEAD` dentro de `repos/` retorna o commit upstream: num clone deste pacote, retorna o commit da coordenação.

A ordem de gates é calibração → funcional → carga curta → confirmação → prolongado. Preservar falhas e estado, drenar filas, verificar crédito por identidade e restaurar recursos. O [procedimento de rollback](dualstack-rollback-legado.md) é separado de um reset de fixture.
