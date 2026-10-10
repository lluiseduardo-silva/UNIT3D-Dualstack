param(
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][string]$IdentityFile,
    [ValidateRange(1,8000)][int]$Rate=20,
    [ValidateRange(1,180)][int]$Seconds=10,
    [ValidateSet(0,1,9)][int]$Block=0,
    [switch]$OnePeer,
    [switch]$Recovery
)
$ErrorActionPreference='Stop'
if ($Name -notmatch '^[a-z0-9-]+$') {throw 'Nome inválido'}
$IdentityFile=(Resolve-Path -LiteralPath $IdentityFile).Path
$folder=if ($Recovery) {'lease-recovery'} else {'lease-probe'}
$dir=Join-Path $PSScriptRoot "results/$folder"
New-Item -ItemType Directory -Force $dir | Out-Null
if (Test-Path -LiteralPath "$dir/$Name-client.json") {throw 'Resultado já existe'}
function Remote([string]$HostName,[string]$Command) {
    $lines=@(& ssh -o BatchMode=yes -o ConnectTimeout=8 -i $IdentityFile $HostName $Command)
    $code=$LASTEXITCODE
    $lines | Add-Content -Encoding utf8 "$dir/$Name-lifecycle.jsonl"
    if ($code -ne 0) {throw "Falha remota: $HostName"}
}
$jobs=@()
$admin=if ($Recovery) {'/tmp/prepare-lease-recovery.py'} else {'/tmp/lease-probe-admin.py'}
$database=if ($Recovery) {' --database unit3d_dualstack_recovery_test'} else {''}
try {
    Remote 'lab@10.0.1.26' "sudo python3 $admin data reset"
    Remote 'lab@10.0.1.27' "sudo python3 $admin tracker start"
    $interval=if ($OnePeer) {'0.25'} else {'1'}
    $duration=$Seconds+8
    $client="sudo python3 /tmp/lease-probe-client.py $Name --rate $Rate --seconds $Seconds --block $Block$database"
    if ($OnePeer) {$client+=' --one-peer'}
    if ($Recovery) {$client+=' --expect-recovery'}
    $specs=@(
        @('host','root@10.0.1.4',"python3 /tmp/lease-probe-observer.py $Name --seconds $duration --interval $interval$database"),
        @('data','lab@10.0.1.26',"sudo python3 /tmp/lease-probe-observer.py $Name --seconds $duration --interval $interval$database"),
        @('client','lab@10.0.1.25',$client)
    )
    foreach ($spec in $specs) {
        $jobs+=Start-Job -Name $spec[0] -ArgumentList $IdentityFile,$spec[1],$spec[2],"$dir/$Name-$($spec[0]).json" -ScriptBlock {
            param($key,$endpoint,$command,$file)
            & ssh -o BatchMode=yes -o ConnectTimeout=8 -i $key $endpoint $command | Set-Content -Encoding utf8 $file
            $LASTEXITCODE
        }
    }
    while (@($jobs | Where-Object State -in @('Running','NotStarted')).Count) {
        Wait-Job -Job @($jobs | Where-Object State -in @('Running','NotStarted')) -Timeout 10 | Out-Null
        $bad=@($jobs | Where-Object State -eq 'Failed')
        if ($bad.Count) {throw 'Observador ou carga falhou'}
    }
    foreach ($job in $jobs) {
        if ((Receive-Job $job) -ne 0) {throw "Falha em $($job.Name)"}
    }
} finally {
    foreach ($job in $jobs) {if ($job.State -in @('Running','NotStarted')) {Stop-Job $job};Remove-Job $job -Force}
    Remote 'lab@10.0.1.27' "sudo python3 $admin tracker stop"
    Remote 'lab@10.0.1.26' "sudo python3 $admin data status"
}
$result=Get-Content -Raw "$dir/$Name-client.json" | ConvertFrom-Json
$result | Select-Object name,accepted,errors,drained,unpersisted_versions,expected_credit | ConvertTo-Json -Compress
