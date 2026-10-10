param(
    [Parameter(Mandatory)][string]$PlanFile,
    [Parameter(Mandatory)][string]$IdentityFile,
    [ValidateSet('density','throughput')][string]$Study='density',
    [ValidateSet('reference','instrumented','unobserved','drain','writer-cadence','writer-endpoints')][string]$Mode='reference',
    [ValidateSet(200,500)][int]$Batch=200
)
$ErrorActionPreference='Stop'
$IdentityFile=(Resolve-Path -LiteralPath $IdentityFile).Path
$PlanFile=(Resolve-Path -LiteralPath $PlanFile).Path
$plan=[IO.File]::ReadAllText($PlanFile) | ConvertFrom-Json
$label=$plan.name
if($label -notmatch '^[a-z0-9-]+$'){throw 'Nome de serie invalido'}
$dir=Join-Path $PSScriptRoot "results/$Study"
[IO.Directory]::CreateDirectory($dir) | Out-Null
if(Test-Path -LiteralPath "$dir/$label-setup.txt"){throw 'Serie ja existente'}
$base='/opt/unit3d-dualstack'
$backend="bash $base/lab/benchmark-backend.sh"
$startBackend="$backend start rust candidate"
$stopBackend="$backend stop rust candidate"
if($Study -eq 'throughput'){
    $startBackend="bash $base/lab/throughput-backend.sh start $Mode $Batch"
    $stopBackend="bash $base/lab/throughput-backend.sh stop $Mode $Batch"
}
$started=$false
$jobs=@()
function Remote([string]$Target,[string]$Command){
    $lines=@(& ssh -i $IdentityFile -o BatchMode=yes -o ConnectTimeout=10 $Target $Command 2>&1)
    $code=$LASTEXITCODE
    $lines | Add-Content -Encoding utf8 "$dir/$label-setup.txt"
    if($code -ne 0){throw "Falha remota em $Target, codigo $code"}
}
$jobCode={
    param($key,$hostName,$command,$file)
    & ssh -i $key -o BatchMode=yes -o ConnectTimeout=10 $hostName $command 2>&1 | ForEach-Object { "$_" | Add-Content -Encoding utf8 $file }
    $LASTEXITCODE
}
try{
    # Os binlogs de series anteriores permanecem no laboratorio; nunca desligar durabilidade para caber no disco.
    Remote 'lab@10.0.1.26' "test `"`$(df -B1 --output=avail / | tail -n 1)`" -gt 2147483648 || { echo 'Menos de 2 GiB livres na VM de dados'; exit 1; }"
    $guard='test "$(hostname)" = unit3d-ds-tracker || exit 1; for n in unit3d-ds-rust unit3d-ds-php unit3d-ds-nginx unit3d-ds-worker unit3d-ds-flush unit3d-ds-coordinator unit3d-ds-legacy-rust; do if docker container inspect "$n" >/dev/null 2>&1; then echo "Tracker existente: $n"; exit 1; fi; done'
    Remote 'lab@10.0.1.27' ("sudo bash -c '"+$guard+"'")
    & scp -i $IdentityFile $PlanFile "lab@10.0.1.25:/tmp/$label.json"
    if($LASTEXITCODE -ne 0){throw 'Falha copiando plano'}
    Remote 'lab@10.0.1.25' "sudo install -m 644 /tmp/$label.json $base/$label.json"
    Remote 'lab@10.0.1.27' "sudo docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test -v ${base}/repos/UNIT3D:/app -v ${base}/lab:/lab:ro unit3d-ds-php:baseline php /lab/initialize-journal-test.php"
    Write-Output "Preparando fixture: $label"
    Remote 'lab@10.0.1.25' "sudo python3 $base/density-fixture.py $label.json"
    $started=$true
    Remote 'lab@10.0.1.27' "sudo $startBackend"
    Remote 'lab@10.0.1.25' "python3 $base/benchmark-readiness.py"
    $duration=15
    foreach($phase in $plan.phases){$duration += $phase.warmup+$phase.seconds+3}
    if($Study -eq 'throughput'){
        foreach($phase in $plan.phases){
            $rate=0
            foreach($group in $phase.groups.PSObject.Properties){$rate += $group.Value.rate}
            $duration += [Math]::Ceiling([Math]::Max(0,$rate-1800)*($phase.warmup+$phase.seconds)/1800)+3
        }
    }
    $specs=@(
        @('load','lab@10.0.1.25',"sudo python3 $base/$Study-http.py $label.json",'jsonl'),
        @('data','lab@10.0.1.26',"sudo python3 /tmp/unit3d-benchmark-io.py --seconds $duration --mysql",'jsonl'),
        @('host','root@10.0.1.4',"python3 /tmp/unit3d-benchmark-io.py --seconds $duration",'jsonl'),
        @('tracker','lab@10.0.1.27',"sudo python3 $base/lab/benchmark-monitor.py --seconds $duration --label $label",'txt')
    )
    $stopSent=$false
    if($Study -eq 'throughput'){
        foreach($spec in $specs){
            if($spec[0] -eq 'load'){continue}
            Remote $spec[1] "test ! -e /tmp/$label.stop"
            $spec[2]+=" --stop-file /tmp/$label.stop"
        }
    }
    foreach($spec in $specs){
        $jobs+=Start-Job -Name $spec[0] -ScriptBlock $jobCode -ArgumentList $IdentityFile,$spec[1],$spec[2],"$dir/$label-$($spec[0]).$($spec[3])"
    }
    Write-Output "Serie em execucao: $label; $($plan.phases.Count) fases; observadores por ${duration}s"
    while(@($jobs | Where-Object State -in @('Running','NotStarted')).Count){
        Wait-Job -Job @($jobs | Where-Object State -in @('Running','NotStarted')) -Timeout 15 | Out-Null
        if($Study -eq 'throughput' -and -not $stopSent -and ($jobs | Where-Object Name -eq 'load').State -eq 'Completed'){
            foreach($spec in $specs){
                if($spec[0] -ne 'load'){Remote $spec[1] "touch /tmp/$label.stop"}
            }
            $stopSent=$true
        }
    }
    foreach($job in $jobs){
        if($job.State -ne 'Completed'){throw "Job incompleto: $($job.Name)"}
        $code=Receive-Job $job
        if($code -ne 0){throw "Job falhou: $($job.Name), $code"}
    }
    $last=Get-Content "$dir/$label-load.jsonl" -Tail 1 | ConvertFrom-Json
    if($last.status -ne 'series_passed'){throw 'Serie nao aprovada funcionalmente'}
    $last | ConvertTo-Json -Compress | Write-Output
}finally{
    foreach($job in $jobs){
        if($job.State -in @('Running','NotStarted')){Stop-Job $job}
        Remove-Job $job -Force
    }
    if($started){
        if($Study -eq 'throughput'){
            & ssh -i $IdentityFile -o BatchMode=yes lab@10.0.1.27 'sudo docker logs unit3d-ds-rust 2>&1 | grep "^DS_METRIC "' | Set-Content -Encoding utf8 "$dir/$label-metrics.txt"
        }
        $stopFailure=$null
        try { Remote 'lab@10.0.1.27' "sudo $stopBackend" } catch { $stopFailure=$_ }
        if($Study -eq 'throughput'){
            $temporary=Join-Path $PSScriptRoot '../../.local/throughput'
            [IO.Directory]::CreateDirectory($temporary) | Out-Null
            foreach($endpoint in @(@('lab@10.0.1.25','unit3d-ds-clients'),@('lab@10.0.1.27','unit3d-ds-tracker'))){
                Remote $endpoint[0] "sudo python3 $base/export-density-results.py $label"
                $archive=Join-Path $temporary "$label-$($endpoint[1]).tar.gz"
                & scp -i $IdentityFile "$($endpoint[0]):/tmp/density-export-$($endpoint[1]).tar.gz" $archive
                if($LASTEXITCODE -ne 0){throw 'Falha exportando resultados'}
                & tar -xzf $archive -C $dir
                if($LASTEXITCODE -ne 0){throw 'Falha extraindo resultados'}
            }
        }
        if($null -ne $stopFailure){throw $stopFailure}
    }
}
