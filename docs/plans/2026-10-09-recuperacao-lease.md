# Recuperação do coordenador Rust

Autorizado após a reprodução registrada em `docs/dualstack-lease-io.md`.

1. Renovar entre operações do escritor, mantendo o fence SQL por geração.
   Separar pausa temporária de fechamento definitivo da entrada.
2. Aguardar a operação em andamento quando vencer a validade local de entrada
   ou chegar uma parada; não descartar sua future por erro de outro ramo.
   Manter os limites existentes de cada operação SQL.
3. Em falha transitória, pausar entrada, confirmar novamente a mesma lease e
   reaplicar somente versões não confirmadas. Drenar antes de reabrir. Limitar
   a recuperação a 120 segundos; lease expirada ou substituída não é readquirida.
   Falha definitiva informa geração e quantidade de transições pendentes.
4. Validar em MySQL real: bloqueio de usuário de 9 s e superior a 10 s,
   renovação bloqueada, parada durante transação, commit seguido de reentrega,
   expiração e troca de proprietário. Usar banco/cópia separados da v2.
5. Repetir carga curta de 4 mil/s e 8 mil/s após os gates funcionais. Confirmar
   crédito, endpoints, drenagem e comparabilidade; registrar resultados e commits.

Sem alterar schema, PHP, durabilidade MySQL ou remover fencing. Sem restart
das seis horas, push ou produção. Não promete recuperar memória perdida por
crash nem transferir a fila antiga para outra geração; perda real da propriedade
permanece uma falha fechada e explícita.
