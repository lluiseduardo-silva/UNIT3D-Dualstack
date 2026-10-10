param([Parameter(Mandatory)][string]$Name,[Parameter(Mandatory)][string]$IdentityFile)
$ErrorActionPreference='Stop'
if($Name -notmatch '^[a-z0-9-]+$'){throw 'Nome invalido'}
$root=Join-Path $PSScriptRoot 'results/soak'
& ssh -i $IdentityFile root@10.0.1.4 "python3 /root/unit3d-soak/export-soak.py $Name"
if($LASTEXITCODE -ne 0){throw 'Exportacao falhou'}
$local=Join-Path $root "$Name-public.tar.gz"
& scp -i $IdentityFile "root@10.0.1.4:/tmp/$Name-public.tar.gz" $local
if($LASTEXITCODE -ne 0){throw 'Download falhou'}
& tar -xzf $local -C $root
if($LASTEXITCODE -ne 0){throw 'Extracao falhou'}
# Keep the individual evidence files, not a second copy of the archive in Git.
Remove-Item -LiteralPath $local
