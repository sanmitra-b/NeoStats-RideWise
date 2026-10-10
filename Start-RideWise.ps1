$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = 'C:\Users\sancr\anaconda3\envs\Ecothon\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = 'python' }
& $taskPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000
