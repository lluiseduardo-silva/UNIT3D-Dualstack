# TLS/proxy e memória/cache antes da carga

Ordem solicitada pelo usuário: TLS/proxy, depois memória/cache; carga e janela
de perda sob carga ficam por último. Bases: PHP `6d8e743`, Rust `9e8b546`.
Somente laboratório, sem produção, push ou alteração de durabilidade.

1. HTTPS com CA exclusiva do laboratório, validação obrigatória de certificado,
   TLS 1.2/1.3 e origens IPv4/IPv6 reais. Rejeitar CA/hostname incorretos.
2. Proxy Nginx sobrescreve headers de origem; backend só em loopback. Executar
   a mesma matriz no PHP standalone e Rust: headers/endereços alternativos
   forjados, probes positivos/negativos independentes, listas compactas, troca
   de porta e resultado de probe atrasado. Logs sem URI/passkey.
3. Rotação sequencial controlada de endereços IPv6/portas por peer, preservando
   IPv4 e crédito único. No máximo 25 requests/s; não é teste de capacidade.
   Registrar SQL, memória dos processos, tamanho do estado Redis e caches.
   Usar lotes repetidos e janela ociosa para distinguir retenção do allocator
   de crescimento ilimitado. Conferir limite do cache, TTL e cardinalidade.
4. Para observar o cache privado Rust, se necessário, usar cópia isolada com
   diagnóstico somente de contadores, identificada por hashes, sem alterar
   os fontes de produto nem política de probes/persistência. Repetir controle
   curto no binário de produto. PHP usa introspecção read-only do Redis.
5. Investigar qualquer divergência antes de passar à etapa seguinte. Registrar
   resultados brutos, fontes/configurações, limites e checkpoint; conferir
   drenagem e retirar exclusivamente certificados/aliases/regras temporárias
   que precisarem ser retirados. Chaves privadas ficam apenas no laboratório.

Uma revisão final por incremento contra este plano. Não iniciar benchmark de
throughput, comparação longa ou seis horas nesta rodada. Aprovação de memória
se limita à duração, cardinalidade e padrões efetivamente observados.

Execução: a matriz encontrou o middleware PHP de proxy desativado no kernel.
Dentro da autorização para investigar/corrigir falhas antes de avançar, ele foi
ativado com confiança explícita apenas no modo dualstack, preservando o legado.
Passaram 19 controles TLS por backend, 2.048 rotações por backend, um controle
Rust de produto com 256 rotações e um controle PHP de expiração do limitador com
512 rotações/130 s ociosos. Regressões: 39 testes PHP e 19 Rust. Fontes Rust de
produto inalterados. Evidências e limites em `docs/dualstack-tls-memoria.md`.
