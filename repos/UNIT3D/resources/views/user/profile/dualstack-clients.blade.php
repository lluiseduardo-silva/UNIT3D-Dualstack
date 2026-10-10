@if (auth()->user()->is($user) || auth()->user()->group->is_modo)
    <section class="panelV2">
        <h2 class="panel__heading">{{ __('user.client-list') }}</h2>
        <div class="data-table-wrapper">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>{{ __('torrent.client') }}</th>
                        <th>{{ __('torrent.torrent') }}</th>
                        <th>{{ __('common.ip') }}</th>
                        <th>{{ __('common.port') }}</th>
                        <th>{{ __('torrent.started') }}</th>
                        <th>{{ __('torrent.last-update') }}</th>
                        <th>{{ __('torrent.size') }}</th>
                        @if (config('announce.connectable_check'))
                            <th>Connectable</th>
                        @endif
                    </tr>
                </thead>
                <tbody>
                    @forelse ($clients as $client)
                        <tr>
                            <td>{{ $client->agent }}</td>
                            <td>
                                <a href="{{ route('peers', ['id' => $client->torrent_id]) }}">{{ $client->torrent_name }}</a>
                            </td>
                            <td>
                                @if (auth()->user()->group->is_modo)
                                    @foreach ($client->endpoints as $endpoint)
                                        <div>
                                            IPv{{ $endpoint->family }}:
                                            <a href="{{ route('staff.peers.index', ['ip' => $endpoint->ip_address, 'groupBy' => 'user_ip']) }}">{{ $endpoint->ip_address }}</a>
                                            @if (! $endpoint->current)
                                                <span class="text-muted">{{ __('dualstack.endpoint-expired') }}</span>
                                            @endif
                                        </div>
                                    @endforeach
                                @else
                                    <x-peer.endpoints :peer="$client" field="ip" :can-view="true" />
                                @endif
                            </td>
                            <td><x-peer.endpoints :peer="$client" field="port" :can-view="true" /></td>
                            <td>
                                <time datetime="{{ $client->created_at }}" title="{{ $client->created_at }}">{{ $client->created_at?->diffForHumans() ?? 'N/A' }}</time>
                            </td>
                            <td>
                                <time datetime="{{ $client->updated_at }}" title="{{ $client->updated_at }}">{{ $client->updated_at?->diffForHumans() ?? 'N/A' }}</time>
                            </td>
                            <td>{{ App\Helpers\StringHelper::formatBytes($client->size) }}</td>
                            @if (config('announce.connectable_check'))
                                <td><x-peer.endpoints :peer="$client" field="connectable" /></td>
                            @endif
                        </tr>
                    @empty
                        <tr><td colspan="{{ 7 + (int) config('announce.connectable_check') }}">No clients</td></tr>
                    @endforelse
                </tbody>
                <tfoot>
                    <tr>
                        <td colspan="{{ 7 + (int) config('announce.connectable_check') }}">
                            If you don't recognize a torrent client or IP address in the list, please
                            <a href="{{ route('tickets.index') }}">create a helpdesk ticket</a>
                        </td>
                    </tr>
                </tfoot>
            </table>
        </div>
        {{ $clients->links() }}
    </section>
@endif
