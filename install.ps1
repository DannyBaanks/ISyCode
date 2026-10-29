# ISyCode — Universal Installer for Windows (PowerShell)
# Usage:
#   irm https://raw.githubusercontent.com/DannyBaanks/ISyCode/main/install.ps1 | iex
#   .\install.ps1 [-Dir <Path>] [-Branch <Name>] [-WithTest] [-Upgrade] [-Uninstall] [-Help]

[CmdletBinding()]
param(
    [string]$Dir = "",
    [string]$Branch = "main",
    [string]$RepoUrl = "https://github.com/DannyBaanks/ISyCode.git",
    [switch]$WithTest,
    [switch]$Upgrade,
    [switch]$Uninstall,
    [switch]$NoModifyPath,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Info([string]$Message) {
    Write-Host "→ " -ForegroundColor Cyan -NoNewline
    Write-Host $Message
}

function Write-Success([string]$Message) {
    Write-Host "✓ " -ForegroundColor Green -NoNewline
    Write-Host $Message
}

function Write-Warn([string]$Message) {
    Write-Host "⚠ " -ForegroundColor Yellow -NoNewline
    Write-Host $Message
}

function Write-Err([string]$Message) {
    Write-Host "✗ " -ForegroundColor Red -NoNewline
    Write-Host $Message
}

if ($Help) {
    Write-Host "ISyCode — Instalador para Windows (PowerShell)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Uso:"
    Write-Host "  irm https://raw.githubusercontent.com/DannyBaanks/ISyCode/main/install.ps1 | iex"
    Write-Host "  .\install.ps1 [opciones]"
    Write-Host ""
    Write-Host "Opciones:"
    Write-Host "  -Dir <Ruta>        Directorio de instalación (por defecto: ~\.isycode o repo actual)"
    Write-Host "  -Branch <Rama>     Rama de Git a clonar (por defecto: main)"
    Write-Host "  -RepoUrl <Url>     URL del repositorio Git"
    Write-Host "  -WithTest          Instalar dependencias de pruebas ([test])"
    Write-Host "  -Upgrade           Actualizar dependencias si ya está instalado"
    Write-Host "  -NoModifyPath      No sugerir ni modificar la variable PATH del usuario"
    Write-Host "  -Uninstall         Eliminar ISyCode de este equipo"
    Write-Host "  -Help              Mostrar esta ayuda"
    return
}

# Determine default target directory
$detectedRepo = $null
if (Test-Path -LiteralPath ".\pyproject.toml") {
    $content = Get-Content -LiteralPath ".\pyproject.toml" -Raw -ErrorAction SilentlyContinue
    if ($content -match 'name\s*=\s*"isycode"' -and (Test-Path -LiteralPath ".\.git")) {
        $detectedRepo = (Get-Item -LiteralPath ".").FullName
    }
}

$targetDir = $Dir
if (-not $targetDir) {
    if ($env:ISYCODE_DIR) {
        $targetDir = $env:ISYCODE_DIR
    } elseif ($detectedRepo) {
        $targetDir = $detectedRepo
    } else {
        $targetDir = Join-Path $env:USERPROFILE ".isycode"
    }
}

# Uninstall workflow
if ($Uninstall) {
    Write-Info "Desinstalando ISyCode..."
    $venvScripts = Join-Path $targetDir ".venv\Scripts"
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -like "*$venvScripts*") {
        $newPath = (($userPath -split ';') | Where-Object { $_ -ne $venvScripts -and $_ -ne "" }) -join ';'
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Success "Se removió $venvScripts del PATH de usuario."
    }
    Write-Success "Desinstalación lista. Si deseas borrar archivos de código y entornos:"
    Write-Host "  Remove-Item -Recurse -Force '$targetDir'"
    return
}

Write-Host "⚡ ISyCode Windows Installer" -ForegroundColor Cyan
Write-Host ""

# 1. Check Git
Write-Info "Comprobando Git..."
$gitCmd = Get-Command "git" -ErrorAction SilentlyContinue
if (-not $gitCmd) {
    Write-Err "Git no se encuentra en el PATH."
    throw "Instala Git for Windows desde https://git-scm.com/ e inténtalo de nuevo."
}
$gitVersion = (& git --version)
Write-Success "Git detectado: $gitVersion"

# 2. Check Python >= 3.10
Write-Info "Comprobando versión de Python (>= 3.10)..."
$pythonCandidates = @("py", "python")
$systemPython = $null

foreach ($cand in $pythonCandidates) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) {
        $testArgs = if ($cand -eq "py") { @("-3", "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)") } else { @("-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)") }
        & $cand $testArgs
        if ($LASTEXITCODE -eq 0) {
            $systemPython = $cand
            break
        }
    }
}

