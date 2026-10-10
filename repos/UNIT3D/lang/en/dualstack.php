<?php

declare(strict_types=1);

return [
    'peer-group-help'      => 'Session groups use user, client and peer ID across torrents. IP groups count each peer once per address; a dualstack peer appears in two IP groups. User and session groups show distinct address and port counts. Upload and download are logical peer totals within each group.',
    'endpoint-expired'     => '(expired)',
    'deletion-unavailable' => 'The tracker cannot confirm this deletion right now. Please try again later.',
    'cleanup-queued'       => 'Cleanup requested. The tracker will close eligible endpoints; accounting references are retained.',
    'cleanup-unavailable'  => 'The cleanup request could not be confirmed. Try again when the standalone tracker is available.',
    'cleanup-quota'        => 'You can only flush twice a day.',
    'peer-count-mode'      => 'Peer counts',
    'peer-count-sum'       => 'Unique peers (IPv4 and IPv6)',
    'peer-count-ipv4'      => 'IPv4',
    'peer-count-ipv6'      => 'IPv6',
    'peer-count-auto'      => 'Automatic',
    'peer-count-help'      => 'Display only. Automatic follows your active seeding, then other active peers, and updates daily. Both families or no activity shows unique peers; dualstack is counted once.',
];
