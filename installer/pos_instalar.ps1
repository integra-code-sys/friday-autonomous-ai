param([string]$Destino = (Split-Path -Parent $MyInvocation.MyCommand.Path))
$ErrorActionPreference = "Continue"
Set-Location $Destino
New-Item -ItemType Directory -Force -Path (Join-Path $env:LOCALAPPDATA "Friday") | Out-Null
$log = Join-Path $env:LOCALAPPDATA "Friday\instalacao.log"
function Log($m) { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format s), $m) }

$py = $null
foreach ($c in @("py -3", "python")) {
    try {
        $v = & cmd /c "$c -c ""import sys; print(sys.executable)"""
        if ($LASTEXITCODE -eq 0 -and $v) { $py = $c; break }
    } catch {}
}
if (-not $py) {
    Log "Python ausente. Tentando winget."
    winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    $py = "py -3"
}
Log "python=$py"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & cmd /c "$py -m venv .venv"
}
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
if (Test-Path "requirements-win.txt") {
    & ".\.venv\Scripts\python.exe" -m pip install -r requirements-win.txt
}
Log "venv pronto"
if (-not (Test-Path "memory")) { New-Item -ItemType Directory -Path "memory" | Out-Null }
Write-Host "Backend preparado em $Destino. Atalho: Area de Trabalho \ F.R.I.D.A.Y."
Write-Host "Log: $log"
