param(
    [Parameter(Mandatory)][string]$PlanFile,
    [Parameter(Mandatory)][string]$IdentityFile
)
$ErrorActionPreference='Stop'
$plan=Get-Content -Raw -LiteralPath $PlanFile | ConvertFrom-Json
$name=$plan.name
if($name -notmatch '^[a-z0-9-]+$'){throw 'Nome invalido'}
$base='/opt/unit3d-dualstack'
function Remote([string]$Target,[string]$Command){
    & ssh -i $IdentityFile -o BatchMode=yes -o ConnectTimeout=10 $Target $Command
    if($LASTEXITCODE -ne 0){throw "Falha remota: $Target"}
}
function Upload([string]$Target,[string[]]$Files){
    & scp -i $IdentityFile @Files "${Target}:/tmp/"
    if($LASTEXITCODE -ne 0){throw "Upload falhou: $Target"}
}
foreach($hostName in @('lab@10.0.1.25','lab@10.0.1.26','lab@10.0.1.27')){
    Remote $hostName "sudo python3 $base/lab/archive-preflight.py"
    Upload $hostName @($PlanFile)
    Remote $hostName "sudo mkdir -p $base/soak && sudo install -m 600 /tmp/$name.json $base/soak/$name.json"
}
$files=@(Get-ChildItem "$PSScriptRoot/soak*.py" | ForEach-Object FullName)
if($null -ne $plan.comparison_variant){$files+=@("$PSScriptRoot/rust-comparison-load.py","$PSScriptRoot/rust-comparison-fixture.py")}
Upload 'lab@10.0.1.25' $files
Remote 'lab@10.0.1.25' "sudo install -m 700 /tmp/soak*.py $base/lab/"
if($null -ne $plan.comparison_variant){Remote 'lab@10.0.1.25' "sudo install -m 700 /tmp/rust-comparison-load.py /tmp/rust-comparison-fixture.py $base/lab/"}
Upload 'lab@10.0.1.26' @("$PSScriptRoot/soak-observer.py","$PSScriptRoot/soak_guard.py","$PSScriptRoot/soak-stop-unit.py","$PSScriptRoot/soak-copy-probe.py")
Remote 'lab@10.0.1.26' "sudo install -m 700 /tmp/soak-observer.py /tmp/soak_guard.py /tmp/soak-stop-unit.py /tmp/soak-copy-probe.py $base/lab/"
if($null -ne $plan.copy_modes){Remote 'lab@10.0.1.26' "sudo python3 $base/lab/soak-copy-probe.py prepare"}
Upload 'lab@10.0.1.27' @("$PSScriptRoot/soak-backend.py","$PSScriptRoot/soak-observer.py","$PSScriptRoot/soak_guard.py","$PSScriptRoot/bootstrap-source.py","$PSScriptRoot/soak-stop-unit.py")
Remote 'lab@10.0.1.27' "sudo install -m 700 /tmp/soak-backend.py /tmp/soak-observer.py /tmp/soak_guard.py /tmp/bootstrap-source.py /tmp/soak-stop-unit.py $base/lab/"
Upload 'root@10.0.1.4' @("$PSScriptRoot/soak-supervisor.py","$PSScriptRoot/soak_guard.py","$PSScriptRoot/soak_diagnostics.py",$PlanFile)
Remote 'root@10.0.1.4' "test ! -e /storage_pool/unit3d-dualstack/supervisor/$name && mkdir -p -m 700 /root/unit3d-soak && install -m 700 /tmp/soak-supervisor.py /tmp/soak_guard.py /tmp/soak_diagnostics.py /root/unit3d-soak/ && install -m 600 /tmp/$name.json /root/unit3d-soak/$name.json"
Remote 'lab@10.0.1.27' 'test -z "$(sudo docker ps -q)" && ! sudo docker inspect unit3d-ds-rust >/dev/null 2>&1'
Remote 'lab@10.0.1.27' "sudo docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test -v ${base}/repos/UNIT3D:/app -v ${base}/lab:/lab:ro unit3d-ds-php:baseline php /lab/initialize-journal-test.php"
Remote 'lab@10.0.1.25' "sudo install -m 600 $base/soak/$name.json $base/$name.json && sudo python3 $base/density-fixture.py $name.json"
if($null -ne $plan.comparison_variant){Remote 'lab@10.0.1.25' "sudo python3 $base/lab/rust-comparison-fixture.py $name"}
Remote 'lab@10.0.1.25' "sudo python3 $base/lab/soak-setup-client.py add"
Remote 'lab@10.0.1.27' "sudo python3 $base/lab/soak-backend.py $base/soak/$name.json"
Remote 'lab@10.0.1.25' "python3 $base/benchmark-readiness.py"
if($plan.comparison_variant -eq 'original'){
    Upload 'lab@10.0.1.27' @("$PSScriptRoot/rust-comparison-provenance.py")
    Remote 'lab@10.0.1.27' "sudo install -m 700 /tmp/rust-comparison-provenance.py $base/lab/ && sudo python3 $base/lab/rust-comparison-provenance.py $name"
}
$max=[int]$plan.seconds+600
Remote 'root@10.0.1.4' "systemd-run --quiet --unit=unit3d-soak-supervisor-$name --property=RuntimeMaxSec=$max --property=TimeoutStopSec=300 python3 /root/unit3d-soak/soak-supervisor.py /root/unit3d-soak/$name.json"
Write-Output "Supervisor iniciado: $name"
