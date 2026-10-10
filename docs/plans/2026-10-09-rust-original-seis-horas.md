# Execução autorizada: seis horas do Rust original

Pedido: “faz o ensaio de 6h nele tbm”. Executar somente o Rust original 0.3.1,
sem alterar produto ou suas cadências de flush/expiração. Preservar os resultados
do baseline formal e as evidências das execuções dualstack anteriores.

1. Conferir armazenamento, ausência de carga concorrente neste laboratório e
   proveniência do binário original. Continuar usando os observadores e as
   proteções de SSD, thin pool, arquivo, memória, processo e atraso contábil.
2. Ampliar apenas o executor: 300 s de aquecimento **mais 21.600 s de medição**,
   em 72 janelas medidas de 300 s. Mesmo perfil de 8.000 req/s, 10.000 peers,
   40 torrents de 250 peers, 250 usuários, IPv4 real e `numwant=10`.
3. Renovar os 2.000 leechers entre janelas, sem evento, `numwant=0`, `left`
   preservado e zero tráfego. Registrar e auditar essas amostras separadamente
   dos seeders que acrescentam 100 bytes por announce. Não estender o TTL para
   ocultar a necessidade de renovação. Sem rotação de IPs ou expiração provocada.
4. Verificar o executor no Linux e executar ensaio de cinco minutos (60 s de
   aquecimento + 240 s medidos; janelas de 60 s). Exigir zero erros/divergências,
   drenagem, SHA-256/CRC/cardinalidade e replay por identidade contra MySQL.
5. Somente após esses gates, iniciar `rust-original-six-hours-v1` no supervisor
   do Proxmox e ativar acompanhamento nesta conversa. Não reiniciar uma falha.
6. No término: confirmar drenagem, integridade e replay contra MySQL antes de
   qualquer reset, coletar JSONs públicos, analisar janelas/recursos/crédito e
   documentar resultado. Commit local em português, sem push.

A medição oferecerá 172.800.000 announces de seeders, além de 2.400.000 no
aquecimento e 146.000 renovações de leechers (73 × 2.000). Crédito esperado:
17.520.000.000 bytes; as renovações não geram crédito. A carga dura seis horas
e cinco minutos, mais pausas curtas entre janelas, preparação, drenagem e
auditoria. Não é carga ininterrupta; as janelas não têm consultas SQL do gerador.

O resultado avalia sustentação prolongada do original neste perfil estável.
Não aprova PHP, dualstack no original ou a comparação formal original/candidato:
a execução dualstack v3 usou renovação, rotação e expiração diferentes.

## Progresso

Preflight e 13 testes Linux aprovados. A calibração v1 expôs a expectativa
incorreta do auditor sobre IPv4 mapeado em `peers6` após renovação. Evidências
preservadas; somente a auditoria foi ajustada para a representação original,
sem dispensar identidade, contagem, crédito ou formato canônico no candidato.
Calibração v2 passou com 2.410.000 amostras, crédito exato e drenagem. Ensaio
longo iniciado às 20:27:07 de 09/10, Brasília, e encerrado com drenagem aprovada
às 02:33:21 de 10/10. As seis horas medidas passaram, com 175.346.000 aceitos
incluindo aquecimento e renovações, zero erros, crédito exato e replay completo
aprovado antes de qualquer reset. Evidências públicas coletadas, séries analisadas
e acompanhamento desativado. A variação de latência durante o ensaio está
explicitada no relatório, sem atribuição causal não demonstrada.

Revisão contra o escopo: mudanças restritas ao executor, auditoria,
proveniência pública e documentação; repositórios de produto intactos.
O perfil curto mantém duas janelas e seus limites. A diferença de payload do
original renovado está explicitamente registrada, sem alegar comparação
equivalente com o baseline curto ou aprovação antecipada da execução longa.
