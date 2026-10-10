# TLS/proxy e memória/cache

Validação de laboratório em 8 de outubro de 2026, conforme a ordem solicitada:
TLS/proxy, memória/cache e carga por último. Nenhum benchmark de capacidade,
comparação longa ou teste de seis horas foi iniciado neste incremento.

## TLS/proxy: resultado e correção encontrada

PHP standalone e Rust passaram pelos mesmos 19 controles, usando conexões reais
IPv4/IPv6 até o Nginx HTTPS. O cliente Python verificou a CA privada do laboratório,
o hostname e a negociação TLS 1.2/1.3. CA desconhecida e nome incorreto foram
recusados. O backend permaneceu em `127.0.0.1:6969`, inacessível pela rede cliente.

O proxy sobrescreveu `X-Real-IP` e `X-Forwarded-For` com a origem observada e
removeu `Forwarded`. Headers forjados e parâmetros `ip`, `ipv4`, `ipv6` não
mudaram os endpoints persistidos. As listas compactas mantiveram IPv4 quando
IPv6 falhou e vice-versa; com ambos disponíveis, retornaram 6 + 18 bytes para
o peer selecionado. A referência final foi 1.300 e o crédito único foi 300
em cada backend.

Uma regra DROP restrita à porta do teste permitiu observar o SYN de um probe
pendente. A porta foi substituída antes de seu timeout; o resultado antigo não
alterou o endpoint substituto. Fechar uma porta previamente confirmada produziu
nova checagem negativa após o TTL, preservando a outra família.

**Falha de produto corrigida no PHP:** `TrustProxies` estava implementado, mas
comentado no kernel HTTP. Com um proxy real, o controlador recebia o endereço
loopback e retornava erro interno antes de registrar o peer. Agora o middleware
está ativo antes do bloqueio por IP e do limitador de frequência. Em dualstack,
usa somente os IPs/CIDRs configurados; no modo legado, continua ignorando os
headers de proxy. Lista vazia não cai na confiança automática do framework.
Wildcards, `REMOTE_ADDR`, hostname e prefixos inválidos são recusados.

Fontes: `repos/UNIT3D/app/Http/Kernel.php:39`,
`repos/UNIT3D/app/Http/Middleware/TrustProxies.php:26` e
`repos/UNIT3D/tests/Integration/DualstackProxyTest.php:26`.
Para a topologia ensaiada, `DUALSTACK_TRUSTED_PROXIES=127.0.0.1/32`;
em outra instalação, configurar os endereços reais dos seus proxies.

## Rotação e memória observada

Cada backend recebeu oito lotes de 256 trocas de IPv6 e porta: **2.048 origens
IPv6 distintas**, sempre com um IPv4 preservado. A origem foi vinculada ao socket
do cliente; não foi simulada por header. O gerador limitou o início das requests
a 20/s. Cada lote aguardou sua referência e crédito no MySQL antes de avançar.

Em ambos, os oito checkpoints e o estado final tinham um peer lógico, dois
endpoints e exatamente 2.048 bytes adicionais. As origens substituídas não
permaneceram em `peer_ips`. Os aliases de rede criados pelo gerador foram
removidos. Um controle adicional com 256 trocas no binário Rust de produto
também passou, com dois endpoints e crédito 256.

PSS é a parcela proporcional da memória física dos processos; evita somar
integralmente as páginas compartilhadas pelos workers. A tabela cobre do fim do
primeiro lote ao fim da rotação, não a alocação inicial do processo:

| Processo | PSS inicial | PSS final | Variação |
|---|---:|---:|---:|
| PHP-FPM, master + 2 workers | 60.316 KiB | 60.316 KiB | 0 |
| Coordenador PHP | 54.547 KiB | 54.699 KiB | +152 KiB |
| Probe PHP | 52.416 KiB | 52.416 KiB | 0 |
| Rust com observação do cache | 9.948 KiB | 10.252 KiB | +304 KiB |

