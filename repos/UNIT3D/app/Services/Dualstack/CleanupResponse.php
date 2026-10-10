<?php

declare(strict_types=1);

namespace App\Services\Dualstack;

use Illuminate\Http\RedirectResponse;
use Illuminate\Support\Facades\Log;
use Throwable;

final class CleanupResponse
{
    public static function submit(?int $userId): RedirectResponse
    {
        try {
            app(CleanupRequests::class)->submit($userId);

            return redirect()->back()->with('success', __('dualstack.cleanup-queued'));
        } catch (CleanupRejected $error) {
            return redirect()->back()->withErrors(__($error->getMessage()));
        } catch (Throwable $error) {
            // SQL e dados de conexao nao devem vazar para a resposta ou para o log.
            Log::error('Falha ao registrar limpeza dualstack.', ['exception' => $error::class]);

            return redirect()->back()->withErrors(__('dualstack.cleanup-unavailable'));
        }
    }
}
