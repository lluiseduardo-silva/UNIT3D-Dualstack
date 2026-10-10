param(
    [Parameter(Mandatory)][string]$IdentityFile,
    [ValidateSet(1000,54000,100000)][int[]]$Populations=@(1000,54000,100000),
    [ValidateSet('distributed','concentrated')][string[]]$Layouts=@('distributed','concentrated'),
    [ValidateRange(1,99)][int]$Revision=1
)
$ErrorActionPreference='Stop'
$base='/opt/unit3d-dualstack'
$dir=Join-Path $PSScriptRoot 'results/bootstrap'
$plans=Join-Path $PSScriptRoot 'plans'
foreach($population in $Populations){
    foreach($layout in $Layouts){
        $label="bootstrap-$population-$layout-v$Revision"
        $log=Join-Path $dir "$label.txt"
        if(Test-Path -LiteralPath $log){throw "Resultado existente: $label"}
        $sizes=if($layout -eq 'distributed'){@(1..($population/250) | ForEach-Object {250})}else{@($population)}
        $plan=Join-Path $plans "$label.json"
        @{name=$label;sizes=@($sizes);phases=@()} | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 $plan
        & ssh -i $IdentityFile -o BatchMode=yes lab@10.0.1.26 'test "$(df -B1 --output=avail / | tail -1)" -gt 3221225472'
        if($LASTEXITCODE -ne 0){throw 'Menos de 3 GiB livres nos dados'}
        & scp -i $IdentityFile $plan "lab@10.0.1.25:/tmp/$label.json"
        if($LASTEXITCODE -ne 0){throw 'Falha copiando plano'}
        & ssh -i $IdentityFile -o BatchMode=yes lab@10.0.1.27 "test -z `"`$(sudo docker ps -q)`" && sudo docker run --rm --network host -e DB_DATABASE=unit3d_dualstack_journal_test -v ${base}/repos/UNIT3D:/app -v ${base}/lab:/lab:ro unit3d-ds-php:baseline php /lab/initialize-journal-test.php" > $log 2>&1
        if($LASTEXITCODE -ne 0){throw 'Falha preparando banco'}
        & ssh -i $IdentityFile -o BatchMode=yes lab@10.0.1.25 "sudo install -m 644 /tmp/$label.json $base/$label.json && sudo python3 $base/density-fixture.py --skip-analyze $label.json" >> $log 2>&1
        if($LASTEXITCODE -ne 0){throw 'Falha criando fixture'}
        Write-Output "Medindo $label"
        & ssh -i $IdentityFile -o BatchMode=yes lab@10.0.1.27 "sudo bash $base/lab/run-bootstrap-scale.sh" >> $log 2>&1
        if($LASTEXITCODE -ne 0){throw "Falha no ensaio $label"}
        $row=Get-Content $log | Where-Object {$_ -like 'BOOTSTRAP_SCALE_JSON *'}
        if(@($row).Count -ne 1){throw 'Resultado ausente'}
        $report=$row.Substring('BOOTSTRAP_SCALE_JSON '.Length) | ConvertFrom-Json
        $report | ConvertTo-Json -Depth 60 | Set-Content -Encoding utf8 (Join-Path $dir "$label.json")
        $report | Select-Object peers,torrents,opens | ConvertTo-Json -Depth 5 -Compress | Write-Output
    }
}
