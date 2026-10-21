#!/usr/bin/env bash
# ISyCode — Universal Installer for Linux and macOS
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/DannyBaanks/ISyCode/main/install.sh | bash
#   ./install.sh [options]

set -euo pipefail

# ANSI Color & Formatting
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RESET=$'\033[0m'
    C_BOLD=$'\033[1m'
    C_DIM=$'\033[2m'
    C_CYAN=$'\033[1;36m'
    C_GREEN=$'\033[1;32m'
    C_YELLOW=$'\033[1;33m'
    C_RED=$'\033[1;31m'
    C_MAGENTA=$'\033[1;35m'
else
    C_RESET=""
    C_BOLD=""
    C_DIM=""
    C_CYAN=""
    C_GREEN=""
    C_YELLOW=""
    C_RED=""
    C_MAGENTA=""
fi

log_info() {
    printf "%s→%s %s\n" "$C_CYAN" "$C_RESET" "$1"
}

log_success() {
    printf "%s✓%s %s\n" "$C_GREEN" "$C_RESET" "$1"
}

log_warn() {
    printf "%s⚠%s %s\n" "$C_YELLOW" "$C_RESET" "$1"
}

log_error() {
    printf "%s✗%s %s\n" "$C_RED" "$C_RESET" "$1" >&2
}

die() {
    log_error "$1"
    exit "${2:-1}"
}

show_help() {
    cat <<EOF
${C_BOLD}ISyCode — Instalador Universal${C_RESET}

${C_BOLD}Uso:${C_RESET}
  curl -fsSL https://raw.githubusercontent.com/DannyBaanks/ISyCode/main/install.sh | bash
  ./install.sh [opciones]

${C_BOLD}Opciones:${C_RESET}
  -d, --dir <RUTA>       Directorio de instalación (por defecto: ~/.isycode o el repo actual)
  -b, --branch <RAMA>    Rama de git a clonar (por defecto: main)
  --bin-dir <RUTA>       Directorio para el enlace ejecutable (por defecto: ~/.local/bin)
  --repo-url <URL>       URL del repositorio Git (por defecto: repositorio oficial de GitHub)
  --with-test            Instalar dependencias adicionales de pruebas ([test])
  --upgrade, -u          Actualizar dependencias si la instalación ya existe
  --no-modify-path       No emitir sugerencias para actualizar archivos de perfil de shell
  --uninstall            Desinstalar el enlace ejecutable de ISyCode
  -h, --help             Mostrar esta ayuda y salir

${C_BOLD}Variables de entorno opcionales:${C_RESET}
  ISYCODE_DIR            Ruta personalizada del directorio de instalación
  ISYCODE_BIN_DIR        Ruta personalizada para el enlace ejecutable
  ISYCODE_BRANCH         Rama de git a utilizar
  ISYCODE_REPO_URL       URL alternativa del repositorio Git
  ISYCODE_PYTHON         Ruta específica del intérprete de Python a usar
EOF
}

# Configuration Defaults
REPO_URL="${ISYCODE_REPO_URL:-https://github.com/DannyBaanks/ISyCode.git}"
BRANCH="${ISYCODE_BRANCH:-main}"
INSTALL_DIR="${ISYCODE_DIR:-}"
BIN_DIR="${ISYCODE_BIN_DIR:-$HOME/.local/bin}"
NO_MODIFY_PATH=false
UPGRADE=false
WITH_TEST=false
UNINSTALL=false

# Parse CLI arguments
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        -d|--dir)
            [ $# -ge 2 ] || die "La opción $1 requiere un argumento de ruta."
            INSTALL_DIR="$2"
            shift 2
            ;;
        -b|--branch)
            [ $# -ge 2 ] || die "La opción $1 requiere el nombre de una rama."
            BRANCH="$2"
            shift 2
            ;;
        --bin-dir)
            [ $# -ge 2 ] || die "La opción $1 requiere una ruta de directorio."
            BIN_DIR="$2"
            shift 2
            ;;
        --repo-url)
            [ $# -ge 2 ] || die "La opción $1 requiere una URL."
            REPO_URL="$2"
            shift 2
            ;;
        --with-test)
            WITH_TEST=true
            shift
            ;;
        -u|--upgrade)
            UPGRADE=true
            shift
            ;;
        --no-modify-path)
            NO_MODIFY_PATH=true
            shift
            ;;
        --uninstall)
            UNINSTALL=true
            shift
            ;;
        *)
            die "Opción no reconocida: $1. Consulta --help para ver las opciones disponibles."
            ;;
    esac
done

# Uninstall workflow
if [ "$UNINSTALL" = true ]; then
    log_info "Desinstalando ISyCode..."
    TARGET_CMD="$BIN_DIR/isycode"
    if [ -L "$TARGET_CMD" ] || [ -f "$TARGET_CMD" ]; then
        rm -f "$TARGET_CMD"
        log_success "Se eliminó el enlace ejecutable en $TARGET_CMD"
    else
        log_warn "No se encontró ningún enlace en $TARGET_CMD"
    fi
    printf "\n%sPara eliminar completamente los datos y entornos:%s\n" "$C_BOLD" "$C_RESET"
    printf "  rm -rf %s\n\n" "${INSTALL_DIR:-$HOME/.isycode}"
    exit 0
