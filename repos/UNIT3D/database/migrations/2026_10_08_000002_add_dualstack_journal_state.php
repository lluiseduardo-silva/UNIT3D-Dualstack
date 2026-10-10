<?php

declare(strict_types=1);

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

return new class () extends Migration {
    public function up(): void
    {
        if (!Schema::hasColumn('peers', 'protocol_state')) {
            Schema::table('peers', fn (Blueprint $table) => $table->json('protocol_state')->nullable());
        }

        if (!Schema::hasColumn('history', 'state_version')) {
            Schema::table('history', fn (Blueprint $table) => $table->unsignedBigInteger('state_version')->default(0));
        }

        if (!Schema::hasColumn('history', 'swarm_updated_at')) {
            Schema::table('history', fn (Blueprint $table) => $table->timestamp('swarm_updated_at')->nullable());
        }

        if (!Schema::hasTable('tracker_ownership')) {
            Schema::create('tracker_ownership', function (Blueprint $table): void {
                $table->unsignedTinyInteger('id')->primary();
                $table->unsignedBigInteger('generation')->default(0);
                $table->char('owner_id', 36)->nullable();
                $table->enum('backend', ['php', 'rust'])->nullable();
                $table->dateTime('lease_expires_at', 3)->nullable();
            });
        }
        // Reexecutar a migracao nunca reinicia a geracao do proprietario.
        DB::table('tracker_ownership')->upsert([['id' => 1, 'generation' => 0]], ['id'], ['id']);
    }

    public function down(): void
    {
        throw new RuntimeException('Preserve o estado de versao e propriedade durante o retorno do binario.');
    }
};
