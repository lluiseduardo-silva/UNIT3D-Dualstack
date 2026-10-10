# Limitações e pendências da entrega

Estado do pacote em 10/10/2026; não é uma autorização de implantação.

| Item | Estado |
|---|---|
| Funcionalidade de dois endpoints, identidade única, contabilidade e consumidores | Implementada e validada nos cenários documentados |
| Clientes reais IPv4/IPv6, handshake, hash e continuidade após falha de família | Matriz Rust de oito casos aprovada no checkpoint identificado no relatório |
| TLS/proxy/origem e cache sob rotação | Validados separadamente; probes desligados no soak |
| Candidato Rust seis horas | Aprovado no perfil de 10 mil peers, 20 mil endpoints e janelas de ~8 mil req/s |
| Original Rust três repetições formais e seis horas | Concluídos e auditados |
| Comparação formal original/candidato em toda a matriz | Incompleta; não aprovar globalmente p95/p99 +10% / throughput -5% |
| Comparação de desempenho PHP×PHP | Não concluída; fontes e evidências funcionais preservados, fora do destaque desta entrega |
| CPU/RAM por VM, população/pool e I/O | Campanha interrompida para diagnóstico; não concluída |
| A1/B/A2 de cache | Concluído; B experimental não integrado e sem aprovação de 5.500 req/s sustentados no banco de um núcleo |
| Causa física da pausa histórica do soak v2 | Não isolada; bug da lease reproduzido e corrigido independentemente dela |
| Journal Rust durável | Não implementado; dados aceitos apenas em memória podem se perder em crash |
| Tempo operacional de rollback em grande swarm | Não medido; roundtrip funcional controlado aprovado |
| Memória linear por peer em toda a faixa de população | Não estabelecida como coeficiente universal |
| Certificação de produção, exposição pública e integração upstream | Não realizadas por este pacote |

## Interpretações que os dados não sustentam

- 54 mil peers como limite rígido, como população de um único torrent ou como 54 mil req/s.
- Usar p99 0,330/0,475 ms dos dois soaks como ganho causal entre versões; cargas e janelas diferem.
- Usar médias de CPU ou RSS como únicos valores de dimensionamento, ignorando picos, backlog, cache e instrumentação.
- Converter IOPS observados no disco virtual em especificação universal de SSD ou atribuir todo I/O físico compartilhado ao MySQL.
- Considerar todo HTTP aceito como commit confirmado, ou toda divergência entre observadores como tamanho exato da fila.
- Supor que a mesma política BON foi homologada porque o BON permaneceu zero na fixture do soak.
- Tratar os sources originais sobre schema expandido como uma instalação inteiramente original.

## Decisões abertas

O cache B oferece economia de RAM com mais CPU/preparações, e uma confirmação reprovou estabilidade. A incorporação depende de decisão e revalidação com margem de persistência. Nenhum patch foi promovido durante o empacotamento. A definição de perfis adicionais de escala e I/O continua aberta.

Os testes e o procedimento de retorno reduzem incerteza, mas não eliminam a necessidade de ensaio na configuração de cada instalação. A [matriz de validação](data/validation-matrix.json) e o [acervo histórico](README.md) delimitam exatamente o que foi executado.
