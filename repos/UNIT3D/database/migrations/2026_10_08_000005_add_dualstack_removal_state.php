<?php

declare(strict_types=1);

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class () extends Migration {
    public function up(): void
    {
        foreach (['users', 'torrents'] as $name) {
            if (!Schema::hasColumn($name, 'tracker_removal_state')) {
                Schema::table($name, function (Blueprint $table): void {
                    // 0: nao selado; 1: trafego confirmado, remocao em curso; 2: concluida.
                    $table->unsignedTinyInteger('tracker_removal_state')->default(0);
                });
            }

            if (!Schema::hasIndex($name, ['tracker_removal_state', 'deleted_at'])) {
                Schema::table($name, function (Blueprint $table): void {
                    $table->index(['tracker_removal_state', 'deleted_at']);
                });
            }
        }
    }

    public function down(): void
    {
        throw new RuntimeException('Preserve os marcadores de remocao durante o rollback.');
    }
};
