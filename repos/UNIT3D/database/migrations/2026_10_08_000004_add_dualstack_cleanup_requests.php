<?php

declare(strict_types=1);

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class () extends Migration {
    public function up(): void
    {
        if (!Schema::hasTable('tracker_cleanup_requests')) {
            Schema::create('tracker_cleanup_requests', function (Blueprint $table): void {
                $table->id();
                $table->string('scope', 32)->unique();
                $table->unsignedInteger('user_id')->nullable();
                $table->timestamp('cutoff');
                $table->timestamp('created_at');
            });
        }
    }

    public function down(): void
    {
        throw new RuntimeException('Preserve solicitacoes de limpeza pendentes durante o rollback.');
    }
};
