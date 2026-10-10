<?php

declare(strict_types=1);

use App\Services\DownloadRefund;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Database\Events\QueryExecuted;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

beforeEach(function (): void {
    if (getenv('DUALSTACK_CONSUMER_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL real e banco isolado de dualstack.');
    }
    expect(DB::getDriverName())->toBe('mysql')->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    Carbon::setTestNow('2026-10-08 12:00:00');
    config(['other.refundable' => true, 'hitrun.seedtime' => 3600]);
    DB::table('peers')->delete();
    DB::table('history')->delete();
    $this->savedUsers = DB::table('users')->whereIn('id', [12001, 12002])->get(['id', 'downloaded', 'group_id'])->all();
    $this->savedTorrent = (array) DB::table('torrents')->find(12001);
    $group = DB::table('groups')->orderBy('id')->value('id');
    DB::table('users')->whereIn('id', [12001, 12002])->update(['downloaded' => 1000000, 'group_id' => $group]);
    DB::table('torrents')->where('id', 12001)->update(['size' => 1000, 'user_id' => 12003, 'refundable' => true]);
    $this->full = 12 * 30 * 24 * 60 * 60 + 3600;
});

afterEach(function (): void {
    Carbon::setTestNow();

    if (!isset($this->savedUsers)) {
        return;
    }
    DB::table('history')->delete();
    DB::table('torrents')->whereBetween('id', [16000, 16200])->delete();
    DB::table('torrents')->where('id', 12001)->update($this->savedTorrent);

    foreach ($this->savedUsers as $user) {
        DB::table('users')->where('id', $user->id)->update((array) $user);
    }
});

function refundHistory(int $torrent, int $seedtime, int $user = 12001): void
{
    DB::table('history')->insert(['user_id' => $user, 'torrent_id' => $torrent, 'agent' => 'refund-test',
        'client_uploaded'                   => 0, 'client_downloaded' => 1000, 'active' => true, 'seeder' => true, 'immune' => false,
        'seedtime'                          => $seedtime, 'created_at' => now()->subDays(2), 'updated_at' => now()->subHour()]);
}

it('usa os mesmos bytes inteiros nos dois lados e preserva timestamps', function (int $size, int $expected): void {
    DB::table('torrents')->where('id', 12001)->update(['size' => $size]);
    refundHistory(12001, intdiv($this->full, 2));
    $timestamp = DB::table('history')->value('updated_at');
    app(DownloadRefund::class)->run();
    expect((string) DB::table('history')->value('refunded_download'))->toBe((string) $expected)
        ->and((string) DB::table('users')->where('id', 12001)->value('downloaded'))->toBe((string) max(0, 1000000 - $expected))
        ->and(DB::table('history')->value('updated_at'))->toBe($timestamp);
    app(DownloadRefund::class)->run();
    expect((string) DB::table('users')->where('id', 12001)->value('downloaded'))->toBe((string) max(0, 1000000 - $expected));
})->with([[1, 1], [3, 2], [5, 3], [1000, 500], [9007199254740992, 4503599627370496]]);

it('soma deltas de usuarios separados e preserva correcao negativa da referencia', function (): void {
    refundHistory(12001, $this->full);
    refundHistory(12001, $this->full, 12002);
    DB::table('history')->where('user_id', 12001)->update(['refunded_download' => 1500]);
    app(DownloadRefund::class)->run();
    expect((int) DB::table('users')->where('id', 12001)->value('downloaded'))->toBe(1000500)
        ->and((int) DB::table('users')->where('id', 12002)->value('downloaded'))->toBe(999000)
        ->and((int) DB::table('history')->sum('refunded_download'))->toBe(2000);
});

it('preserva filtros de elegibilidade', function (string $filter): void {
    refundHistory(12001, $this->full);
    match ($filter) {
        'inactive' => DB::table('history')->update(['active' => false]),
        'leecher'  => DB::table('history')->update(['seeder' => false]),
        'young'    => DB::table('history')->update(['created_at' => now()]),
        'minimum'  => DB::table('history')->update(['seedtime' => 3599]),
        'maximum'  => DB::table('history')->update(['seedtime' => $this->full + 3600 + 86401]),
        'deleted'  => DB::table('history')->update(['deleted_at' => now()]),
        'uploader' => DB::table('torrents')->where('id', 12001)->update(['user_id' => 12001]),
    };
    app(DownloadRefund::class)->run();
    expect((int) DB::table('history')->sum('refunded_download'))->toBe(0)
        ->and((int) DB::table('users')->where('id', 12001)->value('downloaded'))->toBe(1000000);
})->with(['inactive', 'leecher', 'young', 'minimum', 'maximum', 'deleted', 'uploader']);

