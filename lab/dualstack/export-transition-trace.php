<?php
declare(strict_types=1);
// Exporta exclusivamente os campos de auditoria da feature, nunca logs HTTP/SQL.
$events = [];
$fields = array_flip(['user_id', 'torrent_id', 'peer_id', 'generation', 'state_version', 'history_version', 'family', 'event', 'operation', 'upload_delta', 'download_delta', 'credited_upload', 'credited_download']);
foreach (glob('/app/storage/logs/laravel*.log') as $path) {
    $file = new SplFileObject($path);
    while (!$file->eof()) {
        $line = $file->fgets();
        if (preg_match('/dualstack\.transition (\{[^{}\r\n]*\})/', $line, $match)) {
            $event = json_decode($match[1], true, flags: JSON_THROW_ON_ERROR);
            $events[] = array_intersect_key($event, $fields);
        }
    }
}
echo json_encode(['count' => count($events), 'events' => $events], JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR)."\n";
