@props(['torrent', 'kind', 'legacy' => null])
<span title="{{ __('dualstack.peer-count-' . \App\Services\Dualstack\PeerCountDisplay::mode(auth()->user())) }}">{{ \App\Services\Dualstack\PeerCountDisplay::count($torrent, $kind, auth()->user(), $legacy) }}</span>
