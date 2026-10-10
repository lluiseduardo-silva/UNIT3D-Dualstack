<?php
declare(strict_types=1);
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Services\DownloadRefund;
use Illuminate\Support\Facades\DB;

if (DB::getDatabaseName() !== 'unit3d_dualstack_journal_test') { throw new RuntimeException('Banco incorreto'); }
config(['other.refundable'=>true,'hitrun.seedtime'=>3600]);
$mode=$argv[1] ?? '';
if ($mode==='prepare') {
    if (DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists()) { throw new RuntimeException('Encerre o backend'); }
    DB::table('peers')->delete(); DB::table('history')->delete();
    DB::table('personal_freeleeches')->delete(); DB::table('freeleech_tokens')->delete(); DB::table('featured_torrents')->delete();
    DB::table('users')->whereBetween('id',[12001,12006])->update(['uploaded'=>0,'downloaded'=>1000000000,'can_download'=>true,'group_id'=>120,'is_donor'=>false,'is_lifetime'=>false,'deleted_at'=>null,'tracker_removal_state'=>0]);
    DB::table('groups')->where('id',120)->update(['is_freeleech'=>false,'is_double_upload'=>false,'download_slots'=>null]);
    DB::table('torrents')->whereIn('id',[12001,12002])->update(['size'=>1000,'user_id'=>1,'free'=>0,'doubleup'=>false,'status'=>1,'deleted_at'=>null,'tracker_removal_state'=>0]);
    DB::table('torrents')->update(array_fill_keys(['seeders','leechers','seeders_ipv4','seeders_ipv6','leechers_ipv4','leechers_ipv6','times_completed'],0));
    foreach (range(12001,12006) as $user) {
        foreach ([12001,12002] as $torrent) {
            DB::table('history')->insert(['user_id'=>$user,'torrent_id'=>$torrent,'agent'=>'refund-http','client_uploaded'=>0,'client_downloaded'=>0,'active'=>true,'seeder'=>true,'immune'=>false,
                'seedtime'=>12*30*24*60*60+3600,'created_at'=>now()->subDays(2),'updated_at'=>now()]);
        }
    }
    foreach (range(12001,12006) as $id) {
        $key=DB::table('users')->where('id',$id)->value('passkey');
        cache()->forget('user:'.$key); cache()->forget('personal_freeleech:'.$id);
        foreach ([12001,12002] as $torrent) { cache()->forget('freeleech_token:'.$id.':'.$torrent); }
    }
    cache()->forget('group:120'); cache()->forget('featured-torrent-ids');
    foreach (DB::table('torrents')->whereIn('id',[12001,12002])->pluck('info_hash') as $hash) { cache()->forget('announce-torrents:by-infohash:'.$hash); }
    echo "Fixture de carga isolada preparada: 6 usuarios, 2 torrents, 12 historicos.\n";
} elseif ($mode==='work') {
    $duration=(int)($argv[2] ?? 60);
    if ($duration<1 || $duration>180) { throw new RuntimeException('Duracao invalida'); }
    $deadline=microtime(true)+$duration; $times=[];
    do {
        $start=microtime(true); app(DownloadRefund::class)->run(); $times[]=(microtime(true)-$start)*1000;
        usleep(100000);
    } while (microtime(true)<$deadline);
    sort($times);
    echo json_encode(['refund_runs'=>count($times),'p95_ms'=>$times[(int)floor((count($times)-1)*0.95)],'max_ms'=>max($times)])."\n";
} else { throw new RuntimeException('Use prepare ou work'); }
