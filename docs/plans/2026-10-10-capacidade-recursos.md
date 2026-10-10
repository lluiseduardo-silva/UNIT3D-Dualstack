# Capacidade por recursos — Rust candidato e MySQL

Solicitado em 10/10/2026; tamanhos confirmados pelo usuário **por VM**.
Execução autorizada do diagnóstico no laboratório, sem alterar produto ou produção.

## Perguntas e limites

Medir capacidade sustentável de announces, identificar CPU, memória, I/O ou
serialização como restrição, e produzir curvas de demanda por taxa confirmada.
Um valor de IOPS sem tamanho de operação, latência e flush não dimensiona MySQL.
`innodb_io_capacity` orienta tarefas de fundo; não é um limitador geral do disco.
[Manual MySQL](https://dev.mysql.com/doc/refman/8.0/en/innodb-configuring-io-capacity.html).

Usar o binário Rust 36823b5 já validado, SHA-256
`25a9860c6caad0d78e2c3f8073f6ecd6822c05cbcd1b45773d0994a7df6d6833`.
Sem PHP, comparação com original, mudança de durabilidade ou novo ensaio de seis
horas. Esta campanha caracteriza o candidato. O host continua compartilhado:
registrar concorrência e repetir pontos de fronteira, sem prometer isolamento físico.

## Preparação

- VMs exclusivas 120/121/122, nomes/tags conferidos antes de qualquer ajuste.
- Salvar recursos originais (4 vCPU/8 GiB, balloon desligado), restaurar ao fim.
- Gerador permanece na VM 122; reduzir recursos reais das VMs 120 e 121 exige
  parada graciosa e reboot. Não simular RAM de VM apenas com limite de processo.
- Clonar a fixture de recuperação em `unit3d_dualstack_capacity_20261010`;
  reset permitido somente nessa base e sem proprietário ativo.
- Preservar bases, binlogs arquivados, containers e evidências dos testes anteriores.
- Saída pública somente métricas/agregados; nunca env, credenciais, passkeys ou fixtures.

## Sequência

1. Calibrar a instrumentação e auditoria em 4/8 + 4/8 a baixa taxa.
2. Curvas com 10.000 peers, 40 torrents de 250, 100% dualstack, 80% seeders,
   numwant=10, batch=500, TTL=7200, HTTP direto, probes e log de announces desligados.
   Comparar tracker 1/2 e 2/4 com banco 4/8; depois banco 1/2 e 2/4 com tracker 4/8.
   Confirmar pares equilibrados 1/2 + 1/2 e 2/4 + 2/4.
3. Controles causais: banco 1/4 e 2/2; tamanho de buffer pool fixado e registrado
   inicialmente, depois variação isolada quando os resultados justificarem.
4. Memória/população: crescer a população distribuída com taxa fixa, respeitando
   espaço/RAM; medir RSS, buffer pool, leituras físicas e tempo de bootstrap.
   Um conjunto quente que cabe no menor perfil não determina o teto de memória.
5. I/O: variar o limite de escrita apenas no disco da VM 121, medir o limite
   efetivamente aplicado e latência/flush. Cap de IOPS não simula SSD mais rápido;
   se o disco físico limitar antes do cap, reportar resultado censurado.

Começar rampas em 500/1.000/2.000/4.000/6.000/8.000/10.000/12.000 requests/s;
estender apenas quando gerador, backlog e recursos permitirem. Janelas curtas
de localização não são aprovação sustentada. Refinar o intervalo entre último
ponto estável e primeiro saturado; confirmar a fronteira com três repetições
de 300 s e aquecimento separado, drenagem e auditoria entre rodadas.

## Medições e critérios

- HTTP: taxa oferecida/aceita/concluída, p95/p99 de resposta separados da fila
  do gerador, erros, custos de validação; marcar limitação do gerador explicitamente.
- Persistência: taxa confirmada, tendência da diferença aceitos/persistidos,
  drenagem e auditoria por identidade/histórico/usuário. A defasagem das amostras
  não é tamanho exato da fila; comparar séries alinhadas no tempo.
- CPU do processo e por thread, CPU/steal/iowait/pressão da VM e concorrência do host.
- RSS/PSS, MemAvailable, pressão de memória, major faults, cache e leituras físicas.
- Disco da VM e host: IOPS de leitura/escrita, bytes/operação, MiB/s, await, flush,
  fila, redo, esperas de log/buffer pool, checkpoints, locks e tempo de statements.
- Sustentável: zero erro/divergência, >=99% da oferta, sem tendência persistente
  de crescimento da fila, drenagem <=30 s; latência absoluta e relativa expostas.
- Saturação esperada encerra a subida naquele perfil, drena e permite outro perfil
  somente com auditoria exata. Erro de correção, perda de propriedade ou falha de
  proteção interrompe a campanha e preserva evidências.
- Proteções: disco dados >=8 GiB, thin pool >=8 GiB, arquivo >=20 GiB,
  MemAvailable >=256 MiB; observadores frescos; parar oferta antes de 60 mil
  transições pendentes estimadas. Não provocar OOM ou esgotamento do disco.

## Entrega

Tabela por configuração com maior taxa confirmada, primeiro ponto saturado,
faixa de latência, memória, CPU, IOPS, MiB/s e causa sustentada por controles.
Separar teto HTTP, persistência, população e limitação do gerador.
Para alvos de 1k/2k/4k/8k/10k req/s, apresentar demanda medida e margem explícita;
extrapolações não verificadas recebem esse rótulo. Não extrapolar linearmente
bytes de RAM ou IOPS a partir de uma única população/taxa.

## Checkpoint de 10/10/2026: proteção de memória

A matriz `capacity-cpu-ram-v2` foi interrompida no perfil banco 1 vCPU/2 GiB:
251,422 MiB disponíveis acionaram o piso de 256 MiB no aquecimento da segunda
confirmação de 5.500 req/s. As 40 rodadas salvas preservaram crédito e endpoints;
drenagens verificadas, recursos originais restaurados. Evidências públicas
coletadas e analisadas em `docs/dualstack-capacidade-recursos.md`.

Não reiniciar automaticamente a série que falhou. A decisão de continuidade
recomendada é um ensaio curto com o mesmo binário, banco de 4 GiB e alocações de
memória MySQL instrumentadas, incluindo reset/reconexão. Cache de statements
das consultas variáveis é uma hipótese baseada no código; ainda sem prova de
causalidade. Não alterar produto ou durabilidade com base apenas nessa hipótese.

Após essa investigação e autorização para retomar, completar os cinco perfis
não executados e confirmar taxas inferiores nos perfis cuja confirmação longa
falhou. Só então avançar aos controles de população/buffer pool e I/O. A pausa
não aprova a matriz CPU/RAM nem encerra os objetivos da campanha.

## Ensaio autorizado com 4 GiB — 10/10/2026

O usuário autorizou o diagnóstico recomendado. Alterar apenas a RAM da VM de
dados do perfil que interrompeu a matriz: **1 vCPU/4 GiB**, mantendo tracker e
clientes em 4 vCPU/8 GiB. Preservar binário, buffer pool, durabilidade e fixture.
Salvar a base final de `capacity-cpu-ram-v2` em arquivo privado na própria VM,
antes do primeiro reset; exportar somente tamanho, hash e confirmação da cópia.

1. `capacity-memory-calibration-v1`: validar o novo coletor no MySQL real;
   10 s de aquecimento + 30 s a 1.000 req/s, crédito/endpoints auditados e
   drenagem/recursos restaurados. Não avançar em caso de falha.
2. `capacity-memory-4g-v1`: repetir a sequência do perfil anterior sem reiniciar
   o MySQL entre rodadas: 500, 1.000, 2.000, 4.000, 6.000, 5.000 e 5.500 req/s
   (20 s + 60 s cada), seguidos por duas rodadas de 30 s + 300 s a 5.500 req/s.
   Reiniciar o Rust e resetar somente a base de capacidade entre rodadas.
3. Registrar a cada 5 s RSS/PSS, memória anônima/cache, contagem e tamanho
   agregado de statements preparados, grupos e maiores alocações instrumentadas
   do MySQL. Nenhum texto SQL, identidade ou segredo será exportado. Manter os
   observadores existentes de 2 s; medir também o tempo do coletor adicional.
   Correlacionar amostras com início do reset/start e fim da drenagem/stop.
4. Capturar alocações antes do reboot de restauração. Exigir auditoria exata,
   drenagem graciosa e restauração verificada. Manter os mesmos pisos de disco e
   memória, limite de backlog e exclusão de ensaios concorrentes. Uma tendência
   de backlog será reportada mesmo que não interrompa o diagnóstico.

O diagnóstico não aprova um teto sustentado nem reinicia a matriz interrompida.
Ao terminar, analisar a hipótese e informar a decisão de continuidade. Não
alterar cache, pool de conexões, produto ou durabilidade neste ensaio.

### Verificação concluída em 10/10/2026

`capacity-memory-4g-v1` completou as nove rodadas: 5.550.000 announces, zero
erros/divergências, 277.523.200 bytes de crédito auditados, todas as drenagens
com saída zero, sem OOM, recursos originais restaurados e conferidos. A coleta
capturou 317 amostras, até 488,14 MiB em statements preparados e RSS máximo de
1.245,75 MiB; após fechar as conexões a alocação dos statements zerou, mas o RSS
permaneceu próximo de 1.216 MiB. O padrão é compatível com retenção de memória,
sem prova de vazamento ilimitado ou de toda a causa da interrupção anterior.

O atraso temporário de 47.573 transições da segunda confirmação coincidiu com
aumento de iowait/latência de disco e foi recuperado durante a carga; não houve
falta de RAM. Resultados, limites e provas estão no relatório de capacidade.
O diagnóstico não aprova o teto sustentado nem encerra a campanha geral.

Aguardar decisão sobre um controle A/B restrito à persistência do cache das
consultas dinâmicas. Esse controle deve medir também o possível custo extra de
CPU/latência, preservando contabilidade e durabilidade; não está em execução.
Não retomar automaticamente a matriz ou aplicar alteração ao produto.

## A/B de cache autorizado — 10/10/2026

O usuário autorizou o teste recomendado. **A é o candidato dualstack 36823b5**,
não o Rust original 0.3.1. B deriva exatamente desse commit e acrescenta apenas
`.persistent(false)` às oito consultas dinâmicas de `persist_inner`, em
`src/dualstack/persistence.rs`. Consultas fixas, SQL, parâmetros, ordenação,
transações, pool, tamanho de lote e durabilidade permanecem iguais. O patch é
experimental e fica no laboratório; o checkout do produto e o binário A são
preservados. Registrar hashes do código, patch, imagem, compilação e binários.

Hipótese: evitar a retenção das consultas de tamanho variável no cache de cada
conexão reduz a alocação MySQL e o RSS. Risco medido: preparar mais vezes pode
aumentar CPU, latência de persistência e backlog. Não pressupor benefício.

1. Compilar B com a mesma imagem, lockfile e perfil release. Usar o ZFS somente
   para o cache de compilação, devido ao espaço do SSD; executar ambos os
   binários no SSD da mesma VM. Executar testes unitários e de contrato.
2. Antes do reset, preservar a base final de A1 (`capacity-memory-4g-v1`) em
   arquivo privado na VM de dados, exportando apenas prova de tamanho/hash.
3. Calibrar a seleção B e o instrumento existente em
   `capacity-cache-b-calibration-v1`: 10 s + 30 s a 1.000 req/s. Exigir crédito
   exato por identidade, endpoints e contadores corretos, zero erro, drenagem
   graciosa e restauração efetiva das VMs antes de avançar.
4. Executar `capacity-cache-b-v1` com o protocolo completo do diagnóstico de
   memória: sete rampas de 20 s + 60 s (500/1.000/2.000/4.000/6.000/5.000/5.500)
   e duas confirmações de 30 s + 300 s a 5.500 req/s. Banco 1 vCPU/4 GiB,
   tracker/clientes 4 vCPU/8 GiB, buffer pool 128 MiB, durabilidade 1/1,
   10.000 peers dualstack e 20.000 endpoints. Não reiniciar MySQL entre rodadas.
5. Após B passar correção, drenagem e restauração, repetir A em
   `capacity-cache-a-repeat-v1` com o mesmo protocolo. A1/B/A2 permite observar
   variação temporal do host compartilhado; não elimina toda interferência.
   Cada série começa com o reboot da VM de dados ao alterar os recursos.
6. Comparar memória instrumentada, RSS/PSS/anônima antes/durante/depois das
   conexões, prepared statements, prepares/execuções, CPU, p95/p99 por janela,
   throughput, I/O, backlog alinhado e tempo do coletor. Conferir séries e
   picos transitórios, sem resumir tudo ao campo `stable`. Preservar provas.

Manter exclusão compartilhada, guardas e restauração automáticas. Não editar
scripts em execução, iniciar outro ensaio simultâneo ou reiniciar uma série
que falhou. Falha de correção/proteção interrompe a sequência para diagnóstico;
uma regressão de desempenho exige relatório, não ajuste automático do produto.
Calibração não comprova benefício de memória; duas confirmações de cinco minutos
não aprovam teto sustentado nem substituem um ensaio prolongado. Ao final,
registrar os custos e benefício observados e aguardar decisão de incorporação.
A campanha geral de capacidade permanece pendente.

Nota de preparação: `capacity-cache-b-calibration-v1` não iniciou o produto ou
o gerador. Faltava o arquivo vazio que recebe o bind da configuração em B.
Preservar a tentativa e seu container; restaurar os recursos manualmente sob
exclusão compartilhada e validar a correção apenas em
`capacity-cache-b-calibration-v2`. O binário e o patch permanecem idênticos.

Atualização de 2026-10-10 após B: `capacity-cache-b-v1` terminou as nove
rodadas e passou na auditoria de correção, hashes, drenagem e restauração.
Foram 5.550.000 announces, 277.523.200 bytes de crédito e zero erros ou
divergências. As nove saídas foram zero, sem OOM; `probe_failures` vazio.
O pico de RSS MySQL foi 559,86 MiB. A rampa de 6.000 req/s e a primeira
confirmação de 5.500 req/s acusaram tendência de crescimento do backlog:
isso permanece como resultado de desempenho, não como aprovação dessas taxas.

A próxima série autorizada é `capacity-cache-a-repeat-v1` (A2), registrada
no checkpoint antes do início, com o binário A preservado. O bloqueio livre,
a ausência de announcer ativo, os recursos efetivos 4 vCPU/8 GiB das três VMs
e o hash de A foram verificados após B. Repetir exatamente o mesmo protocolo;
comparar A1/B/A2 antes de decidir sobre incorporação ou novos ensaios.

Conclusão em 2026-10-10: A2 terminou às 16:55:49 UTC. Nove rodadas,
5.550.000 announces, crédito exato, zero erros/divergências; hashes, saídas
zero, ausência de OOM e restauração efetiva 4 vCPU/8 GiB passaram. A comparação
A1/B/A2 foi concluída com todas as 27 séries e as janelas de atraso alinhado.
B reduziu o pico RSS MySQL em 55,1–59,7%, mas usou mais 5,0–7,9 pontos de CPU
de um núcleo nas confirmações; sua rampa de 6.000 req/s e primeira confirmação
de 5.500 req/s reprovaram estabilidade. A conclusão não aprova teto sustentado.

Encerrar o acompanhamento A/B e aguardar decisão sobre incorporação ou novos
ensaios. B permanece experimental; A e as evidências estão preservados.
Não retestar 2 GiB nem retomar a matriz geral automaticamente. Resultados e
limitações em `docs/dualstack-capacidade-recursos.md`, seção final do A/B.
