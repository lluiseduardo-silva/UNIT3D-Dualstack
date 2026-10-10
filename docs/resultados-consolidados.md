# Resultados consolidados — 10/10/2026

Esta síntese separa versão original, candidato dual-stack e experimentos intermediários. Os relatórios vinculados contêm configuração, séries, incidentes e artefatos. Os [valores estruturados](data/key-metrics.json) permitem consulta sem extrair números da prosa.

## Estado por dimensão

| Dimensão | Evidência concluída | Limite |
|---|---|---|
| Identidade e contabilidade | Contratos unitários/integração, concorrência, clientes reais e auditoria final dos ensaios | Não é prova formal de ausência de qualquer defeito |
| Dois caminhos | IPv4/IPv6 reais, respostas, stopped, expiração, rotação e restart | Sem tradução entre famílias incompatíveis |
| Rollback | Retorno aos componentes originais e reativação com reconciliação | Ensaio funcional com um peer; não mede janela de manutenção de grande swarm |
| Estabilidade Rust | Original e candidato completaram seis horas nos respectivos perfis | Perfis não equivalentes; não aprova regressão global de 10% |
| Capacidade | Rampas, confirmações e diagnóstico de memória/cache | Matriz geral incompleta; nenhuma fórmula universal de IOPS |
| Cache B | A1/B/A2 concluído e auditado | Experimental, não incorporado; uma confirmação de B reprovou estabilidade |
| PHP | Código, suites e validação funcional incluídos | Comparação de desempenho PHP×PHP não concluída |

## Seis horas: estabilidade e consistência

| Métrica | Candidato corrigido | Original 0.3.1 |
|---|---:|---:|
| Execução | `soak-rust-six-hours-v3` | `rust-original-six-hours-v1` |
| Identidades | 10.000 | 10.000 |
| Endpoints do perfil | 20.000, IPv4 + IPv6 | 10.000, IPv4 legado |
| Announces aceitos | 171.427.236 | 175.346.000 |
| Principais / controle ou renovação | 170.004.515 / 1.422.721 | 175.200.000 / 146.000 |
| Erros de request | 0 | 0 |
| Crédito esperado e confirmado (bytes) | 8.500.225.800 | 17.520.000.000 |
| Divergências contábeis finais | 0 | 0 |
| Throughput mínimo / mediano nas janelas (req/s) | 7.999,20 / 7.999,95 | 7.999,93 / 7.999,99 |
| Mediana dos p95 por janela (ms) | 0,246 | 0,352 |
| Mediana dos p99 por janela (ms) | 0,330 | 0,475 |
| RSS Rust, intervalo das medianas horárias (MiB) | 32,15–33,20 | 26,95–27,92 |
| RSS Rust, pico amostrado (MiB) | 125,31 | 38,61 |

O candidato retornou a 32,89 MiB após o pico, coincidente com atraso de persistência; não houve crescimento acumulativo observado. A diferença máxima amostrada chegou a 89.007 versões, recuou e terminou em zero. Inclui defasagem dos observadores, não mede exatamente a fila interna. Houve uma versão adicional legítima de expiração, restrita ao peer de controle; não impor `soma(state_version) == requests` nesse cenário.

O IPv6 de controle expirou aos 7.221 s (TTL 7.200 s), mantendo 10.000 identidades com 19.999 endpoints; foi restaurado por announce. No original, renovações sem tráfego não geram crédito; multiplicar todos os aceitos por 100 seria incorreto.

**Não calcular ganho de velocidade a partir das duas colunas.** Há diferenças de família, crédito, payload, manutenção, duração das janelas e estado do host. Os percentis são medianas por janela, não globais. No original houve aumento do p99 resumido de aproximadamente 32% entre primeira e última hora, sem causa física isolada. A checagem de conectividade estava desligada nos dois ensaios.

