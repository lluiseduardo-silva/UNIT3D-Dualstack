<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\History;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use PDOException;

final class DownloadRefund
{
    private const BATCH_SIZE = 100;

    public function run(): void
    {
        $minimum = (int) config('hitrun.seedtime');
        $full = 12 * 30 * 24 * 60 * 60 + $minimum;
        $cutoff = now()->subSeconds($minimum);
        $cursor = [0, 0];

        do {
            // Enumeration takes no locks. Recheck these candidates inside each transaction.
            $keys = $this->eligible($minimum, $full, $cutoff)
                ->where(fn ($query) => $query->where('history.user_id', '>', $cursor[0])
                    ->orWhere(fn ($query) => $query->where('history.user_id', $cursor[0])->where('history.torrent_id', '>', $cursor[1])))
                ->orderBy('history.user_id')->orderBy('history.torrent_id')->limit(self::BATCH_SIZE)
                ->get(['history.user_id', 'history.torrent_id'])
                ->map(fn ($row) => [(int) $row->user_id, (int) $row->torrent_id])->all();

            if ($keys === []) {
                return;
            }

            for ($attempt = 0; ; $attempt++) {
                try {
                    DB::transaction(fn () => $this->apply($keys, $minimum, $full, $cutoff));

                    break;
                } catch (PDOException $error) {
                    if ($attempt >= 4 || !($error->getCode() === '40001' || $error->getCode() === 40001
                        || \in_array($error->errorInfo[1] ?? null, [1205, 1213], true))) {
                        throw $error;
                    }
                    // Failed batches have rolled back. Never sleep while retaining their locks.
                    usleep(25000 * (1 << $attempt));
                }
            }
            $cursor = $keys[array_key_last($keys)];
        } while (\count($keys) === self::BATCH_SIZE);
    }

    private function eligible(int $minimum, int $full, Carbon $cutoff): Builder
    {
        return History::query()
            ->join('torrents', 'torrents.id', '=', 'history.torrent_id')
            ->join('users', 'users.id', '=', 'history.user_id')
            ->join('groups', 'groups.id', '=', 'users.group_id')
            ->where('history.active', 1)->where('history.seeder', 1)
            ->whereBetween('history.seedtime', [$minimum, $full + $minimum + 86400])
            ->where('history.created_at', '<=', $cutoff)
            ->whereColumn('torrents.user_id', '!=', 'history.user_id')
            ->when(!config('other.refundable'), fn ($query) => $query->where(
                fn ($query) => $query->where('groups.is_refundable', true)->orWhere('torrents.refundable', true)
            ));
    }

    private function apply(array $keys, int $minimum, int $full, Carbon $cutoff): void
    {
        // Same order as both announce writers: users -> (torrents) -> histories.
        // Exact keys only; no locking joins across torrents/groups. At most 100 histories.
        $userIds = array_values(array_unique(array_column($keys, 0)));
        DB::table('users')->whereIn('id', $userIds)->orderBy('id')->lockForUpdate()->get(['id']);
        $tuples = implode(',', array_fill(0, \count($keys), '(?,?)'));
        $keyBindings = array_merge(...$keys);
        DB::table('history')->whereRaw("(user_id,torrent_id) IN ({$tuples})", $keyBindings)
            ->orderBy('user_id')->orderBy('torrent_id')->lockForUpdate()->get(['user_id', 'torrent_id']);

        // First consistent read of this transaction: the locked histories are current.
        // Round the cumulative target once, as for a BIGINT assignment. Use that SAME
        // integer for both sides of the ledger; never convert bytes to PHP floats.
        $refunds = $this->eligible($minimum, $full, $cutoff)
            ->whereRaw("(history.user_id,history.torrent_id) IN ({$tuples})", $keyBindings)
            ->select(['history.user_id', 'history.torrent_id', 'history.refunded_download'])
            ->selectRaw('CAST(LEAST(1, history.seedtime / ?) * torrents.size AS DECIMAL(20,0)) AS target', [$full])
            ->get()->filter(fn ($row) => (string) $row->target !== (string) $row->refunded_download);

        if ($refunds->isEmpty()) {
            return;
        }
        $rows = $bindings = $cases = $historyBindings = $changedKeys = [];

        foreach ($refunds as $refund) {
            $rows[] = 'SELECT ? AS user_id, CAST(? AS DECIMAL(20,0)) - CAST(? AS DECIMAL(20,0)) AS delta';
            array_push($bindings, $refund->user_id, (string) $refund->target, (string) $refund->refunded_download);
            $cases[] = 'WHEN user_id = ? AND torrent_id = ? THEN CAST(? AS DECIMAL(20,0))';
            array_push($historyBindings, $refund->user_id, $refund->torrent_id, (string) $refund->target);
            array_push($changedKeys, $refund->user_id, $refund->torrent_id);
        }
        $grammar = DB::connection()->getQueryGrammar();
        $users = $grammar->wrapTable('users');
        $history = $grammar->wrapTable('history');
        $deltas = implode(' UNION ALL ', $rows);
        // Only constant rows in the derived table: no extra locks or stale balance.
        DB::update("UPDATE {$users} AS u JOIN (SELECT user_id, SUM(delta) AS delta FROM ({$deltas}) AS entries GROUP BY user_id) AS refunds ON refunds.user_id = u.id "
            .'SET u.downloaded = GREATEST(0, CAST(u.downloaded AS DECIMAL(20,0)) - refunds.delta)', $bindings);
        $changedTuples = implode(',', array_fill(0, $refunds->count(), '(?,?)'));
        DB::update(
            "UPDATE {$history} SET refunded_download = CASE ".implode(' ', $cases)
            ." ELSE refunded_download END WHERE (user_id,torrent_id) IN ({$changedTuples}) ORDER BY user_id,torrent_id",
            [...$historyBindings, ...$changedKeys]
        );
    }
}
