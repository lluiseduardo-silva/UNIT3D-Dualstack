# Execução autorizada: baseline Rust original

Pedido de 09/10/2026: preparar e iniciar o Rust original; PHP versus PHP fica
para depois. Registrar separadamente os defeitos preexistentes corrigidos.

## Sequência e gates

1. Preservar no laboratório o banco e a fixture privada da v3 concluída;
   conferir agregados antes/depois e não modificar as evidências v1/v2.
2. Conferir os arquivos da tag Rust `fcd189e9aebf07a12a1f8cc39500819c3870925b`,
   dependências, imagem, compilador, binário e configurações efetivas públicas.
3. Preparar um perfil comum de 10.000 peers IPv4, 40 torrents de 250 peers,
   250 usuários, 80% seeders, `numwant=10`, 8.000 requests/s, origens reais,
   HTTP direto, conectividade desativada nos dois lados. Schema aditivo do
   laboratório, explicitamente distinto do schema original intacto.
4. Executar calibração curta (30 s + 60 s). Somente com respostas, contabilidade,
   drenagem, proteção de recursos e integridade das amostras aprovadas iniciar
   a primeira repetição formal (300 s de aquecimento + 900 s de medição).
5. Fazer três repetições, com fixture limpa e reinício entre elas; interromper
   a sequência na primeira falha, investigar e preservar os dados. Não aplicar
   correções ao original nem ajustar sua cadência de persistência silenciosamente.
6. Coletar agregados públicos, manter amostras compactadas no ZFS e documentar
   os problemas preexistentes com commit, reprodução e limites da evidência.

O candidato terá de repetir este perfil antes do veredito comparativo. A v3
dualstack de seis horas não é o outro lado deste par. Este primeiro perfil
mede custo por request em IPv4; não encerra a matriz 0/50/100% dualstack,
escalas adicionais ou capacidade máxima. Não inicia PHP nem produção.

## Instrumentação

Reutilizar o transporte HTTP, histogramas e amostras limitadas do soak. Adicionar
um executor de comparação com validação específica para um endereço por peer.
O original não mantém `peer_ips`, `state_version` ou lease: não fingir essas
capacidades nem desativar guardas de disco, arquivo, memória ou progresso.
Medir backlog pelos créditos aceitos versus persistidos, com tolerância para
a amostragem. Conferir cada identidade ao final; totais sozinhos não bastam.

Logs limitados; arquivos públicos sem URLs de announce, credenciais ou passkeys.
Supervisor no Proxmox independe desta sessão. Não reiniciar automaticamente
uma execução falha. Verificação final: comparar o diff com este escopo.

## Progresso em 09/10

Preservação v3 e origem da tag verificadas. Calibração v1 falhou por uma
expectativa do auditor sobre IPv4 mapeado; dados preservados, causa confirmada
no código e no banco. Auditor ajustado, produto original intacto. Calibração
v2 aprovada, incluindo replay de 720.000 amostras contra MySQL e integridade.
Dez testes Linux passaram. Série formal iniciada em r1, com gates para r2/r3.
O restante é acompanhamento, coleta e análise; candidato e PHP ficam pendentes.

Revisão final única contra o plano: alterações restritas ao laboratório,
documentação e evidências; árvores PHP/Rust sem mudanças. Auditoria antiga do
soak mantém seu comportamento padrão. Nenhum requisito de correção ou proteção
de recursos foi dispensado; a representação mapeada é aceita somente no auditor
original e a ausência de lease é declarada. Sem desvio de escopo identificado.