Fontes: [candidato](dualstack-prolongado-v3.md), [original](dualstack-rust-original-prolongado.md), [resumo candidato](../lab/dualstack/results/soak/six-hours-v3-summary.json), [replay candidato](../lab/dualstack/results/soak/six-hours-v3-accepted-samples-audit.json), [resumo original](../lab/dualstack/results/soak/rust-original-six-hours-v1/summary.json), [análise original](../lab/dualstack/results/soak/rust-original-six-hours-v1/analysis.json).

## Custo de escrita: controles intermediários

Os números seguintes são de etapas anteriores às últimas otimizações. Não representam um novo comparativo do snapshot final.

| Perfil inicial, 1.000 peers / 50% dual-stack | Escritas/s na VM | MiB/s escritos | Redo MiB/s |
|---|---:|---:|---:|
| Original, flush 3 s | 118–133 | 2,15–2,28 | 0,157–0,158 |
| Original, controle com flush 100 ms | 476 | 5,54 | 0,524 |
| Candidato, tick 100 ms | 432–497 | 7,36–7,69 | 1,54–1,55 |

A frequência explica parte da amplificação. Mesmo no controle de 100 ms, o redo do candidato ficou aproximadamente 2,95× maior. Mudaram versões, transações, estado de protocolo e agregação, além dos endpoints. Em 54 mil peers distribuídos, a escrita observada foi 6,34 MiB/s original e 10,86 MiB/s candidato, com 327 e 612 escritas/s. Fonte: [benchmark e I/O](dualstack-benchmarks.md).

A persistência seletiva posterior, comparada à cadência já corrigida do próprio candidato a 8 mil/s, reduziu redo de 7,94 para 6,58 **MB/s** (-17,1%), escrita de 36,94 para 34,13 **MiB/s** (-7,6%) e tempo médio de lote de 51,47 para 46,37 ms (-9,9%). Não misturar MB com MiB nem interpretar essa redução como retorno ao custo original. Fonte: [escritor](dualstack-writer.md).

## Throughput e gargalo

O escritor inicial confirmava cerca de 2 mil transições/s com lote 200 e timer 100 ms, mesmo recebendo mais. Após correção de cadência e endpoints, a mediana de confirmação sob oferta de 12 mil/s chegou a aproximadamente 10.289/s, com fila crescendo 1.184–1.921/s: **12 mil/s não eram sustentáveis**. São janelas curtas; valores acima da oferta numa janela podem representar drenagem do warmup.

Perto desse limite, o escritor serial passou quase todo o tempo nos lotes de 500 (~49 ms). Exemplo de decomposição: endpoints 13,85 ms; deltas 11,38; commit 6,29; peers 5,81; leitura/fencing 5,38; histórico 5,13. São tempos de etapas, não CPU SQL isolada. Espera média dos mutexes de publicação/seleção ficou abaixo de 0,1 µs. HTTP direto exclui Nginx desse gargalo, e Redis não participa desse caminho Rust.

Um controle posterior de 8.000 req/s por 180 s mediu 33,24 MiB/s, 2.080 escritas/s e 691 flushes/s na VM. Escrita/flush médios: 0,368/0,460 ms. Não define a capacidade de outro SSD. Fonte: [lease/I/O](dualstack-lease-io.md).

## Densidade e bootstrap

| Peers no torrent alvo | Mediana de p99 das repetições (ms) |
|---:|---:|
| 50 | 0,2390 |
| 150 | 0,2454 |
| 250 | 0,2483 |
| 1.000 | 0,2555 |
| 2.500 | 0,2745 |
| 5.000 | 0,3155 |
| 10.000 | 0,4038 |
| 20.000 | 0,5836 |
| 40.000 | 1,1346 |

Controle exploratório a 1.000 req/s; não é teto sustentado. População, densidade e taxa são eixos separados: 54 mil peers não significa 54 mil req/s nem um limite intrínseco. Método e interferência entre torrents em [densidade](dualstack-densidade.md), com [análise da curva](../lab/dualstack/results/density/density-curve-v1-analysis.json).

