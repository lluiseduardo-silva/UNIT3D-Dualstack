<?php

declare(strict_types=1);

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

return new class () extends Migration {
    public function up(): void
    {
        foreach (['state_version', 'session_generation', 'completion_reported'] as $column) {
            if (!Schema::hasColumn('peers', $column)) {
                Schema::table('peers', function (Blueprint $table) use ($column): void {
                    if ($column === 'completion_reported') {
                        $table->boolean($column)->default(false);
                    } else {
                        $table->unsignedBigInteger($column)->default(0);
                    }
                });
            }
        }

        if (!Schema::hasTable('peer_ips')) {
            Schema::create('peer_ips', function (Blueprint $table): void {
                $table->unsignedInteger('user_id');
                $table->unsignedInteger('torrent_id');
                $table->binary('peer_id', length: 20, fixed: true);
                $table->unsignedTinyInteger('family');
                $table->binary('ip', length: 16);
                $table->unsignedSmallInteger('port');
                $table->boolean('connectable')->nullable();
                $table->timestamp('last_announced_at');
                $table->timestamp('connectivity_checked_at')->nullable();
                $table->unsignedBigInteger('revision')->default(1);
                $table->timestamps();
                $table->primary(['user_id', 'torrent_id', 'peer_id', 'family']);
            });
        }

        // MySQL confirma cada DDL separadamente. Uma tabela existente pode ainda
        // estar sem FK ou indices depois de uma interrupcao do processo.
        if (!DB::table('information_schema.TABLE_CONSTRAINTS')
            ->where('CONSTRAINT_SCHEMA', DB::getDatabaseName())
            ->where('TABLE_NAME', 'peer_ips')
            ->where('CONSTRAINT_NAME', 'peer_ips_user_id_torrent_id_peer_id_foreign')
            ->exists()) {
            Schema::table('peer_ips', function (Blueprint $table): void {
                $table->foreign(['user_id', 'torrent_id', 'peer_id'])->references(['user_id', 'torrent_id', 'peer_id'])->on('peers')->cascadeOnDelete()->cascadeOnUpdate();
            });
        }

        foreach ([
            'peer_ips_torrent_family_live' => ['torrent_id', 'family', 'last_announced_at'],
            'peer_ips_expiration'          => ['last_announced_at'],
        ] as $name => $columns) {
            if (!DB::table('information_schema.STATISTICS')
                ->where('TABLE_SCHEMA', DB::getDatabaseName())
                ->where('TABLE_NAME', 'peer_ips')
                ->where('INDEX_NAME', $name)
                ->exists()) {
                Schema::table('peer_ips', fn (Blueprint $table) => $table->index($columns, $name));
            }
        }

        foreach ([
            'peer_ips_family_length'     => '((family = 4 AND OCTET_LENGTH(ip) = 4) OR (family = 6 AND OCTET_LENGTH(ip) = 16))',
            'peer_ips_positive_revision' => '(revision > 0)',
        ] as $name => $expression) {
            if (!DB::table('information_schema.TABLE_CONSTRAINTS')->where('CONSTRAINT_SCHEMA', DB::getDatabaseName())->where('TABLE_NAME', 'peer_ips')->where('CONSTRAINT_NAME', $name)->exists()) {
                DB::statement("ALTER TABLE peer_ips ADD CONSTRAINT {$name} CHECK {$expression}");
            }
        }

        foreach (['seeders_ipv4', 'seeders_ipv6', 'leechers_ipv4', 'leechers_ipv6'] as $counter) {
            if (!Schema::hasColumn('torrents', $counter)) {
                Schema::table('torrents', fn (Blueprint $table) => $table->unsignedInteger($counter)->default(0));
            }
        }

        if (!Schema::hasColumn('users', 'peer_count_mode')) {
            Schema::table('users', fn (Blueprint $table) => $table->enum('peer_count_mode', ['ipv4', 'ipv6', 'sum', 'auto'])->default('sum'));
        }

        if (!Schema::hasColumn('users', 'peer_count_auto_mode')) {
            Schema::table('users', fn (Blueprint $table) => $table->enum('peer_count_auto_mode', ['ipv4', 'ipv6', 'sum'])->default('sum'));
        }

        // Acrescentar valores nao altera nenhuma regra de remuneracao existente.
        DB::statement("ALTER TABLE bon_earnings MODIFY variable ENUM('1','age','size','seeders','leechers','times_completed','personal_release','internal','seedtime','connectable','seeders_ipv4','seeders_ipv6','leechers_ipv4','leechers_ipv6') NOT NULL");
        DB::statement("ALTER TABLE bon_earning_conditions MODIFY operand1 ENUM('1','age','size','seeders','leechers','times_completed','personal_release','internal','type_id','seedtime','connectable','seeders_ipv4','seeders_ipv6','leechers_ipv4','leechers_ipv6') NOT NULL");
    }

    public function down(): void
    {
        // Retornar o binario usa a projecao legada. Nao destruir endpoints ou regras BON.
        throw new RuntimeException('Schema dualstack aditivo: retorne o binario mantendo o schema expandido; a remocao exige migracao posterior.');
    }
};
