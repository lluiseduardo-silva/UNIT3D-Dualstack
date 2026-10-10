<?php

declare(strict_types=1);

return [
    'peer-group-help'      => 'Sessões agrupam usuário, cliente e peer ID entre torrents. Grupos por IP contam cada peer uma vez por endereço; um peer dualstack aparece em dois grupos de IP. Grupos por usuário e sessão mostram quantidades distintas de endereços e portas. Upload e download são totais dos peers lógicos em cada grupo.',
    'endpoint-expired'     => '(expirado)',
    'deletion-unavailable' => 'O tracker não pode confirmar esta exclusão no momento. Tente novamente mais tarde.',
    'cleanup-queued'       => 'Limpeza solicitada. O tracker encerrará os endpoints elegíveis, preservando as referências contábeis.',
    'cleanup-unavailable'  => 'Não foi possível confirmar a solicitação de limpeza. Tente novamente quando o tracker standalone estiver disponível.',
    'cleanup-quota'        => 'Você pode solicitar apenas duas limpezas por dia.',
    'peer-count-mode'      => 'Contagem de peers',
    'peer-count-sum'       => 'Peers únicos (IPv4 e IPv6)',
    'peer-count-ipv4'      => 'IPv4',
    'peer-count-ipv6'      => 'IPv6',
    'peer-count-auto'      => 'Automático',
    'peer-count-help'      => 'Altera apenas a exibição. Automático acompanha seu seeding ativo, depois os demais peers ativos, com atualização diária. Ambas as famílias ou nenhuma atividade mostram peers únicos; dualstack conta uma vez.',
];
