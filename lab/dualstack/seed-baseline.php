<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
if (config('database.connections.mysql.database') !== 'unit3d_baseline') {
    throw new RuntimeException('Fixtures permitidas apenas no banco isolado do laboratorio.');
}
fake()->seed(920031);
$fixture = Illuminate\Database\Eloquent\Model::withoutEvents(function (): array {
    $group = App\Models\Group::factory()->create([
        'id' => 120, 'name' => 'Laboratorio', 'slug' => 'lab-member',
        'download_slots' => null, 'is_freeleech' => false,
        'is_double_upload' => false, 'is_immune' => false,
    ]);
    $users = [];
    for ($i = 1; $i <= 6; $i++) {
        $user = App\Models\User::factory()->create([
            'id' => 12000 + $i, 'username' => 'lab'.$i,
            'email' => 'lab'.$i.'@example.invalid', 'group_id' => $group->id,
            'uploaded' => 0, 'downloaded' => 0, 'can_download' => true,
            'seedbonus' => 0, 'fl_tokens' => 0, 'hitandruns' => 0,
        ]);
        $users[] = ['id' => $user->id, 'passkey' => $user->passkey];
    }
    $torrents = [];
    for ($i = 1; $i <= 2; $i++) {
        $hash = hash('sha1', 'unit3d-dualstack-baseline-'.$i, true);
        $torrent = App\Models\Torrent::factory()->create([
            'id' => 12000 + $i, 'name' => 'Dualstack laboratorio '.$i,
            'info_hash' => $hash, 'user_id' => $users[0]['id'],
            'size' => 65536, 'num_file' => 1, 'free' => 0, 'doubleup' => false,
            'seeders' => 0, 'leechers' => 0, 'times_completed' => 0,
            'imdb' => 0, 'tvdb' => 0, 'tmdb_movie_id' => null,
            'tmdb_tv_id' => null, 'mal' => 0, 'igdb' => 0,
        ]);
        $torrents[] = ['id' => $torrent->id, 'info_hash_hex' => bin2hex($hash)];
    }
    return compact('users', 'torrents');
});
file_put_contents('/private/fixture.json', json_encode($fixture, JSON_THROW_ON_ERROR));
chmod('/private/fixture.json', 0600);
echo "Fixtures sinteticas criadas; credenciais salvas apenas no arquivo privado.\n";
