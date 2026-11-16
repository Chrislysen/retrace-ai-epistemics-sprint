param([ValidateRange(1024, 65535)][int]$Port = 8769)
$ErrorActionPreference = 'Stop'
$retraceRoot = $PSScriptRoot
Push-Location -LiteralPath $retraceRoot
try {
    $retracePython = Get-Command python -ErrorAction Stop
    Write-Host "RETRACE local workbench: http://127.0.0.1:$Port (Ctrl+C to stop)"
    & $retracePython.Source -B -S -m retrace.server_v6h --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Python exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
