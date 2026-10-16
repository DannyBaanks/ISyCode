param([switch]$TestDependencies)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoDirectory = Split-Path -Parent $PSScriptRoot
$venvDirectory = Join-Path $repoDirectory '.venv'
if (-not (Test-Path -LiteralPath (Join-Path $venvDirectory 'Scripts\python.exe'))) {
    & py -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Creating the virtual environment failed.' }
}
$runtimeExecutable = Join-Path $venvDirectory 'Scripts\python.exe'
$packageTarget = if ($TestDependencies) { "$repoDirectory[test]" } else { $repoDirectory }
& $runtimeExecutable -m pip --disable-pip-version-check install -e $packageTarget
if ($LASTEXITCODE -ne 0) { throw 'Installing ISyCode failed.' }
$installedExecutable = Join-Path $venvDirectory 'Scripts\isycode.exe'
& $installedExecutable --version
if ($LASTEXITCODE -ne 0) { throw 'Installed command verification failed.' }
Write-Output ('Start ISyCode with: & "' + $installedExecutable + '"')