it('respeita configuracao e permissao de reembolso do grupo ou torrent', function (): void {
    refundHistory(12001, $this->full);
    config(['other.refundable' => false]);
    $group = DB::table('users')->where('id', 12001)->value('group_id');
    $old = DB::table('groups')->where('id', $group)->value('is_refundable');

    try {
        DB::table('groups')->where('id', $group)->update(['is_refundable' => false]);
        DB::table('torrents')->where('id', 12001)->update(['refundable' => false]);
        app(DownloadRefund::class)->run();
        expect((int) DB::table('history')->value('refunded_download'))->toBe(0);
        DB::table('groups')->where('id', $group)->update(['is_refundable' => true]);
        app(DownloadRefund::class)->run();
        expect((int) DB::table('history')->value('refunded_download'))->toBe(1000);
    } finally {
        DB::table('groups')->where('id', $group)->update(['is_refundable' => $old]);
    }
});

it('limita lotes mesmo para um usuario e retoma falha entre saldo e historico', function (string $failure): void {
    $torrent = $this->savedTorrent;

    foreach (range(16000, 16200) as $id) {
        DB::table('torrents')->insert(array_replace($torrent, ['id' => $id, 'info_hash' => hex2bin(sha1('refund-'.$id)), 'size' => 1000, 'user_id' => 12003]));
        refundHistory($id, $this->full);
    }
    $writes = 0;
    $listening = true;
    DB::listen(function (QueryExecuted $query) use (&$writes, &$listening, $failure): void {
        if (!$listening || !str_starts_with($query->sql, 'UPDATE ') || !str_contains($query->sql, 'AS refunds ON')) {
            return;
        }
        $writes++;
        expect(\count($query->bindings))->toBeLessThanOrEqual(300);

        if ($writes === 2 && $failure !== 'none') {
            if ($failure === 'retry') {
                throw new PDOException('Deadlock found when trying to get lock; try restarting transaction', 40001);
            }

            throw new RuntimeException('REFUND_FAILURE_AFTER_BALANCE');
        }
    });

    try {
        if ($failure === 'rollback') {
            expect(fn () => app(DownloadRefund::class)->run())->toThrow(RuntimeException::class, 'REFUND_FAILURE_AFTER_BALANCE');
            expect((int) DB::table('history')->sum('refunded_download'))->toBe(100000)
                ->and((int) DB::table('users')->where('id', 12001)->value('downloaded'))->toBe(900000);
        }
        app(DownloadRefund::class)->run();
        expect((int) DB::table('history')->sum('refunded_download'))->toBe(201000)
            ->and((int) DB::table('users')->where('id', 12001)->value('downloaded'))->toBe(799000)
            ->and(DB::transactionLevel())->toBe(0)->and($writes)->toBe($failure === 'none' ? 3 : 4);
        app(DownloadRefund::class)->run();
        expect((int) DB::table('users')->where('id', 12001)->value('downloaded'))->toBe(799000);
    } finally {
        $listening = false;
    }
})->with(['none', 'rollback', 'retry']);

it('esgota o retry sem confirmar apenas o saldo', function (): void {
    refundHistory(12001, $this->full);
    $writes = 0;
    $listening = true;
    DB::listen(function (QueryExecuted $query) use (&$writes, &$listening): void {
        if ($listening && str_starts_with($query->sql, 'UPDATE ') && str_contains($query->sql, 'AS refunds ON')) {
            $writes++;

            throw new PDOException('Deadlock found when trying to get lock; try restarting transaction', 40001);
        }
    });

    try {
        expect(fn () => app(DownloadRefund::class)->run())->toThrow(PDOException::class);
        expect($writes)->toBe(5)->and(DB::transactionLevel())->toBe(0)
            ->and((int) DB::table('history')->value('refunded_download'))->toBe(0)
            ->and((int) DB::table('users')->where('id', 12001)->value('downloaded'))->toBe(1000000);
    } finally {
        $listening = false;
    }
});
