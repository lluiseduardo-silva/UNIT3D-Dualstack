# Inicialização Rust: reconciliação e cancelamento

Continuação autorizada pelo usuário. Bases: coordenação `d2df124`, Rust
`9446bfd`, PHP `6d8e743`. Somente laboratório isolado; sem produção ou push.

Problemas confirmados: a reconciliação usa seis EXISTS correlacionados por peer
(`src/dualstack/persistence.rs:165`); o timeout externo descarta a future sem
confirmar encerramento da consulta MySQL (`src/dualstack/coordinator.rs:170`).
O ensaio anterior registrou mais de um bilhão de linhas examinadas e UPDATE
ativo depois da saída do processo. Estatísticas preparadas contornaram o caso,
sem corrigir o produto. Preservar essa evidência histórica.

1. Reproduzir cancelamento com consulta bloqueada no MySQL real e identificar
   exclusivamente a conexão do bootstrap. Examinar os planos SQL com dados
   distribuídos e concentrados, sem depender de ANALYZE TABLE corretivo.
2. Agregar famílias por identidade uma vez, depois agregar peers por torrent.
   Manter contagem única, visibilidade, conectividade configurada e reconciliação
   sem TTL antes das transições de expiração. Nenhum crédito será recalculado.
3. Reservar conexão de trabalho e conexão de controle na inicialização. Em
   timeout ou cancelamento, encerrar somente a conexão de trabalho e confirmar
   sua saída do servidor antes de liberar a propriedade. Não devolver uma
   conexão com operação em voo ao pool. A limpeza assíncrona deve sobreviver
   ao cancelamento da future chamadora enquanto o runtime estiver ativo.
   Manter o limite de 120 s; não ampliar timeout nem privilégios globais.
4. Validar timeout, cancelamento externo, rollback, recuperação, exclusão de
   segundo proprietário e falha de limpeza explicitamente sinalizada. Usar
   bloqueios reais, conferir PROCESSLIST/locks e preservar consultas alheias.
   Verificar contadores com famílias mistas, inativos, invisíveis e probes.
5. Medir bootstrap em 1 mil, 54 mil e 100 mil peers, distribuídos e concentrados,
   com plano desfavorável no controle e agregação nova. Registrar planos, duração,
   linhas examinadas e contabilidade; controlar espaço de disco antes de cada
   rodada. Repetir as suítes afetadas, registrar checkpoint e commits.

Uma revisão final do diff contra este plano. Fora deste incremento: SQL normal
de persistência, políticas financeiras, seleção incremental, sharding, configuração
do host/SSD, produção e ensaio de seis horas. Falhas encontradas nos testes serão
investigadas dentro deste escopo antes do avanço, conforme autorização do usuário.
