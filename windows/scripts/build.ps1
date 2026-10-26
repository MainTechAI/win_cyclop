$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.12 is required." }
}
$python = Join-Path $PWD ".venv\Scripts\python.exe"
& $python -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
& $python scripts/check-winrt.py
if ($LASTEXITCODE -ne 0) { throw "Windows Runtime check failed." }
& $python -m PyInstaller --noconfirm --clean --windowed --onedir --name CyclopWindows --collect-submodules winrt --copy-metadata cyclop-windows scripts/launch.py
if ($LASTEXITCODE -ne 0) { throw "Build failed." }
Copy-Item ..\LICENSE dist\CyclopWindows\LICENSE.txt
Copy-Item THIRD_PARTY_NOTICES.md dist\CyclopWindows\THIRD_PARTY_NOTICES.md
& $python scripts/collect-licenses.py dist/CyclopWindows/licenses
& $python -m pip freeze | Out-File dist/CyclopWindows/BUILD-DEPENDENCIES.txt -Encoding utf8
Compress-Archive -Path dist\CyclopWindows -DestinationPath dist\CyclopWindows-win-x64.zip -Force
Write-Output "Build ready: windows\dist\CyclopWindows-win-x64.zip"
