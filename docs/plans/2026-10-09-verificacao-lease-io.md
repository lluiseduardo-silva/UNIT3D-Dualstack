# Verificação da hipótese de acúmulo e timeout

Autorizada em 09/10/2026: executar a verificação proposta, sem corrigir o produto
nem repetir as seis horas. Preservar o banco, container parado e evidências da v2.

1. Clonar somente dentro do laboratório o banco sintético em um nome exclusivo.
   Executar o binário Rust preservado em outro container/porta. Conferir hashes,
   ausência de escritores no banco anterior, espaço e configuração de durabilidade.
2. Comparar controle sem bloqueio, bloqueio curto e bloqueio prolongado de um
   usuário do banco novo. O bloqueador não toca na propriedade: observar se o
   lote do próprio Rust segura o lock compartilhado da lease e bloqueia sua
   renovação. Registrar cadeia de locks, tempos, respostas e saldo confirmado.
   A falha longa é resultado esperado de reprodução, não aprovação de resiliência.
3. Executar carga curta até 8 mil/s, somente após verificar os controles, com
   contadores de I/O por dispositivo no host e na VM, pressão de I/O, esperas
   SQL, contagem persistida e latência. Não gerar I/O artificial no disco inteiro
   nem interferir nos demais serviços. Interromper se os limites de espaço ou
   saúde forem atingidos. Ausência de falha não comprova a causa histórica.
4. Auditar crédito e endpoints, encerrar apenas os novos processos, confirmar
   que o banco anterior permaneceu igual, documentar conclusão e limites.

O banco novo e as credenciais permanecem no laboratório. Exportar somente
métricas e evidências públicas. Nenhuma alteração de timeout, durabilidade,
pool, hardware, produto, produção ou execução v2 faz parte deste incremento.
