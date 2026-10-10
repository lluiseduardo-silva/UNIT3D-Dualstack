# Preparativos finais e início do ensaio prolongado

Autorizado pelo usuário: concluir os preparativos e iniciar seis horas após os
gates curtos. Primeiro alvo: Rust de produto `9e8b546`, batch 500, 10 mil peers
dualstack em 40 torrents de 250 peers. HTTP direto pelas duas famílias, mesma
durabilidade do banco. PHP e comparação formal com as tags são etapas separadas.

1. Coletor com histogramas de precisão explícita, amostras binárias comprimidas
   em segmentos no ZFS e fila limitada. Testar precisão, formato, falhas e limite
   de memória. Não alterar os geradores históricos nem os produtos.
2. Renovar leechers; manter carga de 8 mil/s em janelas de 60 s. Entre janelas,
   conferir créditos, realizar entrada/saída e rotação de endereço de peers de
   controle. Um controle perde IPv6 pelo TTL real de 7.200 s mantendo IPv4.
3. Supervisor independente no Proxmox e observadores nas VMs, via guest agent,
   sem distribuir chaves SSH. Interromper carga por erros, heartbeat ausente,
   backlog crescente, memória ou espaço insuficiente; drenar o tracker e salvar
   estado. A carga não depende da sessão do Codex/SSH.
4. Gates: testes do coletor/guards, ensaio funcional acelerando somente TTL no
   perfil de teste, três pares curtos com/sem arquivo, e ensaio representativo
   com configuração definitiva. Investigar falha antes de iniciar seis horas.
5. Registrar os parâmetros e evidências, revisar uma vez o diff contra este
   plano, fazer checkpoint local e iniciar a execução. Confirmar progresso real
   antes de reportar início. Guardar resultado final e motivo de interrupção.

Critérios de início: zero divergência contábil, erro HTTP ou perda no gerador;
throughput nas janelas >=95% da taxa; fila drena; espaço inicial aprovado pelo
preflight; observadores e encerramento por falha testados. Comparação do arquivo:
p95/p99 até +10% com carga e gerador idênticos; investigar variabilidade se falhar.
O gate é do perfil curto, não constitui aprovação antecipada das seis horas.

Parada conservadora: SSD dados <8 GiB, SSD outras VMs <1 GiB, arquivo <20 GiB,
thin pool físico <8 GiB, memória disponível <512 MiB, observador sem atualização
por 30 s, arquivo sem progresso por 240 s, backlog de arquivo >4 GiB,
persistência atrasada >40 mil transições por 30 s ou falha do serviço. O monitor
usa 80 mil como limite observado para descontar até 40 mil requests que cabem
entre duas amostras SQL de cinco segundos; não mistura esse atraso da coleta
com a fila real.

O supervisor pode devolver blocos já descartados somente na VM 121 usando
`fstrim /` quando o thin pool ficar abaixo de 16 GiB, no máximo uma vez a cada
300 s. O limite de parada de 8 GiB continua obrigatório. Nenhum volume de outro
projeto é manipulado.
