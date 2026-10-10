<?php

declare(strict_types=1);

use Illuminate\Contracts\Console\Kernel;
use Illuminate\Database\Events\QueryExecuted;
use Illuminate\Support\Facades\DB;

beforeAll(function (): void {
    $app = require __DIR__.'/../../bootstrap/app.php';
    $app->make(Kernel::class)->bootstrap();
});

beforeEach(function (): void {
    if (getenv('DUALSTACK_BON_ALLOCATION_TESTS') !== '1') {
        $this->markTestSkipped('Exige MySQL real e fixtures exclusivas de alocacao BON.');
    }
    expect(DB::getDriverName())->toBe('mysql')->and(DB::getDatabaseName())->toBe('unit3d_dualstack_journal_test');
    expect(DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists())->toBeFalse();
    expect(DB::table('users')->whereBetween('id', [15001, 15501])->exists())->toBeFalse();
    $this->savedRules = DB::table('bon_earnings')->get()->map(fn ($row) => (array) $row)->all();
    $this->savedConditions = DB::table('bon_earning_conditions')->get()->map(fn ($row) => (array) $row)->all();
    $this->savedBalances = DB::table('users')->pluck('seedbonus', 'id')->all();
    $this->dispatcher = DB::connection()->getEventDispatcher();
    DB::connection()->setEventDispatcher(clone $this->dispatcher);
    config(['dualstack.enabled' => true, 'dualstack.endpoint_ttl' => 7200]);
    DB::table('bon_earnings')->delete();
    $this->rule = DB::table('bon_earnings')->insertGetId([
        'position' => 1, 'variable' => '1', 'multiplier' => '10', 'operation' => 'append',
        'name'     => 'Alocacao isolada', 'description' => 'Fixture de transacao e lotes',
    ]);
});

afterEach(function (): void {
    if (!isset($this->dispatcher)) {
        return;
    }
    DB::connection()->setEventDispatcher($this->dispatcher);
    DB::disableQueryLog();
    DB::transaction(function (): void {
        DB::table('peers')->whereBetween('user_id', [15001, 15501])->delete();
        DB::table('history')->whereBetween('user_id', [15001, 15501])->delete();
        DB::table('users')->whereBetween('id', [15001, 15501])->delete();
        DB::table('bon_earnings')->delete();

        if ($this->savedRules !== []) {
            DB::table('bon_earnings')->insert($this->savedRules);
        }

        if ($this->savedConditions !== []) {
            DB::table('bon_earning_conditions')->insert($this->savedConditions);
        }

        foreach ($this->savedBalances as $user => $balance) {
            DB::table('users')->where('id', $user)->update(['seedbonus' => $balance]);
        }
    });
});

function bonAllocationUsers(int $count, string $balance = '1000000000.00'): void
{
    $template = (array) DB::table('users')->find(12001);
    $users = $peers = $endpoints = $histories = [];

    foreach (range(15001, 15000 + $count) as $id) {
        $users[] = array_replace($template, [
            'id'        => $id, 'username' => 'bon-lab-'.$id, 'email' => 'bon-'.$id.'@example.invalid',
            'passkey'   => md5('bon-lab-passkey-'.$id), 'rsskey' => md5('bon-lab-rss-'.$id), 'api_token' => null,
            'seedbonus' => $balance, 'deleted_at' => null, 'tracker_removal_state' => 0,
        ]);
        $identity = ['user_id' => $id, 'torrent_id' => 12001, 'peer_id' => str_repeat('A', 20)];
        $peers[] = $identity + [
            'ip'       => inet_pton('192.0.2.30'), 'port' => 6881, 'agent' => 'bon-allocation-test',
            'uploaded' => 1000, 'downloaded' => 0, 'left' => 0, 'seeder' => true, 'active' => true,
            'visible'  => true, 'connectable' => true, 'created_at' => now()->subHour(), 'updated_at' => now(),
        ];
        $endpoints[] = $identity + [
            'family'      => 6, 'ip' => inet_pton('2001:db8::30'), 'port' => 6881,
            'connectable' => true, 'last_announced_at' => now(), 'revision' => 1, 'created_at' => now(), 'updated_at' => now(),
        ];
        $histories[] = [
            'user_id'         => $id, 'torrent_id' => 12001, 'agent' => 'bon-allocation-test',
            'client_uploaded' => 1000, 'client_downloaded' => 0, 'seeder' => true, 'active' => true,
            'immune'          => false, 'seedtime' => 3600, 'created_at' => now()->subHour(), 'updated_at' => now(),
        ];
    }
    DB::transaction(function () use ($users, $peers, $endpoints, $histories): void {
        foreach (array_chunk($users, 100) as $chunk) {
            DB::table('users')->insert($chunk);
        }
        DB::table('peers')->insert($peers);
        DB::table('peer_ips')->insert($endpoints);
        DB::table('history')->insert($histories);
    });
}

