param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& $Python -m PyInstaller --noconfirm --onefile --windowed --name SaveSales --collect-all customtkinter --distpath (Join-Path $projectDir 'dist') --workpath (Join-Path $projectDir 'build') --specpath (Join-Path $projectDir 'build') (Join-Path $projectDir 'main.py')
if ($LASTEXITCODE -ne 0) { throw 'SaveSales build failed' }
Write-Output ('Built ' + (Join-Path $projectDir 'dist\SaveSales.exe'))
