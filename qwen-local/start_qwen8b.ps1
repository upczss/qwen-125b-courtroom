param(
    [string]$PythonExecutable = 'D:\Anaconda\envs\qwen-local-new\python.exe',
    [switch]$Background
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:QWEN_MODEL_PATH = Join-Path $PSScriptRoot 'models\Qwen3-8B'
$env:QWEN_QUANTIZATION = 'int8'
$portProbe = New-Object System.Net.Sockets.TcpClient
try {
    $portProbe.Connect('127.0.0.1', 8000)
    Write-Output 'Port 8000 is already in use. Open http://127.0.0.1:8000 or stop the existing server first.'
    return
} catch [System.Net.Sockets.SocketException] {
    # No listener: continue with startup.
} finally {
    $portProbe.Dispose()
}
if ($Background) {
    $logDirectory = Join-Path $PSScriptRoot 'logs'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $server = Start-Process -FilePath $PythonExecutable -ArgumentList '-u', 'serve_qwen8b.py' `
        -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDirectory 'qwen8b.stdout.log') `
        -RedirectStandardError (Join-Path $logDirectory 'qwen8b.stderr.log')
    $server.Id | Set-Content -LiteralPath (Join-Path $logDirectory 'qwen8b.pid')
    Write-Output "Qwen3-8B process started: $($server.Id)"
} else {
    & $PythonExecutable serve_qwen8b.py
}
