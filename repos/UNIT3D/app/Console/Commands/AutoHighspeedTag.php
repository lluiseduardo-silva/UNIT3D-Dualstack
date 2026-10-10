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
 * @author     HDVinnie <hdinnovations@protonmail.com>
 * @license    https://www.gnu.org/licenses/agpl-3.0.en.html/ GNU Affero General Public License v3.0
 */

namespace App\Console\Commands;

use App\Models\Peer;
use App\Models\Scopes\ApprovedScope;
use App\Models\Seedbox;
use App\Models\Torrent;
use Exception;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;
use Throwable;

class AutoHighspeedTag extends Command
{
    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'auto:highspeed_tag';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'Updates torrents highspeed tag based on registered seedboxes.';

    /**
     * Execute the console command.
     *
     * @throws Exception|Throwable If there is an error during the execution of the command.
     */
    final public function handle(): void
    {
        $seedboxIps = Seedbox::all()
            ->pluck('ip')
            ->filter(fn ($ip) => filter_var($ip, FILTER_VALIDATE_IP) !== false)
            ->map(fn ($ip) => inet_pton($ip));

        $seeders = Peer::where('seeder', true)->where('active', true)
            ->select('torrent_id')->distinct();

        if (config('dualstack.enabled')) {
            $seeders->whereExists(fn ($query) => $query->selectRaw('1')->from('peer_ips as endpoint')
                ->whereColumn('endpoint.user_id', 'peers.user_id')
                ->whereColumn('endpoint.torrent_id', 'peers.torrent_id')
                ->whereColumn('endpoint.peer_id', 'peers.peer_id')
                ->where('endpoint.last_announced_at', '>', now()->subSeconds((int) config('dualstack.endpoint_ttl')))
                ->whereIn('endpoint.ip', $seedboxIps));
        } else {
            $seeders->whereIn('ip', $seedboxIps);
        }

        DB::transaction(function () use ($seeders): void {
            // Leitura consistente sem locks nos peers; escrita somente em torrents.
            Torrent::withoutGlobalScope(ApprovedScope::class)
                ->leftJoinSub($seeders, 'highspeed_torrents', fn ($join) => $join->on('torrents.id', '=', 'highspeed_torrents.torrent_id'))
                ->select('torrents.id')->selectRaw('highspeed_torrents.torrent_id IS NOT NULL AS highspeed')
                ->chunkById(500, function ($torrents): void {
                    $cases = $bindings = $ids = [];

                    foreach ($torrents as $torrent) {
                        $cases[] = 'WHEN ? THEN ?';
                        $bindings[] = $torrent->id;
                        $bindings[] = (int) $torrent->highspeed;
                        $ids[] = $torrent->id;
                    }
                    $table = DB::connection()->getQueryGrammar()->wrapTable('torrents');
                    $placeholders = implode(',', array_fill(0, \count($ids), '?'));
                    DB::update("UPDATE {$table} SET highspeed = CASE id ".implode(' ', $cases)
                        ." ELSE highspeed END WHERE id IN ({$placeholders}) ORDER BY id", [...$bindings, ...$ids]);
                }, 'torrents.id', 'id');
        }, 5);

        $this->comment('Automated high speed torrents command complete');
    }
}
