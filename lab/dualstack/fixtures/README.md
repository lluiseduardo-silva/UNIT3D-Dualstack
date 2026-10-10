# Contrato compartilhado v1

`peer-v1.json` define transições de um peer lógico, independente de backend.
Os valores cumulativos são strings decimais sem sinal; nenhuma implementação
pode convertê-los em ponto flutuante. Tempos são segundos em um relógio controlado
pelo teste, nunca parâmetros aceitos de um cliente HTTP real.

Cada caso começa sem peer. Mesclar `defaults` com `config` do caso e
`request_defaults` com cada operação. `kind` ausente significa `announce`;
`expire` e `probe` são operações internas. `expect` compara apenas os campos
especificados, mas todas as operações sem erro explícito devem ser aceitas.

`state_version` avança uma vez por mutação aceita. Endpoints recebem a versão
da transição quando criados ou quando seu IP/porta muda; a revisão não muda
somente por renovar prazo. Isso permite rejeitar probes de endereços anteriores.
Uma operação ignorada ou recusada não concede crédito nem avança a versão.

Expiração remove somente caminhos vencidos. O cenário de contabilidade usa
intervalo zero para isolar o cálculo; o caso de intervalo usa 1.800 segundos.
Esses parâmetros não alteram os padrões operacionais aprovados.

As fixtures não substituem os ensaios de múltiplos peers, persistência, rede,
contabilidade por usuário/torrent, BON, propriedade exclusiva ou carga.
Os testes PHP e Rust recebem este mesmo arquivo por `DUALSTACK_PEER_FIXTURES`;
nenhum processo de produção depende dele nem do outro backend.
