# Correção do inventário e nova campanha prolongada

Continuidade autorizada pelo usuário após o diagnóstico de `soak-rust-six-hours-v1`.
Escopo: inventário do laboratório, testes, evidências e nova execução; produtos
PHP/Rust e parâmetros da carga permanecem iguais.

1. Repetir somente a divergência entre lista de binlogs e arquivo ativo, com
   até três tentativas, pausas de 100/200 ms e orçamento total de cinco segundos.
   Cada consulta recebe o tempo restante. Erros SQL, formato inválido e timeout
   continuam interrompendo a operação. Nenhuma leitura parcial é publicada.
2. Testar recuperação, tentativas esgotadas, orçamento esgotado e falhas não
   transitórias. Executar rotação real entre as consultas no MySQL do laboratório
   e conferir a contabilidade antes/depois, sem alterar dados de peers.
3. Atualizar o módulo compartilhado por observador/arquivador de forma atômica,
   preservando configuração e checagens de segurança. Rodar um novo ensaio de
   cinco minutos com arquivo ativo e auditar dados/amostras.
4. Após aprovação, revisar uma vez o diff, registrar checkpoint e iniciar
   `soak-rust-six-hours-v2`, por seis horas completas. Preservar a execução v1,
   confirmar a primeira janela e atualizar o acompanhamento existente.

Falha em qualquer gate exige diagnóstico antes de continuar. Não relaxar o
heartbeat de 30 s, os limites de espaço/backlog ou as verificações do binlog
ativo. Não usar lock MySQL para impedir a rotação.