Não houve crescimento proporcional às 2.048 origens nesse intervalo. Isso não
prova ausência de qualquer vazamento nem substitui a campanha prolongada. Esses
valores são de uma população pequena e não estimam bytes por peer em 54 mil ou
100 mil peers. Também não são comparação de performance entre PHP e Rust.

## Cache de conectividade

O perfil de ensaio fixou capacidade em 16 entradas e TTL em 2 segundos.
No PHP, a rechecagem foi a cada 3 segundos; no Rust observado e no controle
de produto, a limpeza periódica foi a cada 3 segundos. Os padrões do produto
permanecem inalterados. A matriz TLS inicial Rust precedeu essa alteração do
intervalo de limpeza, mas já usava TTL de 2 segundos.

| Medida | PHP | Rust observado |
|---|---:|---:|
| Máximo de entradas amostrado | 9 | 16 |
| Entradas após a rotação e expiração | 1–2 | 0 |
| Crédito duplicado | 0 | 0 |

O PHP continua rechecando os dois endpoints correntes durante a ociosidade,
por isso seu cache não precisa ficar vazio. Hash e sorted set tiveram a mesma
cardinalidade. O máximo combinado de memória desses dois objetos Redis foi
1.616 bytes; o JSON do peer permaneceu entre 894 e 904 bytes. A fila chegou a
33 transições na amostragem de 1 Hz e terminou vazia. Não se trata de um teto
de backlog sob carga.

As amostras PHP cobriram 155 segundos, incluindo toda a rotação de 103,51 s
e seus primeiros cinco segundos de ociosidade. Uma coleta posterior de dez
segundos complementa o estado ocioso. As amostras Rust cobriram 145 segundos,
incluindo a rotação de 102,96 s e toda a janela ociosa de 12 segundos.
Probes muito curtos podem não aparecer na amostragem de 1 Hz; zero probes
simultâneos amostrados não significa ausência de conexões TCP.

O limite PHP foi também exercitado pelo teste de integração com capacidade 2,
Redis/MySQL reais e rotação de portas. A suíte Rust verificou capacidade,
expiração e recusa quando os 128 slots de probes estão ocupados.
Fontes: `repos/UNIT3D/app/Services/Dualstack/EndpointProbe.php:50`,
`repos/UNIT3D/tests/Integration/DualstackJournalTest.php:514`,
`repos/UNIT3D-Announce/src/dualstack_network.rs:75` e
`repos/UNIT3D-Announce/src/scheduler.rs:27`.

## Estado temporário por IP no limitador PHP

Uma segunda execução PHP rotacionou 512 endereços e aguardou 130 segundos sem
novos announces. O banco Redis usado pelo limitador começou com zero chaves,
atingiu 513 (as 512 origens IPv6 mais o IPv4) e voltou a zero pelo TTL natural
de 120 segundos. O announce final no IPv6 fixo criou uma chave nova; nenhuma
limpeza manual foi usada. Crédito final 512, um peer e dois endpoints.

A memória Redis total foi de 2.365.600 para um pico de 2.524.232 bytes, terminando
em 2.392.752 bytes. Inclui estado do tracker, caches da aplicação e alocador;
não atribuir toda a diferença ao limitador. A coleta adicional durou 185 s.
O limitador existente usa 500 requests/minuto por IP
(`repos/UNIT3D/app/Providers/RouteServiceProvider.php:92`). O TTL de dois minutos
foi confirmado no `DurationLimiter` do Laravel instalado e observado em execução.
Portanto, esse estado cresce com a quantidade de origens recentes, enquanto o
cache de conectividade tem um limite de entradas independente. O efeito durante
uma carga intensa de origens distintas ainda pertence à medição de carga.

## Reprodução e evidências

Os runners recusam hosts fora do laboratório e usam exclusivamente o banco
`unit3d_dualstack_journal_test`. Encerrar o proprietário anterior antes de
`network-backend.sh start`, pois a inicialização restaura essa fixture.

