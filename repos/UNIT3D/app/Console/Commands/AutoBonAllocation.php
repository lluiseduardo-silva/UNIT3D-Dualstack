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

use App\Helpers\ByteUnits;
use App\Models\BonEarning;
use App\Services\Dualstack\BonPeers;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;

/**
 * @see \Tests\Unit\Console\Commands\AutoBonAllocationTest
 */
class AutoBonAllocation extends Command
{
    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'auto:bon_allocation';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'Allocates bonus points to users based on peer activity.';

    /**
     * Execute the console command.
     */
    public function handle(ByteUnits $byteUnits): void
    {
        $now = now();

        $bonEarnings = BonEarning::with('conditions')->orderBy('position')->get();

        $earningsQuery = str_repeat('(', $bonEarnings->count()).'0';

        foreach ($bonEarnings as $bonEarning) {
            // Raw bindings are fine since all database values are either enums or numeric
            $conditionQuery = '1=1';

            foreach ($bonEarning->conditions as $condition) {
                $conditionQuery .= ' AND '.match ($condition->operand1) {
                    '1'                => '1',
                    'age'              => 'TIMESTAMPDIFF(SECOND, torrents.created_at, NOW())',
                    'size'             => 'torrents.size',
                    'seeders'          => 'torrents.seeders',
                    'leechers'         => 'torrents.leechers',
                    'times_completed'  => 'torrents.times_completed',
                    'internal'         => 'torrents.internal',
                    'personal_release' => 'torrents.personal_release',
                    'type_id'          => 'torrents.type_id',
                    'seedtime'         => 'history.seedtime',
                    'connectable'      => 'MAX(peers.connectable)',
                }.' '.$condition->operator.' '.$condition->operand2;
            }

            $variable = match ($bonEarning->variable) {
                '1'                => '1',
                'age'              => 'TIMESTAMPDIFF(SECOND, torrents.created_at, NOW())',
                'size'             => 'torrents.size',
                'seeders'          => 'torrents.seeders',
                'leechers'         => 'torrents.leechers',
                'times_completed'  => 'torrents.times_completed',
                'internal'         => 'torrents.internal',
                'personal_release' => 'torrents.personal_release',
                'seedtime'         => 'history.seedtime',
                'connectable'      => 'MAX(peers.connectable)',
            };

            $earningsQuery .= match ($bonEarning->operation) {
                'append'   => " + CASE WHEN ({$conditionQuery}) THEN {$variable} * {$bonEarning->multiplier} ELSE 0 END)",
                'multiply' => " * CASE WHEN ({$conditionQuery}) THEN {$variable} * {$bonEarning->multiplier} ELSE 1 END)",
            };
        }

        DB::transaction(function () use ($earningsQuery): void {
            // A idade dos torrents usa um unico instante, inclusive entre lotes.
            $evaluatedAt = DB::selectOne('SELECT CURRENT_TIMESTAMP AS evaluated_at')->evaluated_at;
            $bindings = array_fill(0, substr_count($earningsQuery, 'NOW()'), $evaluatedAt);
            $earningsQuery = str_replace('NOW()', '?', $earningsQuery);
            // SELECT comum: o calculo nao toma locks nas tabelas do swarm.
            DB::query()->fromSub(
                BonPeers::query()
                    ->select([
                        'peers.user_id',
                        'peers.torrent_id',
                    ])
                    ->selectRaw("({$earningsQuery}) AS hourly_earnings", $bindings)
                    ->join('history', fn ($join) => $join->on('history.torrent_id', '=', 'peers.torrent_id')->on('history.user_id', '=', 'peers.user_id'))
                    ->join('torrents', 'peers.torrent_id', '=', 'torrents.id')
                    ->where('peers.seeder', '=', true)
                    ->where('peers.active', '=', true)
                    ->where('peers.created_at', '<', now()->subMinutes(30))
                    ->groupBy(['peers.user_id', 'peers.torrent_id']),
                'earnings_per_user_per_torrent',
            )
                ->select(['user_id', DB::raw('SUM(hourly_earnings) AS hourly_earnings_sum')])
                ->groupBy('user_id')
                ->chunkById(500, function ($earnings): void {
                    $cases = $bindings = $ids = [];

                    foreach ($earnings as $earning) {
                        $cases[] = 'WHEN ? THEN CAST(? AS DECIMAL(65,30))';
                        $bindings[] = $earning->user_id;
                        $bindings[] = $earning->hourly_earnings_sum;
                        $ids[] = $earning->user_id;
                    }

                    // Somente users, na mesma ordem dos gravadores PHP e Rust.
                    // O incremento SQL preserva o saldo corrente; nenhum float em PHP.
                    $users = DB::connection()->getQueryGrammar()->wrapTable('users');
                    $placeholders = implode(',', array_fill(0, \count($ids), '?'));
                    DB::update(
                        "UPDATE {$users} SET seedbonus = seedbonus + CASE id ".implode(' ', $cases)
                        ." ELSE 0 END WHERE id IN ({$placeholders}) ORDER BY id",
                        [...$bindings, ...$ids],
                    );
                }, 'user_id');
        }, 25);
        $this->comment('Automated BON allocation command complete in '.(int) now()->diffInMilliseconds($now, true).' ms');
    }
}