fi

# Detect if executed inside an existing ISyCode repository clone
DETECTED_REPO=""
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ "${BASH_SOURCE[0]}" != "bash" ] && [ "${BASH_SOURCE[0]}" != "sh" ]; then
    CANDIDATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
    if [ -n "$CANDIDATE_DIR" ] && [ -f "$CANDIDATE_DIR/pyproject.toml" ] && { [ -d "$CANDIDATE_DIR/.git" ] || [ -f "$CANDIDATE_DIR/.git" ]; }; then
        if grep -q 'name = "isycode"' "$CANDIDATE_DIR/pyproject.toml" 2>/dev/null; then
            DETECTED_REPO="$CANDIDATE_DIR"
        fi
    fi
fi
if [ -z "$DETECTED_REPO" ] && [ -f "$PWD/pyproject.toml" ] && { [ -d "$PWD/.git" ] || [ -f "$PWD/.git" ]; }; then
    if grep -q 'name = "isycode"' "$PWD/pyproject.toml" 2>/dev/null; then
        DETECTED_REPO="$PWD"
    fi
fi

if [ -n "$INSTALL_DIR" ]; then
    TARGET_DIR="$INSTALL_DIR"
elif [ -n "$DETECTED_REPO" ]; then
    TARGET_DIR="$DETECTED_REPO"
else
    TARGET_DIR="$HOME/.isycode"
fi

printf "%s%sISyCode Installer%s\n\n" "$C_BOLD$C_CYAN" "⚡ " "$C_RESET"

# 1. Check prerequisites: Git
log_info "Comprobando Git..."
if ! command -v git >/dev/null 2>&1; then
    die "Git no está instalado en tu sistema.\nInstálalo con el gestor de paquetes de tu distribución:\n  Ubuntu/Debian: sudo apt install git\n  macOS:         brew install git\n  Fedora:        sudo dnf install git"
fi
log_success "Git detectado ($(git --version | head -n1))"

# 2. Check prerequisites: Python >= 3.10
log_info "Comprobando versión de Python (>= 3.10)..."
PYTHON_BIN=""
if [ -n "${ISYCODE_PYTHON:-}" ] && [ -x "$ISYCODE_PYTHON" ]; then
    PYTHON_BIN="$ISYCODE_PYTHON"
else
    for candidate in python3 python3.12 python3.11 python3.10 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
                PYTHON_BIN="$(command -v "$candidate")"
                break
            fi
        fi
    done
fi

if [ -z "$PYTHON_BIN" ]; then
    die "Se requiere Python 3.10 o superior, pero no se encontró un intérprete compatible en tu PATH.\nInstala Python 3.10+ y vuelve a ejecutar este instalador."
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
log_success "Python $PY_VERSION detectado ($PYTHON_BIN)"

# Check for venv module
if ! "$PYTHON_BIN" -c 'import venv' >/dev/null 2>&1; then
    die "El módulo 'venv' de Python no está disponible en tu instalación.\nEn Ubuntu/Debian suele ser necesario instalar python3-venv:\n  sudo apt install python3-venv"
fi

# Detect uv for accelerated installation if available
HAS_UV=false
if command -v uv >/dev/null 2>&1; then
    HAS_UV=true
    log_success "Acelerador uv detectado ($(uv --version | head -n1))"
fi

# 3. Prepare target repository
if [ -n "$DETECTED_REPO" ] && [ "$TARGET_DIR" = "$DETECTED_REPO" ]; then
    log_success "Usando repositorio local: $TARGET_DIR"
else
    if [ ! -d "$TARGET_DIR" ]; then
        log_info "Clonando ISyCode en $TARGET_DIR (rama: $BRANCH)..."
        git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$TARGET_DIR" || die "No se pudo clonar el repositorio de ISyCode."
        log_success "Repositorio clonado correctamente"
    elif [ -d "$TARGET_DIR/.git" ] || [ -f "$TARGET_DIR/.git" ]; then
        log_success "Repositorio existente detectado en $TARGET_DIR"
        if [ "$UPGRADE" = true ]; then
            log_info "Actualizando repositorio local desde $BRANCH..."
            (cd "$TARGET_DIR" && git pull --ff-only origin "$BRANCH") || log_warn "No se pudo actualizar vía git pull; continuando con archivos locales."
        fi
    else
        die "El destino $TARGET_DIR ya existe pero no es un repositorio Git válido.\nMuévelo o especifica otra ruta con --dir."
    fi
fi

# 4. Setup isolated virtual environment (.venv)
VENV_DIR="$TARGET_DIR/.venv"
log_info "Configurando entorno virtual aislado (.venv)..."

PKG_SPEC="$TARGET_DIR"
if [ "$WITH_TEST" = true ]; then
    PKG_SPEC="$TARGET_DIR[test]"
