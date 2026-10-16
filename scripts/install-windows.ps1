param(
    [switch]$TestDependencies,
    [switch]$Uninstall
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($TestDependencies -and $Uninstall) {
    throw 'The -TestDependencies and -Uninstall options cannot be combined.'
}
$repoDirectory = Split-Path -Parent $PSScriptRoot
$venvDirectory = Join-Path $repoDirectory '.venv'
$runtimeExecutable = Join-Path $venvDirectory 'Scripts\python.exe'
$installedExecutable = Join-Path $venvDirectory 'Scripts\isycode.exe'

if ($Uninstall) {
    if (-not (Test-Path -LiteralPath $runtimeExecutable)) {
        Write-Output 'ISyCode is not installed in this checkout virtual environment.'
        return
    }
    & $runtimeExecutable -m pip --disable-pip-version-check uninstall -y isycode
    if ($LASTEXITCODE -ne 0) { throw 'Uninstalling ISyCode failed.' }
    if (Test-Path -LiteralPath $installedExecutable) {
        throw 'Uninstall left the isycode launcher behind.'
    }
    & $runtimeExecutable -c "import importlib.metadata as m, sys; sys.exit(1 if any((d.metadata.get('Name') or '').lower() == 'isycode' for d in m.distributions()) else 0)"
    if ($LASTEXITCODE -ne 0) {
        throw 'Uninstall left ISyCode distribution metadata behind.'
    }
    Write-Output ('Removed ISyCode from "' + $venvDirectory + '". The virtual environment and its dependencies were retained.')
    return
}

if (-not (Test-Path -LiteralPath (Join-Path $venvDirectory 'Scripts\python.exe'))) {
    & py -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Creating the virtual environment failed.' }
}
$packageTarget = if ($TestDependencies) { "$repoDirectory[test]" } else { $repoDirectory }
& $runtimeExecutable -m pip --disable-pip-version-check install -e $packageTarget
if ($LASTEXITCODE -ne 0) { throw 'Installing ISyCode failed.' }
& $installedExecutable --version
if ($LASTEXITCODE -ne 0) { throw 'Installed command verification failed.' }
Write-Output ('Start ISyCode with: & "' + $installedExecutable + '"')
