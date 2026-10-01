param([string]$Python = 'py')
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$taskVenv = Join-Path $taskRoot '.venv'
$taskPythonArgs = if ([IO.Path]::GetFileNameWithoutExtension($Python) -eq 'py') { @('-3') } else { @() }
& $Python @taskPythonArgs -m venv $taskVenv
if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed. Install Python 3.10+ x64 or pass -Python with its executable path.' }
$taskVenvPython = Join-Path $taskVenv 'Scripts/python.exe'
& $taskVenvPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Windows capture dependency installation failed' }
Push-Location $taskRoot
try {
    & bun install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw 'Bun dependency installation failed' }
    & bun run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Type check failed' }
} finally { Pop-Location }
Write-Output 'Windows backend ready. Run bun src/index.ts, or register that command as a stdio MCP server.'
