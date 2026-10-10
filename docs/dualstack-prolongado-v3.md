# Captura prolongada Rust v3 — 09/10/2026

**Aprovada a execução Rust de seis horas no perfil descrito abaixo.** A carga
começou em **09/10/2026 às 12:12:14 de Brasília**; o supervisor concluiu a
drenagem e a limpeza às **18:12:36**. As auditorias posteriores de SQL e de
todas as amostras aceitas passaram. Execução: `soak-rust-six-hours-v3`.

Esta aprovação cobre estabilidade e consistência desta carga no Rust corrigido.
Não aprova PHP, implantação em produção nem os limites de regressão do
comparativo formal original/candidato. A causa física da pausa histórica de
I/O continua sem isolamento; o sucesso da v3 não a identifica.

## Resultado final

| Critério | Resultado |
|---|---:|
| Tempo registrado pelo gerador | 21.601,06 s |
| Announces aceitos / erros | 171.427.236 / 0 |
| Announces principais / de preparação e controle | 170.004.515 / 1.422.721 |
| Janelas completas / última parcial | 354 / 1 de 10,564 s |
| Throughput mínimo / mediano por janela completa | 7.999,20 / 7.999,95 requests/s |
| Mediana dos p95 / p99 de resposta por janela | 0,246 / 0,330 ms |
| Crédito esperado e persistido em cada conjunto | 8.500.225.800 bytes |
| Divergências de crédito, versão, limite de seedtime e BON da fixture | 0 |
| Peers lógicos / endpoints finais | 10.000 / 20.000 |
| Seeders / leechers únicos | 8.000 / 2.000 |
| Endpoints IPv4 / IPv6 | 10.000 / 10.000 |
| Segmentos / amostras verificados por SHA-256, CRC e cardinalidade | 355 / 171.427.236 |
| Drenagem, liberação da lease e remoção dos aliases | Aprovadas |

`six-hours-v3-accepted-samples-audit.json` reconstrói o crédito a partir de
todas as respostas aceitas e o compara individualmente com peers, histórico
e usuários. Não houve crédito aceito sem persistência. O banco tem
**171.427.237 versões**, uma a mais que os requests: a auditoria restringiu
essa diferença ao único peer de controle de expiração. Os outros 9.999 peers
têm exatamente suas versões esperadas. Não há violação do limite de endpoints.

A expiração independente foi observada aos **7.221 s**, com 19.999 endpoints
e os mesmos 10 mil peers. O controle confirmou a ausência do IPv6 e o
restabeleceu por announce; `expiry_checked` e `restored` terminaram verdadeiros.
As auditorias por janela também conferiram rotação de endereço, porta,
contadores por família e total lógico (`lab/dualstack/soak-load.py:33`).
O TTL permaneceu em 7.200 s durante a execução.

Os limites de seedtime passaram e o BON permaneceu zero nesta fixture; isso
não é uma homologação de regras de remuneração. Os contadores cumulativos de
deadlocks/timeouts do MySQL continuaram em **3/18**, sem incremento em relação
ao início, conforme a verificação por janela
(`lab/dualstack/soak-load.py:345`). Houve zero failed jobs e zero reinícios do
MySQL. Após a drenagem, a geração **1953** estava liberada (`live=0`).

## Desempenho e recursos ao longo das seis horas

Os percentis abaixo são **medianas dos percentis de cada janela**, não percentis
globais de 171 milhões de requests. A última janela parcial usa seus 10,564 s
reais no denominador. As pausas entre janelas para manutenção e auditoria
fazem parte do perfil; não se trata de seis horas de carga ininterrupta.

| Hora | Mínimo por janela (requests/s) | p95 mediano (ms) | p99 mediano (ms) | RSS mediano Rust (MiB) |
|---|---:|---:|---:|---:|
| 1 | 7.999,53 | 0,243 | 0,326 | 32,15 |
| 2 | 7.999,92 | 0,245 | 0,328 | 32,71 |
| 3 | 7.999,90 | 0,246 | 0,331 | 33,20 |
| 4 | 7.999,90 | 0,250 | 0,336 | 33,16 |
| 5 | 7.999,20 | 0,247 | 0,331 | 32,98 |
| 6 | 7.999,60 | 0,245 | 0,328 | 32,77 |

Não aparece degradação sustentada nessas séries. Houve, porém, eventos
transitórios que devem permanecer visíveis:

- **Persistência:** diferença amostrada máxima de **89.007 versões** entre
  aceitos e persistidos. Ultrapassou 80 mil em duas amostras consecutivas;
  cinco segundos após o pico estava em 56.507 e mais cinco segundos depois,
  em 12.184. Inclui a defasagem dos observadores, portanto não mede a fila
  interna exata. O guard de 80 mil por 30 s não foi acionado. O valor final
  foi zero; a auditoria final confirma todos os efeitos persistidos.
