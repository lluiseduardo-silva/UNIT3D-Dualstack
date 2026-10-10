<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use App\DTO\AnnounceQueryDTO;
use App\Exceptions\TrackerException;
use App\Models\FeaturedTorrent;
use App\Models\FreeleechToken;
use App\Models\Group;
use App\Models\PersonalFreeleech;
use App\Models\Torrent;
use App\Models\User;
use Illuminate\Http\Request;

final class StandaloneAnnounce
{
    public function handle(Request $request, AnnounceQueryDTO $queries, User $user, Group $group, Torrent $torrent): string
    {
        if (config('announce.external_tracker.is_enabled')) {
            throw new TrackerException(100);
        }
        $policy = Policy::configured();

        if (config('announce.slots_system.enabled')) {
            $policy['download_slots'] = $group->download_slots;
        }
        $personal = cache()->rememberForever('personal_freeleech:'.$user->id, fn () => PersonalFreeleech::where('user_id', $user->id)->exists());
        $token = cache()->rememberForever('freeleech_token:'.$user->id.':'.$torrent->id, fn () => FreeleechToken::where('user_id', $user->id)->where('torrent_id', $torrent->id)->exists());
        $featured = \in_array($torrent->id, cache()->rememberForever('featured-torrent-ids', fn () => FeaturedTorrent::pluck('torrent_id')->all()), true);
        $free = $personal || $token || $featured || $user->is_donor || $group->is_freeleech || config('other.freeleech');
        $double = $torrent->doubleup || $group->is_double_upload || $featured || config('other.doubleup');
        $ip = EndpointAddress::observed($request->getClientIp(), $policy['allow_private_addresses']);
        $journal = new TransitionJournal(TrackerLease::current());
        $result = $journal->publish(['user_id' => $user->id, 'torrent_id' => $torrent->id, 'peer_id' => bin2hex($queries->getPeerId())], [
            'ip'         => $ip->text(), 'port' => $queries->port, 'event' => $queries->event, 'agent' => $queries->getAgent(),
            'uploaded'   => Counter::of($request->query->getString('uploaded')),
            'downloaded' => Counter::of($request->query->getString('downloaded')),
            'left'       => Counter::of($request->query->getString('left')), 'visible' => true,
        ], $policy, ['upload_percent' => $double ? 200 : 100, 'download_percent' => $free ? 0 : 100 - min(100, (int) $torrent->free),
            'immune'                  => $user->is_donor || $group->is_immune]);

        if ($result['outcome'] === 'rejected') {
            throw match ($result['reason']) {
                'removed'    => new TrackerException(100),
                'interval'   => new TrackerException(162, [':elapsed' => 'less than the minimum']),
                'peer_limit' => new TrackerException(138, [':limit' => $policy['max_peers']]),
                default      => new TrackerException(131, [':attribute' => 'endpoint', ':reason' => 'IP family limit reached']),
            };
        }
        $warning = ($result['peer']['visible'] ?? true) ? null : (new TrackerException(164, [':max' => $group->download_slots]))->getMessage();

        return (new AnnounceResponse())->build($torrent->id, $user->id, $queries->left === 0, $queries->numwant, $queries->event === 'stopped', $warning);
    }
}
