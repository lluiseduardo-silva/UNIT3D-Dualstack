# Preparação do armazenamento para o ensaio prolongado

Escopo autorizado: preparar o laboratório, sem iniciar a campanha de seis horas.
O SSD mantém MySQL, redo e binlog ativo; ZFS recebe binlogs fechados e resultados.
Não alterar a durabilidade do banco nem os demais projetos do host.

1. Criar dataset exclusivo com quota e reserva de 300 GiB, três filhos e
   mapeamentos VirtioFS para as VMs 120–122. Encerrar os serviços e reiniciar
   somente essas VMs. Verificar montagem persistente, isolamento e fsync.
2. Instalar arquivador serial de binlogs fechados. Conferir UUID do servidor,
   montagem, tamanho e SHA-256; sincronizar arquivo e diretório antes da purga
   SQL. Nunca remover arquivos diretamente do datadir. Falhas impedem a purga.
   Não aceitar réplicas conectadas/configuradas neste laboratório exclusivo.
3. Arquivar o passivo, recuperar espaço e verificar pelo menos 20 GiB livres
   na VM de dados. Preservar tabelas, créditos e configurações de durabilidade.
4. Validar repetição, ausência de montagem, corrupção, arquivo parcial e
   concorrência do arquivador. Medir uma cópia com commits concorrentes;
   esse ensaio de infraestrutura não substitui o benchmark da aplicação.
5. Registrar resultados, procedimento de operação/retorno e pendências.
   Fazer uma revisão final do diff contra este escopo e commit local.

O gerador atual acumula amostras em RAM. Adaptar sua coleta para memória limitada
continua sendo requisito antes de iniciar seis horas, fora desta preparação de
armazenamento. Arquivos arquivados podem conter dados privados: ficam no lab,
com acesso restrito, e não são incluídos no Git.