1. Instalar `prepare-network.sh`, `network-backend.sh`, `memory-sampler.py`,
   `memory-redis.php` e `bootstrap-source.py` no diretório `lab` da VM tracker.
   Preparar a CA com `prepare-network.sh`; copiar somente `ca.crt` para
   `/opt/unit3d-dualstack/network-ca.crt` na VM clientes.
2. Instalar `network-client.py` e `memory-client.py` na VM clientes, junto
   dos helpers/fixtures privados já usados pelo laboratório. Nenhuma credencial
   ou chave privada TLS entra nos resultados exportados.
3. Usar `network-backend.sh start php product` ou `start rust product` e
   executar `network-client.py --backend php|rust --output ARQUIVO_NOVO` como
   root nos clientes. Sempre encerrar com `network-backend.sh stop ...`.
4. Para a medição, iniciar `memory-sampler.py --backend ... --seconds 155
   --output ARQUIVO_NOVO` no tracker e `memory-client.py --backend ...
   --output ARQUIVO_NOVO` nos clientes. Dar margem entre a duração do coletor e
   a do ensaio; os arquivos existentes não são sobrescritos.
5. Para observar o cache Rust privado, executar `build-memory-observer.sh`
   com `prepare-memory-observer.py` instalado. O fingerprint dos fontes é
   conferido antes da cópia. Somente `main.rs` e `dualstack_network.rs` recebem
   contadores de diagnóstico na cópia; o binário original é restaurado após a
   compilação, inclusive em caso de falha. Iniciar com perfil `observed`.
   Exportar exclusivamente as linhas `LAB_MEMORY` do log, como JSON.
6. `summarize-network-memory.py` confere os invariantes das séries selecionadas
   e produz `results/tls-memory/summary.json`.

Os arquivos brutos estão em `lab/dualstack/results/tls-memory/`. A identidade
dos fontes/binários e a configuração permitida estão em `environment.json`.
Rust permanece em `9e8b546`, com fingerprint dos fontes
`a0b448b667f756318200f17fda3e4fc6f2c3b75528c24a9ec9c0dfab80174659`.
O PHP recebeu apenas a correção de integração do proxy e seus testes.

As tentativas interrompidas também foram preservadas. Além da falha de produto,
o harness precisou corrigir permissões do overlay PHP, esperar a porta nova no
SQL, tratar o cabeçalho de `smaps_rollup`, separar sockets IPv6-only e preparar
o arquivo vazio usado como ponto de montagem da configuração Rust. Essas
falhas não foram classificadas como aprovação do produto.

Regressões: **39 testes PHP / 493 verificações**, incluindo journal/probes e
os 12 casos de proxy; **19 testes Rust**, sem falhas ou skips. A matriz TLS
completa passou após a correção PHP. Transferências BitTorrent com clientes
reais pertencem ao relatório anterior; esta matriz HTTPS usa o gerador Python.

Permanecem para a etapa final a comparação formal de carga com as tags originais,
a janela de perda durante carga sustentada, custos de memória por população e
o teste prolongado, sujeito ao orçamento de armazenamento. Sem push ou produção.

Fechamento: lease inativa, journal PHP drenado, zero consultas ativas no banco
de ensaio, nenhum alias de rotação ou regra DROP restante e nenhum container
tracker ativo. Certificados privados de sete dias continuam somente no
laboratório, sem frontend TLS em execução.

Revisão final única contra `docs/plans/2026-10-08-tls-memoria.md`: sequência,
origens reais, limite de frequência, contadores, coleta e fechamento atendidos.
A correção PHP foi necessária para superar uma falha comprovada da matriz,
dentro da autorização para corrigir antes de avançar. A observação Rust ficou
restrita à cópia de diagnóstico. Nenhuma alteração em BON, contabilidade,
schema, lockfiles, durabilidade ou código Rust de produto. A carga continua
fora deste checkpoint.
