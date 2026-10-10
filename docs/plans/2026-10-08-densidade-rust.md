# Medição exploratória de densidade no Rust

Pedido: medir início do efeito de peers por torrent, interferência sobre outros
torrents e maior patamar sem degradação grande. Referência do operador: até 250
peers por torrent no pior caso esperado, normalmente muito menos. Concentrações
acima disso são exploratórias, não requisitos de aprovação ou limites do produto.

Preservar Rust `a9ab263` e PHP `6d8e7437`; usar apenas as VMs e o banco
`unit3d_dualstack_journal_test`. Preparar estatísticas antes do bootstrap,
aguardar os listeners e manter a falha de plano SQL anterior como pendência.
Não alterar algoritmos, durabilidade nem hardware para estes ensaios.

## Método

- Gerar usuários reutilizados entre torrents; um peer por usuário/torrent.
- Usar 100% dualstack, 80% seeders e 20% leechers residentes, com conexões de
  origem IPv4/IPv6 reais e contabilidade compartilhada. Tráfego sintético frequente
  é estresse, não previsão da cadência real de announces de um tracker privado.
- `numwant=10` e torrents com pelo menos 50 peers mantêm as listas com os mesmos
  dez peers lógicos e vinte endpoints, isolando o efeito da população sobre a
  seleção. Contadores do envelope podem mudar a quantidade de dígitos.
- Curva inicial: 50, 100, 150, 250, 500, 1.000, 2.500, 5.000, 10.000, 20.000
  e 40.000 peers; taxa fixa de 1.000 req/s. Todos os torrents ficam residentes
  e somente o alvo muda entre fases. Repetir em ordem inversa e refinar os
  cruzamentos relevantes antes de descrever um intervalo de limite.
- Interferência: grupo sentinela de torrents pequenos medido separadamente.
  Aumentar quantos torrents densos estão recebendo requests, primeiro com carga
  total fixa e depois com taxa fixa por torrent. Incluir densidade operacional
  de 250 e densidade exploratória maior. Limitar inicialmente a 2.000 req/s e
  registrar explicitamente o maior patamar testado se não houver cruzamento.
- Janelas curtas para varredura, repetições maiores nos controles e fronteiras.
  Um único resultado ruidoso não estabelece um teto. Medir latência até receber
  o corpo, custo de validação, espera no gerador, p95/p99, conclusões por janela,
  erros, CPU, memória e I/O. Não tratar percentis somados/subtraídos como percentis.
- Comparação principal com a própria versão candidata em baixa densidade.
  Não confundir população total residente, peers por torrent e requests/s.

## Critério descritivo, sem novo gate de produto

Mostrar alterações de 10%, 25% e 50% e seus valores absolutos. Sinalizar como
degradação grande p99 pelo menos 50% **e** 0,5 ms acima do controle comparável,
ou erros/descartes/incapacidade de acompanhar a carga. O limite é condicionado
à taxa, mix, máquina e janela testados; não é uma constante universal do tracker.

## Verificações e encerramento

Antes da curva, smoke com mais de um torrent por usuário e famílias alternadas.
Em cada fase, confirmar versões por request aceito, créditos por peer/histórico
e soma por usuário, contagens e endpoints de cada torrent na resposta. Não
executar varreduras SQL periódicas durante as janelas medidas. Falha funcional
interrompe a sequência e preserva os dados; degradação exploratória documenta o
limite e orienta o próximo ponto. Exportar somente dados numéricos sem credenciais.

Registrar resultados no repositório, fazer uma revisão final do diff contra este
plano e um checkpoint local. Ao terminar, drenar o backend, remover aliases e
verificar lease, processos e consultas remanescentes. Sem push ou produção.
