# Método, ambiente e interpretação das medidas

## Proveniência

Bases: UNIT3D 9.2.0 (`8b88f4c8182eb3d3912ffef425c3224dcfd596f4`) e UNIT3D-Announce 0.3.1 (`fcd189e9aebf07a12a1f8cc39500819c3870925b`). Fontes finais e hashes em [proveniência](entrega-e-proveniencia.md). Os ensaios intermediários usaram checkpoints anteriores identificados em cada relatório; não atribuir retroativamente todos os números ao snapshot final.

## Ambiente de referência

| Componente | Configuração registrada |
|---|---|
| Virtualização | Proxmox; VMs laboratoriais 120/121/122; tracker, dados e clientes separados |
| Recursos de referência | 4 vCPUs / 8 GiB por VM; perfis menores aplicados por VM, não como orçamento total |
| Sistema clientes | Ubuntu 24.04 |
| Banco | MySQL 8.0.46; `REPEATABLE-READ` |
| Durabilidade MySQL | `innodb_flush_log_at_trx_commit=1`, `sync_binlog=1` |
| Buffer pool de referência | 128 MiB; aumentar RAM da VM não aumentou automaticamente o pool |
| Redis | 7.2.16; não integra o caminho de announce Rust medido por HTTP direto |
| PHP / Rust registrados | PHP 8.4.26 / Rust 1.99.0; lockfiles e imagens identificados nas execuções |
| Disco de dados | SSD NVMe KINGSTON SNVS250G, 232,9 GiB, compartilhado pelo host |
| Arquivo prolongado | ZFS, com observadores, limites de espaço e inventário; arquivos privados permaneceram no laboratório |
| Clientes reais | qBittorrent 4.6.3; Transmission 4.0.5; libtorrent 2.0.10 |

O [manifesto inicial](../lab/dualstack/manifest.json) fixa a preparação; [imagens](../lab/dualstack/images.env) e artefatos `environment-*`, `provenance.json` e `source-*.json` documentam cada execução. Os discos/recursos foram ampliados ou redimensionados em etapas posteriores. Usar a evidência da execução, não assumir que o manifesto inicial descreve toda a campanha.

## Perfis que não devem ser misturados

| Família de ensaio | Perfil e finalidade |
|---|---|
| Clientes reais | Origem IPv4/IPv6 real, namespaces separados, DHT/PEX/LSD desabilitados, descoberta somente pelo tracker, arquivo 16 MiB e SHA-256 |
| Densidade | Exploração curta, 1.000 req/s no torrent alvo; população residente controlada; maior concentração não equivale a maior população total |
| Escritor/throughput | 10.000 peers, 40 torrents × 250, 100% dual-stack, 80% seeders; lote 200/500 identificado por série |
| Soak candidato | 10.000 peers / 20.000 endpoints, HTTP direto/keep-alive, lote 500, TTL 7.200 s, rotação/expiração e pausas entre janelas, probes desligados |
| Soak original | 10.000 peers IPv4, 300 s de aquecimento + 72 janelas de 300 s, renovações de 2.000 leechers entre janelas; flush 3.000 ms |
| Original formal | Três repetições de 300 s de aquecimento + 900 s de medição; fixture limpa, auditoria e restart entre repetições |
| Capacidade/cache | Banco 1 vCPU/4 GiB no A/B/A, tracker/clientes 4 vCPU/8 GiB, mesmo processo MySQL dentro de cada série; sete rampas e duas confirmações de 300 s a 5.500 req/s |

As taxas elevadas são estresse sintético, com intervalo mínimo ajustado para viabilizar a carga. Não converter 8.000 req/s em 8.000 usuários nem assumir esse ritmo por cliente em operação normal.

## Métricas

- **Peer**: `(user_id, torrent_id, peer_id)`. Endpoint é `(identidade, família)`; não é outra unidade de crédito.
- **Throughput HTTP**: respostas aceitas por tempo de medição. **Confirmação**: efeitos persistidos. Uma fila crescente invalida a interpretação de throughput HTTP como capacidade sustentável.
- **p95/p99 por janela**: percentil dentro daquela janela. A mediana desses percentis não é o percentil global de todas as amostras. Aquecimento é separado quando o relatório assim indica.
- **Latência de resposta**: tempo após início do request. Espera no gerador e validação têm métricas próprias. Não confundir submilissegundos da LAN com RTT público ou com as medições de 27–98 ms fornecidas pela staff.
- **CPU de processo**: 100% = um núcleo lógico. CPU da VM pode usar o total de vCPUs; verificar o denominador.
- **RSS/PSS**: memória residente/proporcional amostrada, não uma constante por peer nem o máximo instantâneo garantido. Performance Schema também consome memória.
- **IOPS**: operações observadas no dispositivo virtual; escritas e flushes informados separadamente. Tamanho e latência das operações importam. O dispositivo físico inclui outras cargas do host.
- **Backlog estimado**: requer alinhamento temporal entre gerador e banco e inclui incerteza do observador. No original, usar crédito, não `state_version`. Expiração pode criar versão sem request no candidato.
- **Payload**: IPv4 compacta = 6 B; IPv6 = 18 B; dual-stack = até 24 B por peer lógico selecionado, além do envelope. `numwant=0` preserva estatísticas com listas vazias.

## Reprodutibilidade e limites

Os resultados incluem falhas e rodadas reprovadas. Preservam-se dados de preparação, finalização, drenagem e auditoria; não basta ler `stable=true`. O A/B/A de cache é sequencial em host compartilhado, não randomizado. As séries curtas não certificam teto de seis horas.

O baseline original usa código intacto sobre schema aditivo do laboratório; não representa uma instalação integral com schema original inalterado. O original pode publicar IPv4 mapeado em `peers6`, alterando seu payload. As garantias e cadências de persistência diferem entre os produtos.

Nenhuma nova carga foi executada ao montar o pacote. A [reprodução](testes-e-reproducao.md) distingue análise dos dados distribuídos de ensaios que exigem infraestrutura e amostras privadas não incluídas.
