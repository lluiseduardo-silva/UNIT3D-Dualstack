param([Parameter(Mandatory)][string]$Series,[Parameter(Mandatory)][string]$IdentityFile)
$ErrorActionPreference='Stop'
if ($Series -notmatch '^[a-z0-9-]+$') {throw 'Série inválida'}
$IdentityFile=(Resolve-Path -LiteralPath $IdentityFile).Path
$capDir=Join-Path $PSScriptRoot "results/capacity/$Series"
New-Item -ItemType Directory -Force -Path $capDir | Out-Null
& scp -q -i $IdentityFile "$PSScriptRoot/export-capacity.py" 'root@10.0.1.4:/root/unit3d-soak/'
if ($LASTEXITCODE -ne 0) {throw 'Falha no envio do exportador'}
& ssh -i $IdentityFile -o BatchMode=yes -o ConnectTimeout=10 root@10.0.1.4 "python3 /root/unit3d-soak/export-capacity.py $Series"
if ($LASTEXITCODE -ne 0) {throw 'Falha na exportação'}
& scp -q -i $IdentityFile "root@10.0.1.4:/tmp/$Series-public.tar.gz" "$capDir/public.tar.gz"
if ($LASTEXITCODE -ne 0) {throw 'Falha na coleta'}
& tar -xzf "$capDir/public.tar.gz" -C $capDir
if ($LASTEXITCODE -ne 0) {throw 'Falha na extração'}
Write-Output "Resultados públicos: $capDir"
