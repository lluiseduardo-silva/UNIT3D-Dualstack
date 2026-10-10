<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();
$running = true;
pcntl_async_signals(true);
pcntl_signal(SIGTERM, function () use (&$running): void { $running = false; });
pcntl_signal(SIGINT, function () use (&$running): void { $running = false; });
// Mesma cadencia de cinco segundos da tag; apenas os consumidores do announce.
while ($running) {
    $begin = microtime(true);
    foreach (['auto:upsert_peers', 'auto:upsert_histories', 'auto:upsert_announces'] as $command) {
        if ($kernel->call($command) !== 0) {
            throw new RuntimeException('Falha no consumidor '.$command);
        }
    }
    usleep((int) max(0, 5_000_000 - (microtime(true) - $begin) * 1_000_000));
}
