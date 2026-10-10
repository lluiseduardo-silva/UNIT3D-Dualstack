@props(['peer', 'field', 'canView' => false])
@if (! $canView && $field !== 'connectable')
    ---
@else
    @forelse ($peer->endpoints as $endpoint)
        <div>
            IPv{{ $endpoint->family }}:
            @if ($field === 'ip')
                {{ $endpoint->ip_address }}
            @elseif ($field === 'port')
                {{ $endpoint->port }}
            @elseif ($field === 'connectable' && $endpoint->current)
                {{ $endpoint->connectable === null ? __('common.unknown') : ($endpoint->connectable ? __('common.yes') : __('common.no')) }}
            @endif
            @if (! $endpoint->current)
                <span class="text-muted">{{ __('dualstack.endpoint-expired') }}</span>
            @endif
        </div>
    @empty
        ---
    @endforelse
@endif
