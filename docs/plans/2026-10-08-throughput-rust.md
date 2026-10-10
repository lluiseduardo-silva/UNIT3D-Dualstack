# Levantamento de throughput do Rust

Autorização: executar os três itens recomendados, começando pelo gravador,
com validações e evidências para decidir como aumentar throughput.

## Sequência

1. Preservar os produtos em `6d8e7437` (PHP) e `a9ab263d` (Rust).
   Instrumentar uma cópia isolada do Rust: espera e duração dos mutexes,
   publicação, seleção, lotes, etapas SQL, commit e backlog. Comparar o
   observador ligado/desligado antes de interpretar diferenças pequenas.
2. Executar smoke contábil e rampa com 250 peers/torrent, origens reais nas
   duas famílias. Medir separadamente HTTP aceito, transições confirmadas,
   crescimento e drenagem da fila. Sobrecarga esperada não equivale a erro
   funcional; limitar duração e backlog para não alcançar 100 mil pendências.
3. Comparar uma variante experimental que drena lotes completos sem esperar
   o próximo tick. Preservar transação, fence, versões, único escritor,
   heartbeat, manutenção e shutdown. Executar a suíte MySQL real nessa cópia.
4. Usar os tempos de mutex e CPU para avaliar seleção/contagem incremental e
   eventual divisão por torrent. Não promover um redesenho sem evidência.
5. Correlacionar capacidade do escritor com etapas SQL, waits, redo, fsync,
   CPU e I/O das VMs e host. Comparar tamanhos de lote dentro do limite já
   aceito apenas se os dados justificarem. Não relaxar durabilidade.
6. Conferir contabilidade por peer, histórico, usuário e torrent, reentrega,
   restart e encerramento. Guardar resultados públicos, conclusão, limitações
   e próximos ajustes. Remover aliases e encerrar os processos do ensaio.

Refinamentos motivados pelos resultados: embaralhar usuários sem separar a
identidade lógica; pré-calcular somente os campos HTTP constantes no gerador,
conferindo igualdade de bytes antes de usar esse caminho; comparar lotes de
200/500 em três repetições; repetir a faixa de 10/12 mil req/s e sustentar
8 mil req/s por 180 s. O gerador aceita no máximo 12 mil req/s, e uma fila local
crescente impede declarar um teto do servidor a partir dessa fase.

## Controles e limites

- Banco exclusivo `unit3d_dualstack_journal_test`; guards contra escritor ativo.
- Mesmo hardware, compilador, lockfile e política em cada comparação.
- Nenhuma alteração de produção, push, credencial em relatório ou dependência nova.
- Instrumentação limitada e numérica; custo medido e indicado no relatório.
- Gerador deve cumprir a taxa sem drops; medir espera local e CPU para detectar
  um teto do próprio gerador. Rampas curtas não substituem ensaio sustentado.
- Um erro funcional interrompe a sequência até sua causa ser investigada.
- SSD compartilhado e anomalia prévia nos contadores do host impedem atribuir
  causalidade ao disco somente por correlação; separar medição de hipótese.
- Revisão final única: comparar diff e evidências com este plano.
