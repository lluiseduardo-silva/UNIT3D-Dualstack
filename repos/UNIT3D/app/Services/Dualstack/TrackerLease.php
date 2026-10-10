<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;
use Illuminate\Support\Str;
use RuntimeException;

final readonly class TrackerLease
{
    public function __construct(public int $generation, public string $ownerId)
    {
    }

    public static function base(): string
    {
        return config('cache.prefix').':dualstack:v1';
    }

    public function prefix(): string
    {
        return self::base().':g:'.$this->generation;
    }

    public static function acquire(): self
    {
        $started = hrtime(true);
        $lease = DB::transaction(function (): self {
            $owner = DB::table('tracker_ownership')->where('id', 1)
                ->selectRaw('*, lease_expires_at > UTC_TIMESTAMP(3) AS live')->lockForUpdate()->first();

            if ($owner === null || $owner->live) {
                throw new RuntimeException('O swarm ja possui proprietario ativo ou o schema esta incompleto.');
            }

            if ($owner->legacy_reconciliation_required) {
                throw new RuntimeException('Reconciliacao legada pendente; execute dualstack:legacy reconcile --offline.');
            }
            $lease = new self((int) $owner->generation + 1, (string) Str::uuid());
            DB::table('tracker_ownership')->where('id', 1)->update([
                'generation'          => $lease->generation, 'owner_id' => $lease->ownerId, 'backend' => 'php',
                'lease_expires_at'    => DB::raw('UTC_TIMESTAMP(3) + INTERVAL 30 SECOND'),
                'php_journal_drained' => false,
            ]);

            return $lease;
        }, 3);
        $redis = Redis::connection('announce');
        $published = $redis->eval(<<<'LUA'
local generation = tonumber(redis.call('HGET', KEYS[1], 'generation') or '0')
if generation > tonumber(ARGV[1]) then return 0 end
if generation == tonumber(ARGV[1]) and redis.call('HGET', KEYS[1], 'owner_id') ~= ARGV[2] then return 0 end
redis.call('HSET', KEYS[1], 'generation', ARGV[1], 'owner_id', ARGV[2], 'backend', 'php', 'ready', '0')
return 1
LUA, 1, self::base().':owner', $lease->generation, $lease->ownerId);

        if ($published !== 1) {
            throw new RuntimeException('A geracao foi substituida antes da inicializacao.');
        }
        $lease->heartbeat($started);

        return $lease;
    }

    public static function current(): self
    {
        $owner = Redis::connection('announce')->hGetAll(self::base().':owner');

        if (($owner['backend'] ?? null) !== 'php' || !isset($owner['generation'], $owner['owner_id'])) {
            throw new RuntimeException('Proprietario PHP indisponivel.');
        }

        return new self((int) $owner['generation'], $owner['owner_id']);
    }

    public function renew(): void
    {
        $started = hrtime(true);
        $changed = DB::table('tracker_ownership')->where('id', 1)->where('owner_id', $this->ownerId)
            ->where('generation', $this->generation)->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')
            ->update(['lease_expires_at' => DB::raw('UTC_TIMESTAMP(3) + INTERVAL 30 SECOND')]);

        if ($changed !== 1) {
            throw new RuntimeException('Propriedade do swarm perdida; novas transicoes foram interrompidas.');
        }
        $this->heartbeat($started);
    }

    private function heartbeat(int $started): void
    {
        $ttl = 10000 - (int) ceil((hrtime(true) - $started) / 1e6);

        if ($ttl <= 0) {
            throw new RuntimeException('Renovacao demorou alem da margem segura da lease.');
        }
        $result = Redis::connection('announce')->eval(<<<'LUA'
if redis.call('HGET', KEYS[1], 'owner_id') ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[2], ARGV[1], 'PX', ARGV[2])
return 1
LUA, 2, self::base().':owner', self::base().':heartbeat', $this->ownerId, $ttl);

        if ($result !== 1) {
            throw new RuntimeException('Geracao de proprietario substituida durante renovacao.');
        }
    }

    public function ready(bool $ready): void
    {
        $result = Redis::connection('announce')->eval(<<<'LUA'
if redis.call('HGET', KEYS[1], 'owner_id') ~= ARGV[1] or redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end
redis.call('HSET', KEYS[1], 'ready', ARGV[2])
return 1
LUA, 2, self::base().':owner', self::base().':heartbeat', $this->ownerId, $ready ? '1' : '0');

        if ($result !== 1) {
            throw new RuntimeException('Nao foi possivel confirmar a disponibilidade do proprietario.');
        }
    }

    /** Chamar dentro da transacao, antes dos locks de usuarios e torrents. */
    public function assertPersistable(): void
    {
        $owner = DB::table('tracker_ownership')->where('id', 1)
            ->selectRaw('*, lease_expires_at > UTC_TIMESTAMP(3) AS live')->sharedLock()->first();

        if ($owner === null || !$owner->live || $owner->owner_id !== $this->ownerId || (int) $owner->generation !== $this->generation) {
            throw new RuntimeException('Lote recusado: proprietario ou geracao expirados.');
        }
    }

    public function release(): void
    {
        // Fecha todos os produtores antes de certificar a fila vazia, atomicamente.
        $drained = Redis::connection('announce')->eval(
            <<<'LUA'
if redis.call('HGET', KEYS[1], 'owner_id') ~= ARGV[1] then return 0 end
redis.call('HSET', KEYS[1], 'ready', '0')
redis.call('DEL', KEYS[2])
if redis.call('XLEN', KEYS[3]) ~= 0 or redis.call('LLEN', KEYS[4]) ~= 0 or redis.call('LLEN', KEYS[5]) ~= 0 then return 0 end
return 1
LUA,
            5,
            self::base().':owner',
            self::base().':heartbeat',
            self::base().':transitions',
            config('cache.prefix').':peers:batch',
            config('cache.prefix').':histories:batch',
            $this->ownerId
        );
        DB::transaction(function () use ($drained): void {
            // A admissao de limpezas usa o mesmo lock. Uma solicitacao concorrente
            // nao pode entrar entre a certificacao da fila e a liberacao da lease.
            $owner = DB::table('tracker_ownership')->where('id', 1)->lockForUpdate()->first();

            if ($owner === null || $owner->owner_id !== $this->ownerId || (int) $owner->generation !== $this->generation) {
                return;
            }
            $pending = DB::table('tracker_cleanup_requests')->exists();
            DB::table('tracker_ownership')->where('id', 1)
                ->update(['lease_expires_at' => null, 'php_journal_drained' => $drained === 1 && !$pending]);
        }, 3);
    }
}
