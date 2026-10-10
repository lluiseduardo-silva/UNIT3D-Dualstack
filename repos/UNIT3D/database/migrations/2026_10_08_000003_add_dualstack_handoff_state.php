<?php

declare(strict_types=1);

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class () extends Migration {
    public function up(): void
    {
        if (!Schema::hasColumn('tracker_ownership', 'php_journal_drained')) {
            Schema::table('tracker_ownership', fn (Blueprint $table) => $table->boolean('php_journal_drained')->default(false));
        }
    }

    public function down(): void
    {
        throw new RuntimeException('Preserve a confirmacao de drenagem durante a troca de backend.');
    }
};