- **Memória Rust:** pico de **125,31 MiB RSS**, na mesma região temporal do
  maior atraso de persistência, com retorno a **32,89 MiB** na última amostra.
  As medianas horárias ficaram entre 32,15 e 33,20 MiB. Não foi observado
  crescimento acumulativo nessa duração. O pico de PSS foi 125,81 MiB.
- **Gerador:** somente a janela 20 teve p99 de espera antes do envio acima
  de 10 ms: **211,05 ms**, com p99 total de **211,48 ms**. O p99 de resposta
  dessa janela foi **0,626 ms** e o throughput, 7.999,95/s. A métrica separa
  espera no gerador de tempo após iniciar o request
  (`lab/dualstack/soak_metrics.py:56`); não há evidência suficiente para
  atribuir a causa física dessa espera ao SSD ou ao tracker. A maior resposta
  individual foi 28,69 ms; o maior tempo total individual, 248,61 ms.

O coletor teve pico de dois blocos pendentes e terminou vazio. Seu processo
terminou com cerca de 65,4 MiB RSS; o MySQL foi de aproximadamente 1,46 para
1,55 GiB RSS. A checagem de conectividade esteve desligada: esta execução não
mede o cache de conectividade. Ela cobre a rotação dos endpoints e a memória
do caminho de announce/persistência nesse perfil.

O arquivador permaneceu saudável, sem falhas amostradas. A maior idade do
arquivo foi **51,60 s**, diante do limite de 240 s; o backlog máximo de binlogs
fechados foi aproximadamente **1,00 GiB**, diante do limite de 4 GiB, e terminou
em zero. O menor espaço livre foi **23,29 GiB** no SSD dos dados,
**261,36 GiB** no ZFS e **30,36 GiB** no thin pool. Não houve acionamento das
proteções de armazenamento, memória ou observador desatualizado.

As amostras comprimidas ocupam **3.744.438.719 bytes** e ficaram no ZFS. Foram
exportados somente JSON/JSONL públicos, incluindo seu manifesto, sem binlogs,
passkeys, credenciais, mapa de identidades ou fixture privada.

## Preparação e escopo

Plano autorizado: `docs/plans/2026-10-09-prolongado-v3.md`. O Rust executa o
commit `36823b5fab72940c0dcb90b0ed456b28c18160cc`, cuja correção da lease já
passou nos gates de `docs/dualstack-recuperacao-lease.md`. Nenhum fonte PHP ou
Rust foi modificado nesta preparação.

O binário executado tem SHA-256
`25a9860c6caad0d78e2c3f8073f6ecd6822c05cbcd1b45773d0994a7df6d6833`.
`soak-backend.py:15` seleciona a cópia validada e confere o hash antes/depois
do build. O checkout e o binário usados na v2 continuam intactos.

Antes de reutilizar `unit3d_dualstack_journal_test`, `preserve-soak-v2.py`
copiou a v2 para **`unit3d_dualstack_soak_v2_evidence`**, exclusivamente dentro
da VM de dados. As 142 tabelas tiveram suas cardinalidades conferidas e os
agregados originais ficaram iguais. O container encerrado foi preservado como
**`unit3d-ds-rust-soak-v2-evidence`**. A fixture privada ficou em
`/opt/unit3d-dualstack/evidence-soak-v2/` na VM de clientes. Nenhum dump,
credencial ou binlog foi exportado. O checkpoint anterior foi salvo em
`results/soak/six-hours-v2-checkpoint-preserved.json`.

O laboratório agora registra rejeições com status HTTP, tamanho, SHA-256 e
códigos conhecidos (`soak_diagnostics.py:12`), sem corpo arbitrário ou URL.
Guarda no máximo 16 diagnósticos (`soak-load.py:288`). Uma falha de drenagem
ganha campo próprio, preservando o motivo principal anterior
(`soak-supervisor.py:175`). A auditoria final admite a transição adicional da
expiração; a restrição individual ao peer de controle continua no gerador.

## Gate de cinco minutos

`soak-rehearsal-v3` usou 10 mil peers, 20 mil endpoints, 40 torrents e janelas
de 8.000 requests/s. Aos 30 segundos, uma transação reteve uma linha de usuário
por **4,007 s**, sem modificar dados (`soak-load.py:293`). A injeção foi aplicada
somente no ensaio curto; a captura de seis horas não contém injeção.

| Critério | Resultado |
|---|---:|
| Testes automatizados do laboratório | 6 aprovados |
| Announces aceitos / erros | 2.392.759 / 0 |
| Crédito em peers, histórico e usuários | 118.636.200 em cada conjunto |
| Divergências individuais de crédito/versão/BON/seedtime | 0 |
| Peers / endpoints | 10.000 / 20.000 |
| Throughput mínimo por janela | 7.999,57/s |
| Mediana dos p95 / p99 por janela | 0,238 / 0,316 ms |
| Segmentos / amostras com SHA-256, CRC e contagem verificados | 5 / 2.392.759 |
| Fila máxima do coletor | 2 blocos |
| Encerramento, drenagem, lease liberada e aliases removidos | Aprovados |

