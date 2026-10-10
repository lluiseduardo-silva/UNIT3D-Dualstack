# Guia da documentação técnica

Estado consolidado em 10/10/2026. Os documentos antigos foram mantidos como registro cronológico, inclusive falhas, hipóteses e gates reprovados. Não reinterpretar uma aprovação funcional como aprovação de desempenho.

## Entrada e dados estruturados

| Documento | Conteúdo |
|---|---|
| [Resultados consolidados](resultados-consolidados.md) | Métricas, comparações válidas e limites |
| [Método e ambiente](metodologia-e-ambiente.md) | Hardware, versões, cargas, unidades e observação |
| [Arquitetura e contratos](arquitetura-e-contratos.md) | Identidade, endpoints, persistência e regras do site |
| [Problemas e correções](problemas-e-correcoes.md) | Origem dos defeitos, correções e evidências |
| [Testes e reprodução](testes-e-reproducao.md) | Suítes, análise offline e dependências de laboratório |
| [Entrega e proveniência](entrega-e-proveniencia.md) | Commits, fontes, patches, integridade e exclusões |
| [Limitações e pendências](limitacoes-e-pendencias.md) | O que ainda não foi demonstrado |
| [Métricas JSON](data/key-metrics.json) | Valores numéricos com unidade, perfil e fonte |
| [Matriz de validação JSON](data/validation-matrix.json) | Requisito → código/teste → artefato |
| [Inventário JSON](data/evidence-index.json) | Caminho, tamanho e SHA-256 de cada evidência distribuída |

## Relatórios de desempenho e recursos

| Etapa | Relatório | Evidências |
|---|---|---|
| Calibração e comparações iniciais | [Benchmarks](dualstack-benchmarks.md) | [benchmarks](../lab/dualstack/results/benchmarks/) |
| População por torrent e interferência | [Densidade](dualstack-densidade.md) | [density](../lab/dualstack/results/density/) |
| Gargalo de persistência | [Throughput](dualstack-throughput.md) | [throughput](../lab/dualstack/results/throughput/) |
| Cadência/lote e endpoints seletivos | [Escritor](dualstack-writer.md) | [writer](../lab/dualstack/results/writer/) |
| Inicialização em escala | [Bootstrap](dualstack-bootstrap.md) | [bootstrap](../lab/dualstack/results/bootstrap/) |
| TLS, origem e rotação/cache | [TLS e memória](dualstack-tls-memoria.md) | [tls-memory](../lab/dualstack/results/tls-memory/) |
| Seis horas do candidato corrigido | [Prolongado v3](dualstack-prolongado-v3.md) | [resumo](../lab/dualstack/results/soak/six-hours-v3-summary.json), [auditoria](../lab/dualstack/results/soak/six-hours-v3-accepted-samples-audit.json) |
| Três repetições do original | [Original formal](dualstack-rust-original.md) | [análise](../lab/dualstack/results/soak/rust-original-formal-v1/analysis.json) |
| Seis horas do original | [Original prolongado](dualstack-rust-original-prolongado.md) | [resumo](../lab/dualstack/results/soak/rust-original-six-hours-v1/summary.json) |
| CPU/RAM e experimento de cache | [Capacidade](dualstack-capacidade-recursos.md) | [A1/B/A2](../lab/dualstack/results/capacity/capacity-cache-ab-comparison.json) |

## Correção, integração e operação

- [Clientes BitTorrent reais](dualstack-clientes-reais.md): versões, handshake, transferência, hash e diagnóstico de bind.
- [Contadores e consumidores](dualstack-contadores.md): totais lógicos, preferências, BON e site.
- [Defeitos preexistentes](dualstack-problemas-preexistentes.md) e [reembolso concorrente](dualstack-reembolso-concorrencia.md).
- [Reprodução do timeout da lease](dualstack-lease-io.md) e [correção/recuperação](dualstack-recuperacao-lease.md).
- [Queda abrupta](dualstack-falha-abrupta.md): atomicidade confirmada e limite da fila volátil.
- [Retorno às versões originais](dualstack-rollback-legado.md): preparação, reconciliação e pré-condições.
- [Implementação PHP independente](dualstack-standalone.md): mantida no pacote; não equivale a benchmark PHP×PHP concluído.
- [Armazenamento/arquivo](dualstack-armazenamento.md) e [tentativas prolongadas anteriores](dualstack-prolongado.md).

## Planos e checkpoints

[Planos históricos](plans/) e [checkpoints do laboratório](../lab/dualstack/) preservam decisões, commits intermediários e autorizações da época. Endereços privados e caminhos do laboratório são referências do ambiente original, não destinos para execução automática. O manifesto inicial descreve a implantação inicial; ampliações e configurações efetivas estão nos relatórios e nas evidências de cada execução.

Este índice e o [README principal](../README.md) têm precedência para navegação e estado atual do pacote. Não foram repetidos ensaios para montar esta entrega.
