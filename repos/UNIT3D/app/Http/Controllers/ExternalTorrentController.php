<?php

declare(strict_types=1);

/**
 * NOTICE OF LICENSE.
 *
 * UNIT3D Community Edition is open-sourced software licensed under the GNU Affero General Public License v3.0
 * The details is bundled with this project in the file LICENSE.txt.
 *
 * @project    UNIT3D Community Edition
 *
 * @author     Roardom <roardom@protonmail.com>
 * @license    https://www.gnu.org/licenses/agpl-3.0.en.html/ GNU Affero General Public License v3.0
 */

namespace App\Http\Controllers;

use App\Models\Torrent;
use App\Models\User;
use App\Services\Unit3dAnnounce;

class ExternalTorrentController extends Controller
{
    /**
     * Display the torrent stored on the external tracker.
     */
    public function show(int $id): \Illuminate\Contracts\View\Factory|\Illuminate\View\View
    {
        $externalTorrent = Unit3dAnnounce::getTorrent($id);
        $peerUsers = User::query()->with(['group', 'privacy'])
            ->whereIn('id', \is_array($externalTorrent) ? array_column($externalTorrent['peers'] ?? [], 'user_id') : [])
            ->get()->keyBy('id');

        return view('torrent.external-tracker', [
            'id'              => $id,
            'torrent'         => Torrent::find($id),
            'externalTorrent' => $externalTorrent,
            'peerUsers'       => $peerUsers,
        ]);
    }
}