it('mantem atomicidade entre lotes e no retry integral', function (string $failure): void {
    bonAllocationUsers(501);
    $writes = 0;
    DB::listen(function (QueryExecuted $query) use (&$writes, $failure): void {
        if (!str_starts_with($query->sql, 'UPDATE ') || !str_contains($query->sql, 'seedbonus + CASE id')) {
            return;
        }
        $writes++;

        if ($writes === 2 && $failure !== 'none') {
            if ($failure === 'retry') {
                // Falha injetada apos SQL real; o retry deve reverter ambos os lotes.
                throw new PDOException('Deadlock found when trying to get lock; try restarting transaction', 40001);
            }

            throw new RuntimeException('BON_TEST_AFTER_SECOND_BATCH');
        }
    });

    if ($failure === 'rollback') {
        expect(fn () => app(Kernel::class)->call('auto:bon_allocation'))->toThrow(RuntimeException::class, 'BON_TEST_AFTER_SECOND_BATCH');
    } else {
        expect(app(Kernel::class)->call('auto:bon_allocation'))->toBe(0);
    }
    $balance = $failure === 'rollback' ? '1000000000.00' : '1000000010.00';
    expect(DB::table('users')->whereBetween('id', [15001, 15501])->where('seedbonus', $balance)->count())->toBe(501)
        ->and($writes)->toBe($failure === 'retry' ? 4 : 2)
        ->and(DB::transactionLevel())->toBe(0);
})->with(['none', 'rollback', 'retry']);

it('preserva decimal ate o arredondamento final do saldo', function (string $multiplier, string $expected): void {
    bonAllocationUsers(1);
    DB::table('bon_earnings')->where('id', $this->rule)->update(['multiplier' => $multiplier]);
    DB::table('bon_earnings')->insert([
        'position' => 2, 'variable' => '1', 'multiplier' => '1.000000000000001', 'operation' => 'multiply',
        'name'     => 'Precisao', 'description' => 'Fixture decimal',
    ]);
    $updatedAt = DB::table('users')->where('id', 15001)->value('updated_at');
    expect(app(Kernel::class)->call('auto:bon_allocation'))->toBe(0);
    expect(DB::table('users')->where('id', 15001)->value('seedbonus'))->toBe($expected)
        ->and(DB::table('users')->where('id', 15001)->value('updated_at'))->toBe($updatedAt);
})->with([
    ['0.004999999999999', '1000000000.00'],
    ['0.005000000000000', '1000000000.01'],
    ['0.014999999999999', '1000000000.01'],
]);

it('fixa a idade do torrent durante todos os lotes da mesma alocacao', function (): void {
    bonAllocationUsers(501);
    $createdAt = DB::table('torrents')->where('id', 12001)->value('created_at');
    $at = (int) DB::selectOne('SELECT UNIX_TIMESTAMP() AS value')->value;

    try {
        DB::statement('SET timestamp = '.$at);
        DB::table('torrents')->where('id', 12001)->update(['created_at' => gmdate('Y-m-d H:i:s', $at - 3600)]);
        DB::table('bon_earnings')->where('id', $this->rule)->update(['variable' => 'age', 'multiplier' => '0.01']);
        $advanced = false;
        DB::listen(function (QueryExecuted $query) use (&$advanced, $at): void {
            if (!$advanced && str_starts_with($query->sql, 'UPDATE ') && str_contains($query->sql, 'seedbonus + CASE id')) {
                $advanced = true;
                DB::statement('SET timestamp = '.($at + 3600));
            }
        });
        expect(app(Kernel::class)->call('auto:bon_allocation'))->toBe(0);
        expect($advanced)->toBeTrue()
            ->and(DB::table('users')->whereBetween('id', [15001, 15501])->where('seedbonus', '1000000036.00')->count())->toBe(501);
    } finally {
        DB::statement('SET timestamp = 0');
        DB::table('torrents')->where('id', 12001)->update(['created_at' => $createdAt]);
    }
});
