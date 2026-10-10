# Escritor Rust: implementação das otimizações medidas

Autorizado pelo usuário após o diagnóstico de throughput. Base Rust a9ab263,
UNIT3D 6d8e743 e coordenação 89c8c60. Somente laboratório isolado; sem produção
ou push. Preservar o contrato financeiro, o escritor único e o fencing.

1. Drenar lotes cheios sem a pausa artificial de 100 ms. Limitar cada ciclo a
   oito lotes ou 100 ms, verificados entre transações; ceder execução e executar
   manutenção entre ciclos. O timeout transacional permanece em 15 s, com os
   retries existentes. Heartbeat e encerramento continuam supervisionados.
   Acrescentar DUALSTACK_BATCH_SIZE (padrão 200, intervalo 1–500).
2. Validar configuração, contrato compartilhado, MySQL real, retries, rollback,
   concorrência, supervisão, BON/refunds e troca PHP/Rust. Medir a versão de
   produto com lotes 200/500 antes da segunda alteração.
3. Reduzir SQL dos endpoints: registrar quais famílias mudaram na transição;
   coalescer somente transições ainda não confirmadas; remover famílias
   encerradas e fazer upsert das modificadas. Manter snapshot completo do peer,
   confirmação conjunta, versões, revisão, timestamps e projeção legada.
   Nenhuma consulta SQL por announce nem consulta por endpoint.
4. Repetir as validações com remoção/reinserção na mesma família, troca de IP,
   probe atrasado, expiração, replay parcial e rollback. Comparar o mesmo perfil
   de 40 torrents × 250 peers, tráfego embaralhado, com dados brutos, I/O e
   auditoria financeira. Medir 4/6/8/10/12 mil requests/s e ampliar duração no
   patamar sustentável identificado.
5. Registrar resultados, limitações e revisão única do diff contra este plano.
   Commits separados para cadência e endpoints, com checkpoint de coordenação.

Fora deste incremento: sharding de mutex, cache de contadores, UPDATE CASE de
saldos, configuração do SSD/host, regressão do bootstrap de torrents densos e
gate completo de seis horas. Não inferir aprovação de produção destes ensaios.
