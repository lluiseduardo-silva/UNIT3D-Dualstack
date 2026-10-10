# Clientes BitTorrent reais — diagnóstico IPv6 e regressão

Em 8 de outubro de 2026, **os oito cenários passaram no PHP standalone e no
Rust: 16 casos aprovados**, com descoberta pelo tracker, handshake, arquivo
completo, SHA-256 e conferência dos créditos finais. Dualstack registra duas
famílias na mesma identidade; interromper uma família preserva a transferência
pela outra. A falha inicial de IPv6 foi identificada no bind de saída do
libtorrent 2.0.10 por nome de interface e corrigida no harness, conforme o
diagnóstico preservado abaixo. Nenhum código dos produtos mudou nesta rodada.

O código dos dois produtos permaneceu no checkpoint anterior:

- UNIT3D: `8071ac42ec844490c81c3805ce8cd1b6e3824262`.
- UNIT3D-Announce: `859aa88f71f505e48401a4d7436a84d122af89a6`.

## Ambiente e método

VM 122, Ubuntu 24.04, 4 vCPU e 8 GiB. Clientes em namespaces separados,
`ds-bt-seed` e `ds-bt-down`, com interfaces macvlan `bt0` na rede isolada do
laboratório. Seeder em `172.29.92.40` / `fd42:756e:6974:92::40` e downloader
em `.41` / `::41`. Cada caso recebe somente as famílias solicitadas; não há
rota padrão nos namespaces. O hostname `tracker.dualstack.test` é resolvido
por `/etc/netns/<namespace>/hosts` para o tracker `.10` / `::10`.

| Componente | Versão executada / pacote Ubuntu |
|---|---|
| qBittorrent | 4.6.3 / `4.6.3-1build2` |
| Transmission | 4.0.5 (`a6fe2a64aa`) / `4.0.5-1ubuntu0.1` |
| libtorrent-rasterbar e binding Python | `2.0.10-1.1build2`; binding informa `2.0.10.0` |
| TShark | `4.2.2-1.1build3` |
| tcpdump | `4.99.4-3ubuntu4.24.04.1` |
| strace, somente no diagnóstico | 6.8 |

A configuração usa torrent privado, TCP, criptografia BitTorrent desativada
para inspeção do handshake, DHT/PEX/LSD e mapeamento de portas desativados.
Os peers são descobertos pelo tracker; não há inserção de peers por RPC.
O serviço global Transmission fica mascarado, e as instâncias são iniciadas
somente pelo harness. RPC permanece no loopback de cada namespace.
Código: `lab/dualstack/real-clients.py:90`, `:146`, `:199` e `bt-rpc.py:11`.

O arquivo de 16.777.216 bytes é determinístico. SHA-256 esperado e obtido nos
16 casos da matriz final:

```text
1b59cea991e571857c66f57efa9bd1e6ba13ed3dbce7211b6aecb5494f47b020
```

Cada caso tem um infohash e torrent próprios, IDs 12101–12108. Os usuários
sintéticos são 12001 e 12002. A única base alterada foi
`unit3d_dualstack_journal_test`; o baseline foi preservado. O Rust permaneceu
ausente durante os ensaios PHP. Cada rodada começou com fixtures novas, após
drenar e encerrar o backend anterior. `versions.json` da matriz final registra
também backend e geração da lease, conferidos pelo runner antes da execução.

## Resultado após o diagnóstico

| Seeder → downloader | Rede | Resultado |
|---|---|---|
| qBittorrent → Transmission | IPv4-only | Handshake, arquivo completo e SHA-256 correto |
| qBittorrent → Transmission | IPv6-only | Handshake, arquivo completo e SHA-256 correto |
| Transmission → qBittorrent | IPv4-only | Handshake, arquivo completo e SHA-256 correto |
| Transmission → qBittorrent | IPv6-only | Handshake, arquivo completo e SHA-256 correto após ajuste do harness |
| Ambos os sentidos | Dualstack | Dois endpoints por peer, ambas as famílias na resposta, hash e crédito corretos nos dois backends |
| Interrupção IPv4 ou IPv6 | Dualstack | Dados antes da falha e no caminho restante depois; hash e crédito corretos nos dois backends |
| Matriz com backend Rust | Todas | Oito casos aprovados |