fi

if [ "$HAS_UV" = true ]; then
    if [ ! -d "$VENV_DIR" ]; then
        # --seed installs pip inside the environment. Without it the environment
        # has no pip, and the updater cannot sync dependencies with it.
        uv venv "$VENV_DIR" --python "$PYTHON_BIN" --seed --quiet || "$PYTHON_BIN" -m venv "$VENV_DIR"
    fi
    log_info "Instalando dependencias de ISyCode con uv..."
    if ! VIRTUAL_ENV="$VENV_DIR" uv pip install -e "$PKG_SPEC" --quiet; then
        log_warn "uv pip falló; reintentando con pip estándar..."
        "$VENV_DIR/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
        "$VENV_DIR/bin/python" -m pip install --upgrade --disable-pip-version-check --quiet -e "$PKG_SPEC" || die "Error instalando dependencias con pip."
    fi
else
    if [ ! -d "$VENV_DIR" ]; then
        "$PYTHON_BIN" -m venv "$VENV_DIR" || die "No se pudo crear el entorno virtual en $VENV_DIR"
    fi
    log_info "Instalando dependencias de ISyCode con pip (esto puede tardar unos segundos)..."
    "$VENV_DIR/bin/python" -m pip install --upgrade --disable-pip-version-check --quiet -e "$PKG_SPEC" || die "Error al instalar las dependencias de ISyCode."
fi
log_success "Entorno virtual y dependencias listas"

# 5. Link executable launcher
log_info "Configurando acceso al comando en $BIN_DIR..."
mkdir -p "$BIN_DIR"

LAUNCHER="$TARGET_DIR/scripts/isycode"
chmod +x "$LAUNCHER" 2>/dev/null || true

# Use install-path helper if available, or direct symlink fallback
LINKED=false
if [ -x "$TARGET_DIR/scripts/install-path" ]; then
    if ISYCODE_BIN_DIR="$BIN_DIR" "$TARGET_DIR/scripts/install-path" --replace-owned >/dev/null 2>&1; then
        LINKED=true
    fi
fi

if [ "$LINKED" = false ]; then
    ln -sf "$LAUNCHER" "$BIN_DIR/isycode"
fi
log_success "Comando enlazado en: $BIN_DIR/isycode"

# 6. Verify installation
log_info "Verificando instalación..."
APP_VERSION=""
if [ -x "$TARGET_DIR/.venv/bin/python" ]; then
    APP_VERSION="$("$TARGET_DIR/.venv/bin/python" -c 'import isycode; print(getattr(isycode, "__version__", "1.0.0"))' 2>/dev/null || true)"
fi
[ -n "$APP_VERSION" ] || APP_VERSION="1.0.0"
log_success "ISyCode v$APP_VERSION listo para usarse"

# 7. Check PATH and advise user if necessary
IN_PATH=false
case ":${PATH:-}:" in
    *":$BIN_DIR:"*) IN_PATH=true ;;
    *) IN_PATH=false ;;
esac

if [ "$IN_PATH" = false ] && [ "$NO_MODIFY_PATH" = false ]; then
    SHELL_NAME="$(basename "${SHELL:-bash}")"
    PROFILE_FILE=""
    case "$SHELL_NAME" in
        zsh) PROFILE_FILE="$HOME/.zshrc" ;;
        bash)
            if [ -f "$HOME/.bashrc" ]; then
                PROFILE_FILE="$HOME/.bashrc"
            else
                PROFILE_FILE="$HOME/.bash_profile"
            fi
            ;;
        fish) PROFILE_FILE="$HOME/.config/fish/config.fish" ;;
        *) PROFILE_FILE="$HOME/.profile" ;;
    esac

    printf "\n"
    log_warn "$BIN_DIR no está actualmente en tu variable PATH."
    printf "  Para poder ejecutar %sisycode%s desde cualquier directorio, añade esto a %s%s%s:\n\n" "$C_BOLD" "$C_RESET" "$C_CYAN" "$PROFILE_FILE" "$C_RESET"
    printf "    %sexport PATH=\"%s:\$PATH\"%s\n\n" "$C_BOLD$C_CYAN" "$BIN_DIR" "$C_RESET"
    printf "  Y recarga tu terminal con: %ssource %s%s\n\n" "$C_BOLD" "$PROFILE_FILE" "$C_RESET"
fi

# 8. Done!
printf "\n%s✨ ¡ISyCode se ha instalado correctamente!%s\n\n" "$C_BOLD$C_GREEN" "$C_RESET"
printf "Para iniciar el agente:\n"
if [ "$IN_PATH" = true ]; then
    printf "  %s%sisycode%s\n\n" "$C_BOLD$C_CYAN" "" "$C_RESET"
else
    printf "  %s%s/isycode%s\n\n" "$C_BOLD$C_CYAN" "$BIN_DIR" "$C_RESET"
fi
printf "Para mantenerlo actualizado en cualquier momento:\n"
printf "  %sisycode actualizar%s\n\n" "$C_YELLOW" "$C_RESET"
