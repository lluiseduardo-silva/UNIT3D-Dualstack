# Encerramento abrupto Rust: controle curto

Continuidade da validação autorizada, depois do bootstrap `9e8b546`.
Somente laboratório, HTTP real IPv4/IPv6 e banco descartável. Sem alteração
dos produtos, configurações de durabilidade ou política de lease.

1. Confirmar referência e crédito em MySQL; encerrar o container Rust com
   SIGKILL, aguardar a expiração natural da propriedade e reiniciar.
2. Conferir endpoints, referência, crédito e reenvio nas duas famílias.
3. Bloquear uma linha de usuário no MySQL, gerar uma rajada curta de announces
   aceitos, confirmar que o SQL ainda guarda a referência anterior e encerrar
   o processo antes de liberar o bloqueio. Conferir rollback e ausência de
   efeitos parciais, aguardar a lease e reiniciar.
4. Medir transições aceitas ainda não confirmadas, validar que um novo announce
   cumulativo recupera o delta uma vez e que repetir o contador não duplica crédito.
5. Encerrar o laboratório e registrar fontes, resultados e limitações.

É um controle de correção com falha provocada, não uma medição da distribuição
da janela de perda sob carga sustentada nem uma comparação com a tag original.
Não ampliar esse resultado para SIGKILL de MySQL/VM ou seis horas. Um erro
observado será investigado antes do próximo cenário. Revisão final única.
