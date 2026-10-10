<?php

declare(strict_types=1);

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class () extends Migration {
    public function up(): void
    {
        if (!Schema::hasColumn('tracker_ownership', 'legacy_reconciliation_required')) {
            Schema::table('tracker_ownership', fn (Blueprint $table) => $table->boolean('legacy_reconciliation_required')->default(false));
        }
    }

    public function down(): void
    {
        throw new RuntimeException('Preserve o bloqueio de reconciliacao durante o retorno do binario.');
    }
};