Os resultados JSON incluem announces observados, endpoints devolvidos,
handshakes, progresso, hash e snapshots SQL antes/depois da transferência
quando ela conclui. A rodada final pausa os clientes por RPC, aguarda a
persistência dos `stopped` e exige dois peers inativos, zero endpoints, zero
contagens ativas e uma única conclusão. Em cada identidade, o maior contador
observado menos a referência inicial deve coincidir com histórico real,
histórico creditado e variação do saldo. As fixtures não aplicam fatores.
No cenário de falha, a rede é restaurada somente depois de comprovar a
transferência pelo caminho restante, permitindo encerrar ambos os endpoints.

O upload anunciado pode exceder o tamanho do arquivo: os testes com interrupção
anunciaram cerca de 18,9 MB e o Transmission 16.790.528 bytes. O teste verifica
o contador efetivamente anunciado, sem inventar crédito a partir do tamanho
do arquivo. O download foi 16.777.216 bytes em todos os casos. Os bytes de
pacotes `piece` dissecados também não equivalem ao tamanho do arquivo; a
integridade é confirmada pelo arquivo recebido e seu SHA-256.

Rodadas finais: `php-20261008T144932` e `rust-20261008T145811`. A primeira
tentativa de conferência financeira (`php-20261008T144547`) encontrou um limite
da captura: o Transmission encerrou o endpoint e o SQL confirmou o crédito,
mas seis pacotes recebidos pelo filtro ainda não tinham sido entregues ao
arquivo quando o tcpdump terminou. `-U` só controla a escrita do arquivo.
Adicionado `--immediate-mode`, o mesmo caso e as duas matrizes completas
passaram com os announces finais na captura. A exigência financeira foi mantida.

## Evidência do bloqueio IPv6 original

Torrent 12104, infohash `b964087b3f986cf5f4857ff1951f423d96d530e1`:

1. Transmission anunciou por `fd42:756e:6974:92::40`, como seeder. O banco
   persistiu um peer ativo, `state_version=1`, um endpoint IPv6 na porta 6881
   e contadores `seeders=1`, `seeders_ipv6=1`, `seeders_ipv4=0`.
2. qBittorrent anunciou por `fd42:756e:6974:92::41`. Recebeu HTTP 200,
   `complete=1` e `peers6` de 18 bytes com `[fd42:756e:6974:92::40]:6881`.
3. Ficou em `stalledDL`, com progresso e download zero, até o timeout.
4. A captura do downloader contém **zero pacotes TCP na porta 6881**,
   inclusive zero SYN. As duas capturas não contêm handshake ou mensagens
   BitTorrent de dados; tcpdump informou zero pacotes descartados pelo kernel.

O endpoint foi devolvido corretamente pelo tracker. Na primeira rodada a
causa permaneceu desconhecida; o diagnóstico abaixo resolveu esse ponto.

## Causa confirmada e teste comparativo

O qBittorrent reconheceu um peer na resposta do tracker, sem filtro de IP,
proxy ou banimento. O Transmission estava em seeding, com o arquivo completo
e listener IPv6 na porta 6881. Um probe separado completou TCP e handshake
BitTorrent com ele; não solicitou peças nem inseriu peers nos clientes.

O `strace` do processo qBittorrent mostrou esta sequência no caminho de saída:

```text
socket(AF_INET6, SOCK_STREAM, IPPROTO_TCP) = 15
setsockopt(15, SOL_SOCKET, SO_BINDTODEVICE, ..., 4) = 0
bind(15, {sa_family=AF_INET, ... sin_addr=inet_addr("0.0.0.0")}, 16)
    = -1 EINVAL (Invalid argument)
```

O socket é IPv6, mas o endereço usado no bind é IPv4. A falha ocorre antes
do `connect()` com o peer. O caminho de announce usa o endereço local IPv6
explícito e consegue alcançar o tracker, explicando a diferença observada.

