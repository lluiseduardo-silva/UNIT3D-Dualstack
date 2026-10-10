param(
    [Parameter(Mandatory)][ValidateSet('original','candidate')][string]$Variant,
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9-]+$')][string]$Label,
    [Parameter(Mandatory)][string]$IdentityFile,
    [ValidateSet(1000,54000,100000)][int]$Peers = 1000,
    [ValidateSet(0,50,100)][int]$DualPercent = 50,
    [ValidateSet('popular','distributed')][string]$Distribution = 'popular',
    [ValidateRange(1,2000)][int]$Rate = 1000,
    [ValidateRange(0,25)][int]$Numwant = 25,
    [ValidateRange(0,300)][int]$Warmup = 30,
    [ValidateRange(1,900)][int]$Seconds = 60,
    [ValidateSet(0,5)][int]$MonitorInterval = 5,
    [ValidateSet(0,100,3000)][int]$LegacyFlushMilliseconds = 0,
    [switch]$AnalyzeFixture
)

$ErrorActionPreference = 'Stop'
$directory = Join-Path $PSScriptRoot 'results/rust-validation'
[IO.Directory]::CreateDirectory($directory) | Out-Null
if (Test-Path -LiteralPath "$directory/$Label-setup.txt") { throw 'O identificador desta rodada ja existe.' }
$IdentityFile = (Resolve-Path -LiteralPath $IdentityFile).Path
$base = '/opt/unit3d-dualstack'
$jobs = @()
$backendStarted = $false
if ($LegacyFlushMilliseconds -ne 0 -and $Variant -ne 'original') { throw 'Controle de flush exclusivo do original.' }

function Invoke-Lab([string]$Target, [string]$Command) {
    $output = @(& ssh -i $IdentityFile -o BatchMode=yes -o ConnectTimeout=10 $Target $Command 2>&1)
    $code = $LASTEXITCODE
    $output | ForEach-Object { "$_" } | Add-Content -Encoding utf8 "$directory/$Label-setup.txt"
    if ($code -ne 0) { throw "Etapa remota em $Target terminou com codigo $code." }
}

$remoteJob = {
    param($Identity, $Target, $Command)
    $output = @(& ssh -i $Identity -o BatchMode=yes -o ConnectTimeout=10 $Target $Command 2>&1)
    [pscustomobject]@{ ExitCode = $LASTEXITCODE; Lines = @($output | ForEach-Object { "$_" }) }
}

try {
    Write-Output "Preparando ${Label}: $Variant, $Peers peers, $DualPercent por cento dualstack, $Distribution."
    $guard = 'test "$(hostname)" = unit3d-ds-tracker || exit 1; for n in unit3d-ds-rust unit3d-ds-php unit3d-ds-nginx unit3d-ds-worker unit3d-ds-flush unit3d-ds-coordinator unit3d-ds-legacy-rust; do if docker container inspect "$n" >/dev/null 2>&1; then echo "Tracker ja existente: $n"; exit 1; fi; done'
    Invoke-Lab 'lab@10.0.1.27' ("sudo bash -c '" + $guard + "'")
    Invoke-Lab 'lab@10.0.1.27' "sudo docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test -v ${base}/repos/UNIT3D:/app -v ${base}/lab:/lab:ro unit3d-ds-php:baseline php /lab/initialize-journal-test.php"
    Invoke-Lab 'lab@10.0.1.25' "sudo python3 $base/benchmark-fixture.py --peers $Peers --dual-percent $DualPercent --distribution $Distribution"
    if ($AnalyzeFixture) {
        Invoke-Lab 'lab@10.0.1.25' "sudo python3 $base/analyze-benchmark-fixture.py"
    }
    $backendStarted = $true
    $flushOption = if ($LegacyFlushMilliseconds) { " $LegacyFlushMilliseconds" } else { '' }
    Invoke-Lab 'lab@10.0.1.27' "sudo bash $base/lab/benchmark-backend.sh start rust $Variant$flushOption"
    Invoke-Lab 'lab@10.0.1.25' "python3 $base/benchmark-readiness.py"
    $observe = $Warmup+$Seconds+15
    # O padrao preserva o gerador anterior; permite implantar o diagnostico sem
    # alterar uma serie de repeticoes que ja esteja em andamento.
    $monitorOption = if ($MonitorInterval -eq 0) { ' --monitor-interval 0' } else { '' }
    $specs = @(
        @('load','lab@10.0.1.25',"sudo python3 $base/benchmark-http.py --backend rust --variant $Variant --rate $Rate --warmup $Warmup --seconds $Seconds --numwant $Numwant --load same-requests$monitorOption"),
        @('data','lab@10.0.1.26',"sudo python3 /tmp/unit3d-benchmark-io.py --seconds $observe --mysql"),
        @('host','root@10.0.1.4',"python3 /tmp/unit3d-benchmark-io.py --seconds $observe"),
        @('tracker','lab@10.0.1.27',"sudo python3 $base/lab/benchmark-monitor.py --seconds $observe --label $Label")
    )
    foreach ($spec in $specs) {
        $jobs += Start-Job -Name $spec[0] -ScriptBlock $remoteJob -ArgumentList $IdentityFile,$spec[1],$spec[2]
    }
    Write-Output "Medindo $Label; aquecimento ${Warmup}s, janela ${Seconds}s, ${Rate}req/s, numwant=$Numwant."
    while (@($jobs | Where-Object State -in @('Running','NotStarted')).Count -gt 0) {
        $pending = @($jobs | Where-Object State -in @('Running','NotStarted'))
        Wait-Job -Job $pending -Timeout 15 | Out-Null
    }
    $failures = @()
    foreach ($job in $jobs) {
        if ($job.State -ne 'Completed') { $failures += $job.Name; continue }
        $result = Receive-Job -Job $job
        $suffix = if ($job.Name -in @('data','host')) { 'jsonl' } else { 'txt' }
        $result.Lines | Set-Content -Encoding utf8 "$directory/$Label-$($job.Name).$suffix"
        if ($result.ExitCode -ne 0) { $failures += $job.Name }
        if ($job.Name -eq 'load' -and $result.ExitCode -eq 0) {
            $summary = $result.Lines[-1] | ConvertFrom-Json
            $summary | Add-Member -NotePropertyName legacy_flush_override_ms -NotePropertyValue $LegacyFlushMilliseconds
            $summary | Add-Member -NotePropertyName fixture_statistics_analyzed -NotePropertyValue ([bool]$AnalyzeFixture)
            $summary | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 "$directory/$Label-summary.json"
            if ($summary.status -ne 'passed') { $failures += 'load-status' }
            $summary | ConvertTo-Json -Depth 10 -Compress | Write-Output
        }
    }
    if ($failures.Count) { throw ('Falha na rodada: '+($failures -join ', ')) }
} finally {
    foreach ($job in $jobs) {
        if ($job.State -in @('Running','NotStarted')) { Stop-Job -Job $job }
        Remove-Job -Job $job -Force
    }
    if ($backendStarted) {
        Invoke-Lab 'lab@10.0.1.27' "sudo bash $base/lab/benchmark-backend.sh stop rust $Variant"
        Write-Output "Tracker drenado e encerrado: $Label."
    }
}
