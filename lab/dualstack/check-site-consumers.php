<?php

declare(strict_types=1);

require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Http\Controllers\TorrentReseedController;
use App\Http\Controllers\User\ResurrectionController;
use App\Models\User;
use App\Repositories\ChatRepository;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Notification;
use Illuminate\Support\Facades\Queue;

$report = ['status' => 'running', 'production' => false, 'checks' => []];
$transaction = false;
try {
    if (DB::getDatabaseName() !== 'unit3d_dualstack_journal_test' || DB::getDriverName() !== 'mysql'
        || DB::table('tracker_ownership')->whereRaw('lease_expires_at > UTC_TIMESTAMP(3)')->exists()) {
        throw new RuntimeException('Exige banco isolado sem proprietario.');
    }
    DB::beginTransaction(); $transaction = true;
    config(['dualstack.enabled'=>true,'dualstack.endpoint_ttl'=>7200,'cache.default'=>'array','scout.driver'=>'null']);
    Notification::fake(); Queue::fake();
    $chat=Mockery::mock(ChatRepository::class); $chat->shouldReceive('systemMessage')->andReturnSelf();
    $app->instance(ChatRepository::class,$chat);
    DB::table('peers')->delete(); DB::table('history')->delete();
    DB::table('torrent_reseeds')->delete(); DB::table('resurrections')->delete();
    DB::table('users')->where('id',12001)->update(['deleted_at'=>null,'tracker_removal_state'=>0]);
    DB::table('torrents')->where('id',12001)->update(['user_id'=>12002,'deleted_at'=>null,'tracker_removal_state'=>0,'created_at'=>now()->subDays(31)]);
    $viewer=User::findOrFail(12001); auth()->setUser($viewer);
    $request=Request::create('/lab/consumer','POST',['torrent_id'=>12001]); $request->setUserResolver(fn ()=>$viewer);
    $check=function (string $name, mixed $expected, mixed $actual) use (&$report): void {
        $report['checks'][]=['name'=>$name,'expected'=>$expected,'actual'=>$actual,'passed'=>$expected===$actual];
    };
    foreach (['ipv4','ipv6','sum','auto'] as $mode) {
        $viewer->peer_count_mode=$mode;
        foreach ([2=>true,3=>false] as $total=>$allowed) {
            DB::table('torrent_reseeds')->delete();
            DB::table('torrents')->where('id',12001)->update(['seeders'=>$total,'seeders_ipv4'=>0,'seeders_ipv6'=>$total]);
            app(TorrentReseedController::class)->store($request,12001);
            $check('reseed_'.$mode.'_unique_'.$total,$allowed,DB::table('torrent_reseeds')->exists());
        }
        foreach ([1=>false,0=>true] as $total=>$allowed) {
            DB::table('resurrections')->delete();
            DB::table('torrents')->where('id',12001)->update(['seeders'=>$total,'seeders_ipv4'=>0,'seeders_ipv6'=>$total]);
            app(ResurrectionController::class)->store($request,$viewer);
            $check('resurrection_'.$mode.'_unique_'.$total,$allowed,DB::table('resurrections')->exists());
        }
    }
    DB::table('bon_earnings')->delete();
    $rule=DB::table('bon_earnings')->insertGetId(['position'=>1,'variable'=>'1','multiplier'=>10,'operation'=>'append','name'=>'Consumer fixture','description'=>'isolated']);
    DB::table('bon_earning_conditions')->insert(['bon_earning_id'=>$rule,'operand1'=>'connectable','operator'=>'=','operand2'=>1]);
    $identity=['user_id'=>12001,'torrent_id'=>12001,'peer_id'=>str_repeat('C',20)];
    DB::table('peers')->insert($identity+['ip'=>inet_pton('172.29.92.30'),'port'=>6881,'agent'=>'consumer-fixture',
        'uploaded'=>1000,'downloaded'=>0,'left'=>0,'seeder'=>true,'active'=>true,'visible'=>true,'connectable'=>true,
        'created_at'=>now()->subHour(),'updated_at'=>now()]);
    DB::table('history')->insert(['user_id'=>12001,'torrent_id'=>12001,'agent'=>'consumer-fixture',
        'client_uploaded'=>1000,'client_downloaded'=>0,'active'=>true,'seeder'=>true,'immune'=>false,
        'seedtime'=>3600,'created_at'=>now()->subHour(),'updated_at'=>now()]);
    foreach ([4=>'172.29.92.30',6=>'fd42:756e:6974:92::30'] as $family=>$ip) {
        DB::table('peer_ips')->insert($identity+['family'=>$family,'ip'=>inet_pton($ip),'port'=>6881,
            'connectable'=>$family===4 ? true : null,'last_announced_at'=>now(),'revision'=>1,'created_at'=>now(),'updated_at'=>now()]);
    }
    foreach ([false,true] as $external) {
        config(['announce.external_tracker.is_enabled'=>$external]);
        DB::table('peer_ips')->where('family',4)->update(['last_announced_at'=>now()]);
        $before=(float)DB::table('users')->where('id',12001)->value('seedbonus');
        Artisan::call('auto:bon_allocation');
        $after=(float)DB::table('users')->where('id',12001)->value('seedbonus');
        $check('bon_current_positive_'.($external?'rust':'php'),10.0,$after-$before);
        // Estado legitimo entre o vencimento de IPv4 e a limpeza periodica:
        // IPv6 esta vigente, mas nunca recebeu checagem positiva.
        DB::table('peer_ips')->where('family',4)->update(['last_announced_at'=>now()->subSeconds(7201)]);
        $before=$after; Artisan::call('auto:bon_allocation');
        $after=(float)DB::table('users')->where('id',12001)->value('seedbonus');
        $check('bon_expired_positive_only_'.($external?'rust':'php'),0.0,$after-$before);
    }
    $report['status']=collect($report['checks'])->every('passed') ? 'passed' : 'failed';
} catch (Throwable $error) {
    $report['status']='failed'; $report['error_type']=$error::class; $report['error_code']=$error->getCode();
    $report['error_origin']=basename($error->getFile()).':'.$error->getLine();
} finally {
    if ($transaction) { DB::rollBack(); }
    Mockery::close();
    $report['rolled_back']=$transaction;
}
echo json_encode($report,JSON_PRETTY_PRINT|JSON_THROW_ON_ERROR)."\n";
exit($report['status']==='passed' ? 0 : 1);
