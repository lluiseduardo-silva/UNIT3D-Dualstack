<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Services\Dualstack\PeerCountPreference;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;

class AutoResolvePeerCountMode extends Command
{
    protected $signature = 'auto:resolve_peer_count_mode';

    protected $description = 'Resolve a familia exibida para usuarios que escolheram auto.';

    public function handle(PeerCountPreference $preferences): int
    {
        if (!config('dualstack.enabled')) {
            return self::SUCCESS;
        }

        DB::table('users')->select('id')->where('peer_count_mode', 'auto')
            ->orderBy('id')->chunkById(500, function ($users) use ($preferences): void {
                $preferences->resolve($users->pluck('id')->all());
            });

        return self::SUCCESS;
    }
}