if (-not $systemPython) {
    Write-Err "Se requiere Python 3.10 o superior y no se encontró en el PATH."
    throw "Descarga e instala Python 3.10+ desde https://www.python.org/downloads/ asegurándote de marcar 'Add Python to PATH'."
}

$pyVerArgs = if ($systemPython -eq "py") { @("-3", "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')") } else { @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')") }
$pyVersion = (& $systemPython $pyVerArgs)
Write-Success "Python $pyVersion detectado ($systemPython)"

# 3. Prepare target directory
if ($detectedRepo -and $targetDir -eq $detectedRepo) {
    Write-Success "Usando repositorio local: $targetDir"
} else {
    if (-not (Test-Path -LiteralPath $targetDir)) {
        Write-Info "Clonando ISyCode en $targetDir (rama: $Branch)..."
        & git clone --depth 1 -b $Branch $RepoUrl $targetDir
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo clonar el repositorio de ISyCode."
        }
        Write-Success "Repositorio clonado correctamente"
    } elseif (Test-Path -LiteralPath (Join-Path $targetDir ".git")) {
        Write-Success "Repositorio existente detectado en $targetDir"
        if ($Upgrade) {
            Write-Info "Actualizando código desde origen..."
            Push-Location $targetDir
            try {
                & git pull --ff-only origin $Branch
            } finally {
                Pop-Location
            }
        }
    } else {
        throw "El directorio destino $targetDir ya existe pero no es un repositorio Git válido."
    }
}

# 4. Setup .venv
$venvDir = Join-Path $targetDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvIsycode = Join-Path $venvDir "Scripts\isycode.exe"

Write-Info "Configurando entorno virtual aislado (.venv)..."
if (-not (Test-Path -LiteralPath $venvPython)) {
    $venvCreateArgs = if ($systemPython -eq "py") { @("-3", "-m", "venv", $venvDir) } else { @("-m", "venv", $venvDir) }
    & $systemPython $venvCreateArgs
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo crear el entorno virtual en $venvDir"
    }
}

$pkgSpec = if ($WithTest) { "$targetDir[test]" } else { $targetDir }
Write-Info "Instalando dependencias de ISyCode (esto puede tardar unos segundos)..."
& $venvPython -m pip install --upgrade --disable-pip-version-check --quiet -e $pkgSpec
if ($LASTEXITCODE -ne 0) {
    throw "Falló la instalación de dependencias con pip."
}
Write-Success "Entorno virtual y dependencias listas"

# 5. Verify installation
Write-Info "Verificando comando isycode..."
if (-not (Test-Path -LiteralPath $venvIsycode)) {
    throw "No se encontró el ejecutable $venvIsycode tras la instalación."
}
$isyVer = (& $venvPython -c "import isycode; print(getattr(isycode, '__version__', '1.0.0'))")
Write-Success "ISyCode v$isyVer listo para usarse"

# 6. Check PATH
$scriptsDir = Join-Path $venvDir "Scripts"
$currentUserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$inPath = ($env:PATH -split ';') -contains $scriptsDir

if (-not $inPath -and -not $NoModifyPath) {
    Write-Warn "$scriptsDir no está actualmente en tu variable PATH."
    Write-Host "  ¿Deseas agregar $scriptsDir a tu variable PATH de usuario automáticamente? (S/n): " -ForegroundColor Yellow -NoNewline
    $answer = Read-Host
    if ($answer -ne "n" -and $answer -ne "N") {
        $updatedPath = if ($currentUserPath) { "$currentUserPath;$scriptsDir" } else { $scriptsDir }
        [Environment]::SetEnvironmentVariable("Path", $updatedPath, "User")
        $env:PATH = "$env:PATH;$scriptsDir"
        Write-Success "Se agregó al PATH de usuario. Los cambios tendrán efecto en tus nuevas terminales."
        $inPath = $true
    } else {
        Write-Host "  Para ejecutar 'isycode' sin la ruta completa, agrega esta carpeta a tu PATH manualmente:"
        Write-Host "    $scriptsDir" -ForegroundColor Cyan
    }
}

# 7. Summary
Write-Host ""
Write-Host "✨ ¡ISyCode se ha instalado correctamente en Windows!" -ForegroundColor Green
Write-Host ""
Write-Host "Para iniciar el agente:"
if ($inPath) {
    Write-Host "  isycode" -ForegroundColor Cyan
} else {
    Write-Host "  & `"$venvIsycode`"" -ForegroundColor Cyan
}
Write-Host ""
Write-Host "Para mantenerlo actualizado en el futuro:"
Write-Host "  isycode actualizar" -ForegroundColor Yellow
Write-Host ""
