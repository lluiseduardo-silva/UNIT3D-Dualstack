<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Services\Dualstack\EndpointAddress;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;
use InvalidArgumentException;

final class DualstackBackfill extends Command
{
    protected $signature = 'dualstack:backfill {--offline : Confirma que announces, workers e escritores de peers foram interrompidos} {--batch=1000}';

    protected $description = 'Preenche endpoints a partir da projecao legada, sem sobrescrever endpoints existentes';

    public function handle(): int
    {
        if (!$this->option('offline') || config('dualstack.enabled')) {
            $this->error('Interrompa os escritores, desative dualstack e use --offline antes do backfill.');

            return self::FAILURE;
        }
        $batch = filter_var($this->option('batch'), FILTER_VALIDATE_INT, ['options' => ['min_range' => 1, 'max_range' => 2000]]);

        if ($batch === false) {
            $this->error('O lote deve conter entre 1 e 2000 peers.');

            return self::FAILURE;
        }
        $cursor = null;
        $read = $invalid = 0;

        do {
            $query = DB::table('peers')->where('state_version', 0)->orderBy('user_id')->orderBy('torrent_id')->orderBy('peer_id')->limit($batch);

            if ($cursor !== null) {
                $query->whereRaw('(user_id, torrent_id, peer_id) > (?, ?, ?)', $cursor);
            }
            $peers = $query->get();
            $rows = [];

            foreach ($peers as $peer) {
                $cursor = [$peer->user_id, $peer->torrent_id, $peer->peer_id];
                $read++;
                $text = @inet_ntop($peer->ip);

                try {
                    $ip = EndpointAddress::observed($text === false ? '' : $text, (bool) config('dualstack.allow_private_addresses'));
                } catch (InvalidArgumentException) {
                    $invalid++;

                    continue;
                }
                $lastAnnounced = $peer->updated_at ?? $peer->created_at ?? '1970-01-01 00:00:01';
                $rows[] = [
                    'user_id' => $peer->user_id, 'torrent_id' => $peer->torrent_id, 'peer_id' => $peer->peer_id,
                    'family'  => $ip->family, 'ip' => $ip->binary, 'port' => $peer->port,
                    // false legado tambem representava "nao verificado".
                    'connectable'       => $peer->connectable ? true : null,
                    'last_announced_at' => $lastAnnounced, 'connectivity_checked_at' => null,
                    'revision'          => 1, 'created_at' => $peer->created_at, 'updated_at' => $peer->updated_at,
                ];
            }

            if ($rows !== []) {
                // family faz parte da PK: reexecutar nao altera IP, revisao ou timestamps.
                DB::transaction(fn () => DB::table('peer_ips')->upsert($rows, ['user_id', 'torrent_id', 'peer_id', 'family'], ['family']), 5);
            }
        } while ($peers->count() === $batch);

        $cutoff = now()->subSeconds((int) config('dualstack.endpoint_ttl'))->toDateTimeString();
        $connectivity = config('dualstack.require_connectivity') ? ' AND e.connectable = 1' : '';
        // Agregar a identidade antes de contar as familias; nunca multiplicar peers pelo join.
        DB::update("UPDATE torrents t LEFT JOIN (
            SELECT p.torrent_id,
                SUM(p.seeder AND EXISTS (SELECT 1 FROM peer_ips e WHERE e.user_id=p.user_id AND e.torrent_id=p.torrent_id AND e.peer_id=p.peer_id AND e.family=4 AND e.last_announced_at > ? {$connectivity})) AS seeders_ipv4,
                SUM(p.seeder AND EXISTS (SELECT 1 FROM peer_ips e WHERE e.user_id=p.user_id AND e.torrent_id=p.torrent_id AND e.peer_id=p.peer_id AND e.family=6 AND e.last_announced_at > ? {$connectivity})) AS seeders_ipv6,
                SUM(NOT p.seeder AND EXISTS (SELECT 1 FROM peer_ips e WHERE e.user_id=p.user_id AND e.torrent_id=p.torrent_id AND e.peer_id=p.peer_id AND e.family=4 AND e.last_announced_at > ? {$connectivity})) AS leechers_ipv4,
                SUM(NOT p.seeder AND EXISTS (SELECT 1 FROM peer_ips e WHERE e.user_id=p.user_id AND e.torrent_id=p.torrent_id AND e.peer_id=p.peer_id AND e.family=6 AND e.last_announced_at > ? {$connectivity})) AS leechers_ipv6
            FROM peers p WHERE p.active = 1 AND p.visible = 1 GROUP BY p.torrent_id
        ) counts ON counts.torrent_id=t.id SET
            t.seeders_ipv4=COALESCE(counts.seeders_ipv4,0), t.seeders_ipv6=COALESCE(counts.seeders_ipv6,0),
            t.leechers_ipv4=COALESCE(counts.leechers_ipv4,0), t.leechers_ipv6=COALESCE(counts.leechers_ipv6,0)", [$cutoff, $cutoff, $cutoff, $cutoff]);

        $this->info("Peers lidos: {$read}; enderecos invalidos/nao permitidos: {$invalid}. Contadores legados preservados.");

        return $invalid === 0 ? self::SUCCESS : self::FAILURE;
    }
}
