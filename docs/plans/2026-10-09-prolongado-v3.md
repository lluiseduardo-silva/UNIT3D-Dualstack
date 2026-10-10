# Preparação e início da captura prolongada v3

Autorização: seguir as etapas necessárias e iniciar seis horas após os gates.

1. Registrar diagnóstico público limitado das respostas rejeitadas, sem URLs,
   corpos arbitrários ou credenciais; registrar resultado da drenagem mesmo
   quando outra falha já for o motivo principal. Testar ambos os caminhos.
2. Preservar o banco v2 em outro schema local, seu container encerrado e as
   evidências anteriores. Usar o binário corrigido com SHA-256 fixado, sem
   alterar o binário anterior ou os produtos. Conferir espaço e arquivador.
3. Executar cinco minutos a 8.000/s, TTL 7.200, com bloqueio de uma linha de
   usuário por quatro segundos durante a carga. O atraso fica abaixo do limite
   local de admissão; exigir zero erros, crédito exato e recuperação do backlog.
   A suíte específica já cobre pausa/reabertura nos bloqueios de 9/12 segundos.
   Exigir encerramento, auditoria SQL e integridade das amostras aprovados.
4. Passando, iniciar `soak-rust-six-hours-v3`, sem injeção, com perfil anterior:
   10 mil peers/20 mil endpoints, 40 torrents, janelas de 8.000/s e seis horas.
   Confirmar primeira janela, observadores, arquivo e ausência de divergências.
5. Registrar checkpoint, evidências e commits locais em português, sem push.
   Reativar acompanhamento somente da v3, silencioso enquanto saudável.

Nenhuma aprovação antecipada do prolongado, do PHP ou do comparativo formal.
Preservar limites dos guards e métricas; não mascarar erros durante a injeção.
Se falhar, investigar e corrigir o necessário antes de iniciar seis horas;
mudança de grande impacto exige apresentar evidências ao operador.