Após a correção do carregamento: 54 mil peers inicializaram em 1,69–1,91 s; 100 mil peers/200 mil endpoints, em 2,81–3,38 s. Foram 18 inicializações cobrindo concentração/distribuição. [Bootstrap](dualstack-bootstrap.md) e [JSON](../lab/dualstack/results/bootstrap/summary.json).

## Capacidade por recursos e cache A1/B/A2

A matriz inicial parou no banco 1 vCPU/2 GiB quando `MemAvailable=251,422 MiB`, abaixo do piso 256 MiB. A rodada estava no aquecimento; não possui percentis medidos. Foram preservados 38.646 announces e crédito exato, drenagem 0,735 s e nenhum OOM. Não é evidência de falha causada pelo SSD nem certificado de impossibilidade de operação com 2 GiB.

O diagnóstico subsequente usou banco 1 vCPU/4 GiB, pool 128 MiB e durabilidade 1/1. A1 e A2 são o candidato `36823b5`; B acrescenta `.persistent(false)` a oito consultas dinâmicas. **Nenhuma coluna é Rust original.** Cada série teve 5.550.000 announces e crédito 277.523.200 bytes, sem erros/divergências finais; total 16.650.000 em 27 rodadas.

| Métrica da série | A1 | B experimental | A2 |
|---|---:|---:|---:|
| Pico RSS MySQL (MiB) | 1.245,75 | 559,86 | 1.389,38 |
| Pico memória de prepared statements (MiB) | 488,14 | 8,18 | 490,32 |
| Pico de statements | 301 | 20 | 301 |
| Preparações | 63.527 | 147.681 | 61.219 |
| Execuções | 125.255 | 124.630 | 125.388 |
| CPU MySQL, confirmações 1/2 (% de um núcleo) | 65,44 / 65,20 | 70,46 / 70,91 | 63,72 / 62,98 |
| CPU Rust, confirmações 1/2 (% de um núcleo) | 36,46 / 36,45 | 39,90 / 40,18 | 36,55 / 36,35 |
| p99 HTTP, confirmações 1/2 (ms) | 0,3586 / 0,3590 | 0,3608 / 0,3644 | 0,3648 / 0,3575 |
| Escrita na VM, confirmações 1/2 (MiB/s) | 26,10 / 25,79 | 26,06 / 26,09 | 25,97 / 25,86 |

B reduziu pico RSS em 55,1–59,7%, com mais 5,0–7,9 pontos de CPU de um núcleo no MySQL e 3,4–3,8 no Rust. Não reduziu materialmente disco. Uma confirmação a 5.500/s e a rampa 6.000/s reprovaram o detector de estabilidade; todas drenaram com integridade. Logo, não se aprova 5.500/s sustentados em B com esse banco.

RSS retido após encerramento das conexões é compatível com retenção/fragmentação do alocador, não prova vazamento ilimitado. Performance Schema ocupou aproximadamente 230 MiB. Sem novas leituras físicas InnoDB nas confirmações, a base aquecida não avalia pool insuficiente numa população maior. [Relatório integral](dualstack-capacidade-recursos.md), [comparação JSON](../lab/dualstack/results/capacity/capacity-cache-ab-comparison.json), [patch B](../lab/dualstack/capacity-cache-b.patch).

## Payload e validade das conclusões

Para o mesmo conjunto selecionado: 6 B por IPv4, 18 B por IPv6, até 24 B dual-stack. A lista pode crescer 300% frente à IPv4 (4×), além do envelope. O original com listener `::` publicou IPv4 mapeado em `peers6` em parte do baseline; essa diferença deve acompanhar qualquer comparação de bytes.

Critérios planejados: p95/p99 ≤1,10× e throughput ≥0,95× sob perfil equivalente. Não foram universalmente aprovados. O [estado de pendências](limitacoes-e-pendencias.md) impede converter medições parciais em homologação completa.