O gerador também exigiu que os contadores de deadlocks/timeouts do banco não
aumentassem. A auditoria final mostra os valores cumulativos preexistentes
3/18, não três/dezoito erros nesta execução. Não houve divergência de contagem
por família nem duplicação de conclusão.

A maior diferença amostrada entre aceitos e persistidos foi 41.610 versões;
ela inclui defasagem do observador de cinco segundos, portanto não equivale à
fila interna exata. Ao final, todas as versões aceitas estavam confirmadas.
O ensaio não cobre o TTL real de duas horas nem aprova estabilidade por seis
horas. Os bloqueios de 9/12 s e perda real de propriedade foram tratados pela
suíte específica da correção, sem afrouxar os guards do prolongado.

## Perfil executado

Plano: `lab/dualstack/plans/soak-rust-six-hours-v3.json`. Mantém 21.600 segundos,
TTL 7.200 s, batch 500, 250 usuários, 40 torrents com 250 peers, 80% seeders,
duas famílias de origem reais e HTTP direto. As janelas de até 60 s oferecem
8.000 requests/s; há manutenção e auditoria entre elas. Não é tráfego contínuo
sem pausas, teste de throughput máximo ou comparativo formal original/candidato.
Conectividade continua desligada neste perfil; PHP e TLS/proxy não são avaliados
por esta execução.

O preflight imediatamente anterior encontrou aproximadamente 24,4 GiB livres
no SSD da VM de dados, 4,1 GiB no tracker, 6,0 GiB nos clientes e 280,9 GiB no
ZFS. O arquivador estava ativo, atualizado e com backlog abaixo do limite de
início. Durabilidade e limites de segurança permanecem os anteriores.

Confirmação inicial aos 158 s: 1.261.626 announces aceitos, zero erros e fila
do coletor vazia. A primeira janela confirmou 480 mil requests, 7.999,97/s,
p95 de 0,240 ms e p99 de 0,326 ms. Os três observadores estavam saudáveis.
Esses números confirmam o início; não antecipam o resultado das seis horas.

Status no host `root@10.0.1.4`:
`/storage_pool/unit3d-dualstack/supervisor/soak-rust-six-hours-v3/status.json`.
Unidade: `unit3d-soak-supervisor-soak-rust-six-hours-v3.service`.
Parar a unidade interrompe a entrada e solicita drenagem; não reiniciar
automaticamente se ocorrer falha. As amostras completas continuam no ZFS.

O encerramento confirmou `status=passed` e `tracker_drain.status=passed`.
Foram executados `verify-soak-samples.py` no host e `inspect-soak-final.py`
mais `audit-soak-samples.py` na VM de clientes, sempre com o nome desta execução.
As evidências públicas foram coletadas com `collect-soak.ps1` e resumidas com
`summarize-soak.py`. Nenhum teste foi reiniciado nem houve modificação do Rust
ou PHP durante a análise. Falha física ou perda real de propriedade ainda
pode impedir persistência da fila volátil; esta aprovação não muda esse limite.

O acompanhamento `acompanhar-dualstack-seis-horas-v3` foi **desativado
(`PAUSED`)** após a conclusão e as auditorias. Durante a execução, verificou
o estado a cada 15 minutos; as proteções rodaram independentemente no Proxmox.
[Documentação oficial de tarefas agendadas](https://learn.chatgpt.com/docs/automations?surface=app).

## Evidências

`lab/dualstack/results/soak/rehearsal-v3-validation.json`, os resultados
`rehearsal-v3-*`, a pasta `soak-rehearsal-v3/` e os registros de preservação
`v3-preserved-*` contêm o gate. `six-hours-v3-setup.txt` e os snapshots
`six-hours-v3-start-*` registram o início; não são resultado final.

O resultado final está em `lab/dualstack/results/soak/`:

- `soak-rust-six-hours-v3/`: status final, drenagem, 355 janelas, séries dos
  três observadores, monitor do supervisor e manifesto das amostras.
- `six-hours-v3-sample-integrity.json`: SHA-256, CRC e cardinalidade aprovados.
- `six-hours-v3-final-accounting.json`: SQL após encerramento e lease liberada.
- `six-hours-v3-accepted-samples-audit.json`: reconstrução individual a partir
  de todas as amostras aceitas e comparação com o banco.
- `six-hours-v3-summary.json` e `six-hours-v3-series-analysis.json`: métricas,
  evolução horária, pico de atraso, memória e janela de espera no gerador.
- `six-hours-v3-validation.json` e `six-hours-v3-evidence-manifest.json`:
  conferência cruzada dos resultados e hashes dos arquivos públicos.

As evidências v1/v2, o schema `unit3d_dualstack_soak_v2_evidence` e o container
`unit3d-ds-rust-soak-v2-evidence` não foram modificados nesta auditoria.

Revisão final contra o plano: alterações limitadas ao laboratório, diagnóstico,
auditoria e preparação da v3. O perfil de produto e os guards permaneceram
iguais; histórico e evidências anteriores foram preservados.