O [código fixado do libtorrent 2.0.10, `enum_net.hpp:166–224`](https://github.com/arvidn/libtorrent/blob/v2.0.10/include/libtorrent/enum_net.hpp#L166)
confirma o mecanismo: `bind_socket_to_device` inicializa o endpoint como IPv4;
quando recebe um nome de interface e `SO_BINDTODEVICE` funciona, não troca a
família antes do bind. Com IP explícito, passa por outro ramo. O
[chamador `session_impl.cpp`](https://github.com/arvidn/libtorrent/blob/v2.0.10/src/session_impl.cpp#L5205)
fornece o protocolo do destino, mas esse ramo do helper não o utiliza.

| Única configuração alterada no downloader | Resultado |
|---|---|
| Interface `bt0`, endereço automático | `EINVAL`, zero download; Transmission responde ao probe |
| Interface sem restrição por nome, dentro do mesmo namespace | Conexão IPv6, 16 MiB e SHA-256 correto |
| Interface `bt0`, IPv6 local explícito | Conexão IPv6, 16 MiB e SHA-256 correto |

Também foi repetido o controle com `bt0` após a regressão aprovada: o bind
inválido reapareceu. Não foram alterados o tracker, Transmission, biblioteca,
arquivo ou rotas. A hipótese de exigir rota padrão não foi necessária para
explicar o resultado; a transferência passou mantendo somente rotas locais.

A correção em `real-clients.py` deixa `current_network_interface` vazio.
O namespace continua limitado a loopback e `bt0`, sem rota externa. Esse
ajuste é específico do laboratório isolado; não recomenda retirar vínculos
de interface de instalações que dependam deles para restringir uma VPN.
O caso com IP explícito confirma a causa, mas fixar uma só família não atende
ao próximo teste dualstack. As versões dos clientes foram preservadas.

Rodada limpa `php-20261008T142110`: **quatro casos aprovados**, cada um com
handshake, descoberta pelo tracker, 16 MiB e SHA-256 correto. Essa rodada
funcional não contém o probe diagnóstico. A base exclusiva foi restaurada
antes da rodada; baseline preservado. Não houve alteração nos dois produtos.

## Arquivos de evidência

Diretório `lab/dualstack/results/real-clients/`:

- `php-20261008T134620/qbit-transmission-v4/result.json`: aprovado.
- `php-20261008T134945/qbit-transmission-v6/result.json`: aprovado.
- `php-20261008T134945/transmission-qbit-v4/result.json`: aprovado.
- `php-20261008T134945/transmission-qbit-v6/result.json`: bloqueio funcional.
- `php-20261008T141234/`: reprodução do timeout original com inspeção da API.
- `diagnosis-*/diagnostic.json` e `network-calls.json`: controles comparativos;
  incluem probe identificado como diagnóstico, distinto da matriz funcional.
- `php-20261008T142110/`: quatro casos aprovados após ajuste, sem probe.
- `php-20261008T143940/`: quatro casos dualstack/falha PHP aprovados, antes da conferência financeira final.
- `php-20261008T144547/`: tentativa com falha de captura do último announce Transmission.
- `php-20261008T144932/`: oito casos PHP aprovados, incluindo fechamento financeiro.
- `rust-20261008T145811/`: oito casos Rust aprovados, incluindo fechamento financeiro.
- `lifecycle.json`: cinco falhas de provisionamento/recursos existentes verificadas em namespaces Linux reais.
- `ipv6-bind-cause.json`: resumo da causa, syscalls e regressão aprovada.
- `ipv6-stall-diagnostic.json`: contagem independente de pacotes da captura,
  hash da captura privada, versões de pacotes e estado após limpeza.
- `php-20261008T134539/` e `php-20261008T134759/`: erros de preparação já
  corrigidos, preservados como histórico.

Primeiro erro: flag de confirmação legal não aceita pelo qBittorrent 4.6.3;
retirada, mantendo a aceitação no arquivo de configuração. Segundo: RPC do
Transmission não iniciou em IPv6-only com bind IPv4; ajustado para `::1`.
Ambos ocorreram antes de testar a transferência. Não são o bloqueio de
180 segundos descrito acima. Os arquivos `versions.json` históricos têm o
campo Transmission vazio porque o comando escreve a versão em stderr; a
versão foi obtida separadamente e o pacote está no diagnóstico publicado.

Capturas, configurações de clientes e logs completos contêm dados privados e
ficam somente em `/opt/unit3d-dualstack/real-clients/` na VM 122, sob diretório
restrito. Foram exportados apenas `result.json`, `versions.json` e o diagnóstico
permitido, conferidos contra as passkeys das fixtures antes de copiar. Não
publicar a árvore completa nem arquivos `.torrent`, `.env` ou `fixture.json`.

## Reprodução e controles do diagnóstico

Usar exclusivamente as VMs deste laboratório, após confirmar que não há outro
ensaio em execução. Os pacotes fixados acima devem estar instalados na VM 122;
não substituir por versões atuais sem registrar uma nova série. Copiar
`real-clients.py`, `bt-rpc.py` e `baseline.py` para `/opt/unit3d-dualstack/`.
O módulo `python3-pymysql` e os arquivos privados de acesso já são pré-requisitos
do laboratório. Manter `transmission-daemon.service` mascarado.

No tracker, com proprietários encerrados e filas drenadas, restaurar somente o
banco exclusivo de ensaio (esse comando elimina os dados anteriores dele):

```sh
sudo docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test \
  -v /opt/unit3d-dualstack/repos/UNIT3D:/app \
  -v /opt/unit3d-dualstack/lab:/lab:ro \
  unit3d-ds-php:baseline php /lab/initialize-journal-test.php
```

Na VM clientes, antes de iniciar o backend:

```sh
sudo python3 /opt/unit3d-dualstack/real-clients.py prepare
```

No tracker: `sudo bash /opt/unit3d-dualstack/lab/start-candidate-php.sh resume`.
Na VM clientes, reproduzir o caso bloqueado:

```sh
sudo python3 /opt/unit3d-dualstack/real-clients.py run \
  --backend php --case transmission-qbit-v6
```

Com o ajuste, esse caso passou. Para repetir os quatro casos em uma base limpa:

```sh
sudo python3 /opt/unit3d-dualstack/real-clients.py run --backend php \
  --case qbit-transmission-v4,qbit-transmission-v6,transmission-qbit-v4,transmission-qbit-v6
```

Para reproduzir a causa, instalar também `strace` e copiar
`diagnose-client-ipv6.py` para `/opt/unit3d-dualstack/`. Com o backend ativo,
executar sequencialmente, sem outro runner usando os namespaces:

```sh
sudo python3 /opt/unit3d-dualstack/diagnose-client-ipv6.py original
sudo python3 /opt/unit3d-dualstack/diagnose-client-ipv6.py unbound
sudo python3 /opt/unit3d-dualstack/diagnose-client-ipv6.py explicit
```

`original` só passa como **controle negativo** quando reproduz o bind IPv4
inválido, zero download e handshake separado com Transmission. Os controles
positivos exigem o SHA-256 correto. A janela é de 60 segundos e os arquivos
são identificados como diagnóstico; não contam como casos da matriz. Os
controles `original` e `unbound` foram reexecutados com o runner versionado;
`explicit` foi executado no protótipo equivalente, antes de reunir o probe e
as asserções no mesmo arquivo. O relatório registra essa distinção.

O runner funcional retorna código 1 na falha e encerra a sequência. `--backend`
confere backend e validade da lease no SQL; a inicialização permanece externa.
`--case all` executa os oito casos. As asserções dualstack exigem duas famílias
por identidade, resposta com ambas e contabilidade única. Restaurar a fixture
antes de repetir: o runner recusa peers ou histórico anteriores no mesmo caso.

Para Rust, usar `start-candidate-rust.sh resume direct` depois de restaurar a
base e preparar os torrents. Encerrar com SIGTERM, aguardar drenagem e verificar
exit code zero antes de remover o container. Exportar somente os JSONs com
`export-client-results.py <rodada>`, que verifica as passkeys antes de criar
o arquivo permitido para cópia.

Encerrar o tracker com
`sudo bash /opt/unit3d-dualstack/lab/stop-candidate-php.sh`. Verificar
`sudo ip netns list` e ausência de clientes/tcpdump antes de outro ensaio.
A preparação agora limpa recursos próprios mesmo se o construtor falhar.
`test-client-lifecycle.py` comprovou limpeza antes/depois da criação e mudança
da macvlan, depois da configuração de hosts e preservação de namespace
preexistente. Na conclusão das rodadas de clientes, todos os namespaces,
clientes, capturas e containers daquele ensaio foram encerrados. MySQL e Redis
permanecem nas VMs para a etapa seguinte de benchmarks.

Referências das APIs usadas: [qBittorrent 4.1–4.6](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)),
[Transmission 4.0.5 RPC](https://github.com/transmission/transmission/blob/4.0.5/docs/rpc-spec.md)
e [configuração 4.0.5](https://github.com/transmission/transmission/blob/4.0.5/docs/Editing-Configuration-Files.md).
