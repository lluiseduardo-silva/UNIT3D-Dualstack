<?php

declare(strict_types=1);

return [
    // Ativar somente depois de drenar escritores antigos e concluir o backfill.
    'enabled'                    => env('DUALSTACK_ENABLED', false),
    'trace_transitions'          => env('DUALSTACK_TRACE_TRANSITIONS', false),
    'trusted_proxies'            => array_values(array_filter(array_map('trim', explode(',', (string) env('DUALSTACK_TRUSTED_PROXIES', ''))))),
    'max_endpoints_per_peer'     => (int) env('DUALSTACK_MAX_ENDPOINTS_PER_PEER', 2),
    'endpoint_ttl'               => (int) env('DUALSTACK_ENDPOINT_TTL', 7200),
    'inactive_peer_retention'    => (int) env('DUALSTACK_INACTIVE_PEER_RETENTION', 172800),
    'cleanup_interval'           => 60,
    'allow_private_addresses'    => env('DUALSTACK_ALLOW_PRIVATE_ADDRESSES', false),
    'require_connectivity'       => env('DUALSTACK_REQUIRE_CONNECTIVITY', false),
    'max_pending_transitions'    => (int) env('DUALSTACK_MAX_PENDING_TRANSITIONS', 100000),
    'max_cleanup_requests'       => (int) env('DUALSTACK_MAX_CLEANUP_REQUESTS', 1000),
    'connectivity_cache_entries' => (int) env('DUALSTACK_CONNECTIVITY_CACHE_ENTRIES', 100000),
    'connectivity_cache_ttl'     => (int) env('DUALSTACK_CONNECTIVITY_CACHE_TTL', 1800),
];
