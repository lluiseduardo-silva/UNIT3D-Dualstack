@if ($canView)
    <td>
        @if ($dualstack)
            @forelse ($peer['endpoints'] as $endpoint)
                <div>IPv{{ $endpoint['family'] }}: {{ $endpoint['ip_address'] }}</div>
            @empty
                ---
            @endforelse
        @else
            {{ $peer['ip_address'] }}
        @endif
    </td>
    <td>
        @if ($dualstack)
            @foreach ($peer['endpoints'] as $endpoint)
                <div>IPv{{ $endpoint['family'] }}: {{ $endpoint['port'] }}</div>
            @endforeach
        @else
            {{ $peer['port'] }}
        @endif
    </td>
@else
    <td>---</td>
    <td>---</td>
@endif
