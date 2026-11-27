"""Interactive and non-interactive setup wizard for ISyCode (``isycode setup``).

Inspired by Hermes Setup's sectioned wizard UX, tailored to ISyCode's own
architecture and integrations:
- Interface language (es / en / zh)
- Inference provider, model, optional slots (small / gus), and credentials
  (OS keyring vault, IsyMotron keys.env, environment variables + aliases,
  OAuth subscriptions like ChatGPT Codex & Google Antigravity, or local servers)
- Workspace identity (.isyroot with broad-directory guard) & Workspace Authority
- Local MCP servers (~/.config/isycode/mcp.json): official presets + ISyMCP Hub
- ISyCo Gateway (URL, Gateway MCP discovery, keyring token)
- Personal Telegram frontend (status & opt-in handoff to ``isycode telegram``)
- Agent defaults (steps, answer tokens, token budget, accessibility)

Security invariants:
- Never performs network calls during setup or status inspection.
- Never prints or logs secret values.
- Persists all state through ISyCode's existing private atomic stores.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TextIO

from isycode.agent_loop import AGENT_STEP_CHOICES, ANSWER_TOKEN_CHOICES
from isycode.config import (
    ConfigurationError,
    credential_state,
    discover_workspace_identity,
    key_store_path,
    provider_default_model,
    save_api_key,
)
from isycode.credentials import CredentialVault, CredentialVaultError, keyring_available
from isycode.diagnostics import collect_diagnostics
from isycode.gateway_mcp import _server_command as gateway_mcp_command
from isycode.mcp_local import (
    MAX_CONFIG_BYTES,
    MAX_SERVERS,
    config_path as mcp_config_path,
    load_config as load_mcp_config,
)
from isycode.mcp_presets import PRESETS as MCP_PRESETS, add_preset as add_mcp_preset
from isycode.platform_storage import storage
from isycode.providers import (
    DEFAULT_MODEL,
    KEY_NOTES,
    KEY_PAGES,
    PRESETS as PROVIDER_PRESETS,
    _preferences_path as provider_preferences_path,
    model_slot,
    provider_credential_state,
    provider_key_envs,
    resolved_chat_model,
    save_model_slot,
    save_provider_selection,
    selected_model_name,
    selected_provider_name,
)
from isycode.user_defaults import CHAT_TOKEN_BUDGET_CHOICES, UserDefaultsStore
from isycode.workspace_authority import WorkspaceAuthority, WorkspaceAuthorityError
from isycode.workspace_setup import (
    WorkspaceSetupStore,
    broad_workspace_reason,
    ensure_state_root,
    state_root,
)


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_CANCELLED = 130

_BRACKETED_PASTE_RE = re.compile(r"\x1b\[\s*200~|\x1b\[\s*201~")

# Ordered provider groups for the interactive picker.
FEATURED_PROVIDERS: tuple[str, ...] = (
    "nvidia",
    "chatgpt",
    "antigravity",
    "claude",
    "openai",
    "anthropic",
    "openrouter",
    "nebius",
)
LOCAL_PROVIDERS: tuple[str, ...] = (
    "ollama",
    "llamacpp",
    "lmstudio",
    "isyco-web",
)
OTHER_CLOUD_PROVIDERS: tuple[str, ...] = tuple(
    name for name in PROVIDER_PRESETS
    if name not in FEATURED_PROVIDERS and name not in LOCAL_PROVIDERS
)

OAUTH_PROVIDERS = frozenset({"chatgpt", "antigravity", "claude"})
WORKSPACE_MODES = ("classic", "flow", "security")
NEW_WORKSPACE_MODES = ("ask", "classic", "security")
NEW_WORKSPACE_CHOICES = ("ask", "temporary", "recurring")
LOCALE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("es", "Español (predeterminado)"),
    ("en", "English"),
    ("zh", "中文"),
)

SECTION_NAMES: tuple[str, ...] = (
    "language",
    "provider",
    "workspace",
    "mcp",
    "gateway",
    "telegram",
    "defaults",
)


class SetupCancelled(Exception):
    """Raised when the user cancels the interactive wizard (Ctrl+C / EOF)."""


@dataclass
class SetupIO:
    """Injectable I/O surface so interactive flows stay deterministic in tests."""

    out: TextIO = field(default_factory=lambda: sys.stdout)
    err: TextIO = field(default_factory=lambda: sys.stderr)
    input_fn: Callable[[str], str] = input
    secret_fn: Callable[[str], str] = getpass.getpass
    is_tty: bool | None = None
    use_color: bool | None = None

    def tty(self) -> bool:
        if self.is_tty is not None:
            return self.is_tty
        try:
            return bool(sys.stdin.isatty() and self.out.isatty())
        except Exception:
            return False

    def color_enabled(self) -> bool:
        if self.use_color is not None:
            return self.use_color
        if os.environ.get("NO_COLOR"):
            return False
        return self.tty()

    def style(self, text: str, code: str) -> str:
        if not self.color_enabled():
            return text
        return f"\033[{code}m{text}\033[0m"

    def write(self, text: str = "") -> None:
        self.out.write(f"{text}\n")

    def banner(self, title: str, subtitle: str | None = None) -> None:
        width = max(57, len(title) + 6, len(subtitle or "") + 6)
        top = "┌" + "─" * width + "┐"
        mid = "├" + "─" * width + "┤"
        bot = "└" + "─" * width + "┘"
        self.write()
        self.write(self.style(top, "1;35"))
        self.write(self.style(f"│  {title:<{width - 2}}│", "1;35"))
        if subtitle:
            self.write(self.style(mid, "35"))
            self.write(self.style(f"│  {subtitle:<{width - 2}}│", "0;37"))
        self.write(self.style(bot, "1;35"))
        self.write()

    def header(self, title: str) -> None:
        self.write()
        self.write(self.style(f"◆ {title}", "1;36"))

    def info(self, text: str) -> None:
        self.write(f"  {text}")

    def ok(self, text: str) -> None:
        self.write(f"  {self.style('✓', '1;32')} {text}")

    def warn(self, text: str) -> None:
        self.write(f"  {self.style('!', '1;33')} {text}")

    def error(self, text: str) -> None:
        self.err.write(f"{self.style('✗', '1;31')} {text}\n")

    def ask_text(self, prompt_text: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        rendered = self.style(f"  {prompt_text}{suffix}: ", "1;33")
        try:
            raw = self.input_fn(rendered)
        except (KeyboardInterrupt, EOFError) as exc:
            self.write()
            raise SetupCancelled() from exc
        cleaned = _BRACKETED_PASTE_RE.sub("", raw or "").strip()
        return cleaned if cleaned else default

    def ask_secret(self, prompt_text: str) -> str:
        rendered = self.style(f"  {prompt_text}: ", "1;33")
        try:
            raw = self.secret_fn(rendered)
        except (KeyboardInterrupt, EOFError) as exc:
            self.write()
            raise SetupCancelled() from exc
        return _BRACKETED_PASTE_RE.sub("", raw or "").strip()

    def ask_yes_no(self, prompt_text: str, *, default: bool = True) -> bool:
        hint = "S/n" if default else "s/N"
        rendered = self.style(f"  {prompt_text} [{hint}]: ", "1;33")
        while True:
            try:
                raw = self.input_fn(rendered)
            except (KeyboardInterrupt, EOFError) as exc:
                self.write()
                raise SetupCancelled() from exc
            value = _BRACKETED_PASTE_RE.sub("", raw or "").strip().casefold()
            if not value:
                return default
            if value in {"s", "si", "sí", "y", "yes"}:
                return True
            if value in {"n", "no"}:
                return False
            self.warn("Responde 's' (sí) o 'n' (no).")

    def ask_choice(
        self,
        title: str,
        options: list[tuple[str, str]],
        *,
        default_index: int = 0,
    ) -> int:
        self.info(title)
        for idx, (label, detail) in enumerate(options, start=1):
            marker = self.style("●", "1;36") if idx - 1 == default_index else " "
            suffix = f" — {self.style(detail, '2')}" if detail else ""
            self.write(f"    {marker} {idx}) {label}{suffix}")
        while True:
            raw = self.ask_text(f"Elige una opción (1-{len(options)})", str(default_index + 1))
            if raw.isdigit():
                chosen = int(raw) - 1
                if 0 <= chosen < len(options):
                    return chosen
            # Also allow typing the exact option key/label prefix.
            lowered = raw.casefold()
            for idx, (label, _) in enumerate(options):
                if label.casefold() == lowered:
                    return idx
            self.warn(f"Opción inválida: {raw!r}. Ingresa un número entre 1 y {len(options)}.")


def _detect_isymcp_hub() -> str | None:
    """Locate the local ISyMCP Hub binary if installed."""
    found = shutil.which("isymcp-hub")
    if found:
        return str(Path(found).expanduser().resolve())
    candidate = Path.home() / ".local" / "bin" / "isymcp-hub"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())
    return None


def _detect_telegram_status(profile: str = "personal") -> dict[str, Any]:
    """Read local personal Telegram profile metadata without touching secrets."""
    try:
        from isycode.telegram.cli import is_running
        from isycode.telegram.state import TelegramStore

        store = TelegramStore(profile)
        return {
            "profile": profile,
            "configured": bool(store.setting("peer")),
            "running": is_running(store),
            "revoked": bool(store.setting("revoked", False)),
            "workspaces": sorted(store.workspaces().keys()),
        }
    except Exception:
        return {
            "profile": profile,
            "configured": False,
            "running": False,
            "revoked": False,
            "workspaces": [],
        }


def _vault_has_service(service: str) -> bool:
    """Check whether the OS keyring metadata DB has an active key for ``service``."""
    try:
        vault = CredentialVault()
        return any(
            item["service"] == service.casefold() and not item["revoked"]
            for item in vault.list_metadata()
        )
    except (CredentialVaultError, OSError, ValueError):
        return False


def _save_provider_secret(
    provider: str,
    secret: str,
    *,
    storage_preference: str = "auto",
) -> tuple[str, str]:
    """Store a provider API key in OS keyring vault or keys.env (mode 0600).

    Returns ``(backend, detail)`` without ever returning the secret value.
    """
    preset = PROVIDER_PRESETS.get(provider.casefold())
    if preset is None:
        raise ConfigurationError(f"Proveedor desconocido: {provider}")
    if preset.get("key_required") is False:
        raise ConfigurationError(f"{provider} no requiere API key.")
    cleaned = secret.strip()
    if not cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ConfigurationError("La API key debe ser una sola línea no vacía.")

    if storage_preference in {"auto", "vault"}:
        try:
            vault = CredentialVault()
            key_id = vault.add(
                f"{preset['label']} (setup)",
                provider.casefold(),
                f"ISyCode setup ({provider.casefold()})",
                cleaned,
            )
            return ("vault", key_id)
        except (CredentialVaultError, OSError, ValueError) as exc:
            if storage_preference == "vault":
                raise ConfigurationError(
                    f"No se pudo guardar en el keyring del sistema: {exc}"
                ) from exc

    target = save_api_key(provider.casefold(), cleaned)
    return ("file", str(target))


def _save_gateway_secret(secret: str) -> tuple[str, str]:
    """Store ``isyco-gateway`` API key in the OS keyring vault."""
    cleaned = secret.strip()
    if not cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ConfigurationError("La clave de Gateway debe ser una sola línea no vacía.")
    vault = CredentialVault()
    key_id = vault.add("ISyCo Gateway (setup)", "isyco-gateway", "ISyCo Gateway MCP/HTTP", cleaned)
    return ("vault", key_id)


def _add_mcp_server(name: str, command: list[str], *, path: Path | None = None) -> Path:
    """Atomically register a local stdio MCP server in ``mcp.json`` (mode 0600)."""
    target = path or mcp_config_path()
    configs = load_mcp_config(target)
    if name in configs:
        return target
    if len(configs) >= MAX_SERVERS:
        raise ValueError("Se alcanzó el límite máximo de servidores MCP en mcp.json")
    servers = {
        key: {"command": list(value.argv), **({"env": dict(value.env)} if value.env else {})}
        for key, value in configs.items()
    }
    servers[name] = {"command": list(command)}
    payload = (json.dumps({"servers": servers}, indent=2) + "\n").encode("utf-8")
    if len(payload) > MAX_CONFIG_BYTES:
        raise ValueError("mcp.json excede el límite máximo permitido")
    if target.parent.is_symlink():
        raise ValueError("El directorio de configuración MCP no puede ser un symlink")
    if os.name == "nt":
        storage.ensure_directory(target.parent, repair=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".mcp-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            storage.protect(Path(temporary))
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        if not storage.private(target):
            raise ValueError("mcp.json no conservó permisos privados")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def _provider_status_badge(provider: str) -> str:
    """Human-readable credential/auth status for one provider (never prints secrets)."""
    if provider in OAUTH_PROVIDERS:
        return "OAuth suscripción (sin API key)"
    preset = PROVIDER_PRESETS[provider]
    if preset.get("key_required") is False:
        return "local / sin API key"
    state = provider_credential_state(provider)
    if state in {"environment", "session"}:
        return "API key en entorno"
    if _vault_has_service(provider):
        return "API key en OS keyring"
    if state in {"stored", "legacy"}:
        return "API key en keys.env"
    return "sin API key"


def _is_existing_install() -> bool:
    """True when the user already persisted provider or user defaults."""
    try:
        if provider_preferences_path().is_file():
            return True
    except (OSError, ValueError):
        pass
    try:
        if UserDefaultsStore().path.is_file():
            return True
    except (OSError, ValueError):
        pass
    return False


# ── Individual wizard sections (interactive) ─────────────────────────────────


def setup_language(io: SetupIO) -> dict[str, Any]:
    io.header("Idioma de interfaz")
    store = UserDefaultsStore()
    current = store.load().get("locale", UserDefaultsStore.DEFAULT_LOCALE)
    default_idx = next(
        (i for i, (code, _) in enumerate(LOCALE_OPTIONS) if code == current),
        0,
    )
    chosen = io.ask_choice(
        "Selecciona el idioma de ISyCode:",
        [(label, code) for code, label in LOCALE_OPTIONS],
        default_index=default_idx,
    )
    locale = LOCALE_OPTIONS[chosen][0]
    store.update(locale=locale)
    io.ok(f"Idioma guardado: {locale}")
    return {"locale": locale}


def setup_provider(io: SetupIO, *, configure_slots: bool = True) -> dict[str, Any]:
    io.header("Proveedor y modelo de inferencia")
    current_provider = selected_provider_name()
    current_model = selected_model_name() or resolved_chat_model(current_provider)

    ordered: list[str] = list(FEATURED_PROVIDERS) + list(LOCAL_PROVIDERS)
    options: list[tuple[str, str]] = []
    for name in ordered:
        preset = PROVIDER_PRESETS[name]
        options.append((f"{preset['label']} ({name})", _provider_status_badge(name)))
    options.append(("Otros proveedores cloud…", f"{len(OTHER_CLOUD_PROVIDERS)} disponibles"))

    default_idx = ordered.index(current_provider) if current_provider in ordered else 0
    idx = io.ask_choice(
        f"Proveedor actual: {current_provider} ({current_model}). Elige proveedor:",
        options,
        default_index=default_idx,
    )
    if idx == len(ordered):
        other_options = [
            (f"{PROVIDER_PRESETS[name]['label']} ({name})", _provider_status_badge(name))
            for name in OTHER_CLOUD_PROVIDERS
        ]
        other_default = (
            OTHER_CLOUD_PROVIDERS.index(current_provider)
            if current_provider in OTHER_CLOUD_PROVIDERS
            else 0
        )
        other_idx = io.ask_choice("Otros proveedores cloud:", other_options, default_index=other_default)
        provider = OTHER_CLOUD_PROVIDERS[other_idx]
    else:
        provider = ordered[idx]

    preset = PROVIDER_PRESETS[provider]
    suggested_model = (
        current_model
        if provider == current_provider and current_model
        else preset.get("default_model") or provider_default_model(provider) or DEFAULT_MODEL
    )
    model = io.ask_text(f"Modelo para {preset['label']}", suggested_model)
    save_provider_selection(provider, model)
    io.ok(f"Proveedor y modelo guardados: {provider} → {model}")

    cred_result: dict[str, Any] = {"provider": provider, "model": model, "credential": _provider_status_badge(provider)}

    if provider in OAUTH_PROVIDERS:
        io.info(f"{preset['label']} usa inicio de sesión OAuth nativo dentro de la TUI (sin API key manual).")
        io.info("Al abrir `isycode`, entra a `/providers` para completar el inicio de sesión.")
    elif preset.get("key_required") is False:
        io.info(f"{preset['label']} corre en {preset['base_url']} y no requiere API key.")
    else:
        env_names = provider_key_envs(provider)
        status = _provider_status_badge(provider)
        io.info(f"Estado actual de credencial: {status} (env: {', '.join(env_names)})")
        if provider in KEY_PAGES:
            io.info(f"Obtén tu clave en: {KEY_PAGES[provider]}")
        if provider in KEY_NOTES:
            io.info(f"Nota: {KEY_NOTES[provider]}")

        ask_key = status == "sin API key" or io.ask_yes_no(
            "¿Quieres guardar o reemplazar la API key ahora?",
            default=False,
        )
        if ask_key:
            secret = io.ask_secret(f"Pega tu API key para {preset['label']} (Enter para omitir)")
            if secret:
                storage_choice = "auto"
                if keyring_available():
                    store_idx = io.ask_choice(
                        "¿Dónde guardar la API key?",
                        [
                            ("OS Keyring (recomendado)", "Cifrado por el llavero del sistema"),
                            (f"Archivo privado ({key_store_path()})", "Permisos 0600 compatible con headless/CI"),
                        ],
                        default_index=0,
                    )
                    storage_choice = "vault" if store_idx == 0 else "file"
                else:
                    io.warn("OS Keyring no disponible; se usará el almacén privado keys.env (0600).")
                    storage_choice = "file"
                backend, detail = _save_provider_secret(provider, secret, storage_preference=storage_choice)
                io.ok(f"API key guardada en {backend} ({detail}).")
                cred_result["credential_saved"] = backend
            else:
                io.warn("API key omitida. Configúrala luego con `isycode setup provider` o variable de entorno.")

    if configure_slots and io.ask_yes_no(
        "¿Configurar slots opcionales de modelo auxiliar (`small` / `gus`)?",
        default=False,
    ):
        for slot in ("small", "gus"):
            existing = model_slot(slot)
            default_pair = f"{existing['provider']}:{existing['model']}" if existing else ""
            raw = io.ask_text(f"Slot '{slot}' como proveedor:modelo (Enter para omitir)", default_pair)
            if raw and ":" in raw:
                slot_provider, slot_model = raw.split(":", 1)
                slot_provider = slot_provider.strip().casefold()
                slot_model = slot_model.strip()
                if slot_provider in PROVIDER_PRESETS and slot_model:
                    save_model_slot(slot, slot_provider, slot_model)
                    io.ok(f"Slot '{slot}' → {slot_provider}:{slot_model}")
                else:
                    io.warn(f"Slot '{slot}' ignorado: proveedor o modelo inválido.")
    return cred_result


def setup_workspace(io: SetupIO, *, cwd: Path) -> dict[str, Any]:
    io.header("Workspace y Workspace Authority")
    identity = discover_workspace_identity(cwd)
    root = identity.workspace_root
    io.info(f"Directorio actual: {cwd}")
    io.info(f"Raíz de workspace detectada: {root} ({identity.workspace_root_source})")

    marker_created = False
    if identity.workspace_root_source != "isyroot":
        broad_reason = broad_workspace_reason(cwd)
        if broad_reason is not None:
            io.warn(f"No se recomienda crear .isyroot aquí porque {broad_reason}.")
        elif io.ask_yes_no(f"¿Marcar {cwd} como workspace recurrente creando `.isyroot`?", default=True):
            WorkspaceSetupStore().choose_recurrent(cwd, True)
            root = cwd.resolve(strict=True)
            marker_created = True
            io.ok(f"Marcador `.isyroot` creado en {root}")

    authority = WorkspaceAuthority(root)
    current_mode = authority.mode() or "security"
    mode_options = [
        ("security", "Estricto: cada lectura, edición o comando requiere permiso y recibo"),
        ("classic", "Balanceado: lectura cómoda, acciones sensibles con confirmación"),
        ("flow", "Fluido: ediciones, comandos e isymem sin interrupciones en este workspace"),
    ]
    mode_keys = [m for m, _ in mode_options]
    default_mode_idx = mode_keys.index(current_mode) if current_mode in mode_keys else 0
    chosen_mode_idx = io.ask_choice(
        f"Modo de Workspace Authority para {root} (actual: {current_mode}):",
        mode_options,
        default_index=default_mode_idx,
    )
    selected_mode = mode_keys[chosen_mode_idx]
    authority.set_mode(selected_mode)
    io.ok(f"Modo del workspace guardado: {selected_mode}")

    defaults_store = UserDefaultsStore()
    defaults = defaults_store.load()
    new_ws_mode_options = [
        ("ask", "Preguntar al abrir cada carpeta nueva"),
        ("classic", "Preseleccionar Classic en carpetas nuevas"),
        ("security", "Preseleccionar Security en carpetas nuevas"),
    ]
    cur_new_mode = defaults.get("new_workspace_mode", "ask")
    cur_new_mode_idx = next(
        (i for i, (k, _) in enumerate(new_ws_mode_options) if k == cur_new_mode), 0
    )
    chosen_new_mode = new_ws_mode_options[
        io.ask_choice(
            "Modo por defecto para workspaces nuevos:",
            new_ws_mode_options,
            default_index=cur_new_mode_idx,
        )
    ][0]

    recurrence_options = [
        ("ask", "Preguntar si crear .isyroot en carpetas nuevas"),
        ("recurring", "Recordar proyectos normales automáticamente"),
        ("temporary", "Tratar carpetas nuevas como sesiones temporales"),
    ]
    cur_rec = defaults.get("new_workspace", "ask")
    cur_rec_idx = next((i for i, (k, _) in enumerate(recurrence_options) if k == cur_rec), 0)
    chosen_rec = recurrence_options[
        io.ask_choice(
            "Comportamiento por defecto en carpetas nuevas sin .isyroot:",
            recurrence_options,
            default_index=cur_rec_idx,
        )
    ][0]

    defaults_store.update(new_workspace_mode=chosen_new_mode, new_workspace=chosen_rec)
    io.ok(f"Preferencias de workspace: mode={chosen_new_mode}, new_workspace={chosen_rec}")
    return {
        "workspace_root": str(root),
        "marker_created": marker_created,
        "workspace_mode": selected_mode,
        "new_workspace_mode": chosen_new_mode,
        "new_workspace": chosen_rec,
    }


def setup_mcp(io: SetupIO) -> dict[str, Any]:
    io.header("Servidores MCP locales e ISyMCP Hub")
    cfg_path = mcp_config_path()
    try:
        existing = load_mcp_config(cfg_path)
    except (OSError, ValueError) as exc:
        io.warn(f"No se pudo leer {cfg_path}: {exc}")
        existing = {}

    if existing:
        io.info(f"Configurados en {cfg_path}: {', '.join(sorted(existing))}")
    else:
        io.info(f"Aún no hay servidores MCP locales en {cfg_path}.")

    added: list[str] = []

    hub_bin = _detect_isymcp_hub()
    if hub_bin:
        if "isymcp-hub" in existing:
            io.ok(f"ISyMCP Hub ya está registrado ({hub_bin}).")
        elif io.ask_yes_no(
            f"Detectamos ISyMCP Hub en {hub_bin}. ¿Registrar `isymcp-hub` en mcp.json?",
            default=True,
        ):
            _add_mcp_server("isymcp-hub", [hub_bin], path=cfg_path)
            added.append("isymcp-hub")
            io.ok("Servidor `isymcp-hub` agregado a mcp.json.")
    else:
        io.info("ISyMCP Hub no se detectó en PATH ni en ~/.local/bin/isymcp-hub.")

    for preset_name, meta in MCP_PRESETS.items():
        if preset_name in existing:
            io.ok(f"Preset MCP `{preset_name}` ya está configurado.")
            continue
        if io.ask_yes_no(
            f"¿Agregar preset oficial `{preset_name}` ({meta['description']})?",
            default=False,
        ):
            add_mcp_preset(preset_name, path=cfg_path)
            added.append(preset_name)
            io.ok(f"Preset `{preset_name}` agregado a mcp.json.")

    return {"mcp_config": str(cfg_path), "added": added, "configured": sorted(load_mcp_config(cfg_path))}


def setup_gateway(io: SetupIO) -> dict[str, Any]:
    io.header("ISyCo Gateway")
    gateway_url = os.environ.get("GATEWAY_URL") or "http://127.0.0.1:8787"
    gw_cmd = gateway_mcp_command()
    has_env_key = bool(os.environ.get("GATEWAY_API_KEY", "").strip())
    has_vault_key = _vault_has_service("isyco-gateway")

    io.info(f"URL por defecto: {gateway_url}")
    io.info(
        f"Paquete Gateway MCP: {'detectado' if gw_cmd else 'no instalado (define ISYCO_GATEWAY_MCP_ROOT o instala isyco-gateway-mcp)'}"
    )
    key_status = (
        "presente en GATEWAY_API_KEY"
        if has_env_key
        else "guardada en OS keyring"
        if has_vault_key
        else "no configurada"
    )
    io.info(f"Clave de Gateway: {key_status}")

    saved = False
    if keyring_available() and io.ask_yes_no(
        "¿Guardar/actualizar una GATEWAY_API_KEY en el OS keyring (servicio `isyco-gateway`)?",
        default=False,
    ):
        secret = io.ask_secret("GATEWAY_API_KEY (Enter para omitir)")
        if secret:
            _, key_id = _save_gateway_secret(secret)
            saved = True
            io.ok(f"Clave de ISyCo Gateway guardada en OS keyring ({key_id}).")
    return {
        "gateway_url": gateway_url,
        "gateway_mcp_available": bool(gw_cmd),
        "gateway_key_configured": has_env_key or has_vault_key or saved,
    }


def setup_telegram(io: SetupIO) -> dict[str, Any]:
    io.header("Telegram personal (opt-in)")
    status = _detect_telegram_status("personal")
    if status["configured"] and not status["revoked"]:
        io.ok(
            f"Perfil `personal` configurado (activo: {'sí' if status['running'] else 'no'}, "
            f"workspaces: {', '.join(status['workspaces']) or 'ninguno'})."
        )
    else:
        io.info("El frontend personal de Telegram es opt-in y requiere un bot de BotFather + tu user_id.")
        io.info("Para configurarlo con emparejamiento seguro por PIN ejecuta:")
        io.info("  isycode telegram configure --user-id <TU_USER_ID> --workspace <RUTA>")
        io.info("Y para iniciarlo en primer plano:")
        io.info("  isycode telegram serve")
    return status


def setup_defaults(io: SetupIO) -> dict[str, Any]:
    io.header("Preferencias del agente e interfaz")
    store = UserDefaultsStore()
    current = store.load()

    step_options = [
        ("Sin límite (0)" if n == 0 else f"{n} pasos", "límite por turno del agente")
        for n in AGENT_STEP_CHOICES
    ]
    step_idx = (
        AGENT_STEP_CHOICES.index(current["agent_steps"])
        if current["agent_steps"] in AGENT_STEP_CHOICES
        else 0
    )
    agent_steps = AGENT_STEP_CHOICES[
        io.ask_choice("Límite de pasos del agente por turno:", step_options, default_index=step_idx)
    ]

    token_values: tuple[int | None, ...] = (None, *ANSWER_TOKEN_CHOICES)
    token_options = [
        ("Sin límite explícito" if n is None else f"{n:,} tokens", "máximo por respuesta")
        for n in token_values
    ]
    token_idx = (
        token_values.index(current["answer_tokens"])
        if current["answer_tokens"] in token_values
        else 0
    )
    answer_tokens = token_values[
        io.ask_choice("Longitud máxima de respuesta:", token_options, default_index=token_idx)
    ]

    budget_options = [
        ("Sin límite (0)" if n == 0 else f"{n:,} tokens", "presupuesto por sesión de chat")
        for n in CHAT_TOKEN_BUDGET_CHOICES
    ]
    budget_idx = (
        CHAT_TOKEN_BUDGET_CHOICES.index(current["chat_token_budget"])
        if current["chat_token_budget"] in CHAT_TOKEN_BUDGET_CHOICES
        else 0
    )
    chat_token_budget = CHAT_TOKEN_BUDGET_CHOICES[
        io.ask_choice("Presupuesto de tokens por conversación:", budget_options, default_index=budget_idx)
    ]

    sounds = io.ask_yes_no("¿Activar sonidos de notificación?", default=bool(current["notification_sounds"]))
    high_contrast = io.ask_yes_no("¿Activar modo de alto contraste?", default=bool(current["high_contrast"]))
    reduced_motion = io.ask_yes_no("¿Activar movimiento reducido?", default=bool(current["reduced_motion"]))

    store.update(
        agent_steps=agent_steps,
        answer_tokens=answer_tokens,
        chat_token_budget=chat_token_budget,
        notification_sounds=sounds,
        high_contrast=high_contrast,
        reduced_motion=reduced_motion,
    )
    io.ok("Preferencias del agente guardadas.")
    return {
        "agent_steps": agent_steps,
        "answer_tokens": answer_tokens,
        "chat_token_budget": chat_token_budget,
        "notification_sounds": sounds,
        "high_contrast": high_contrast,
        "reduced_motion": reduced_motion,
    }


# ── Status & Hermes-inspired summary ─────────────────────────────────────────


def collect_setup_status(cwd: Path | None = None) -> dict[str, Any]:
    """Build a complete local setup status report with zero network calls."""
    launch = (cwd or Path.cwd()).expanduser().resolve()
    identity = discover_workspace_identity(launch)
    root = identity.workspace_root
    diag = collect_diagnostics(root)

    provider = selected_provider_name()
    model = selected_model_name() or resolved_chat_model(provider)
    preset = PROVIDER_PRESETS.get(provider, {})
    cred_ok = (
        provider in OAUTH_PROVIDERS
        or preset.get("key_required") is False
        or provider_credential_state(provider) in {"environment", "session", "stored", "legacy"}
        or _vault_has_service(provider)
    )

    try:
        mcp_servers = sorted(load_mcp_config())
    except (OSError, ValueError):
        mcp_servers = []

    hub_bin = _detect_isymcp_hub()
    gw_cmd = gateway_mcp_command()
    gw_key_ok = bool(os.environ.get("GATEWAY_API_KEY", "").strip()) or _vault_has_service("isyco-gateway")
    tg = _detect_telegram_status("personal")
    defaults = UserDefaultsStore().load()

    return {
        "version": 1,
        "network_tested": False,
        "locale": defaults.get("locale", UserDefaultsStore.DEFAULT_LOCALE),
        "provider": {
            "name": provider,
            "label": preset.get("label", provider),
            "model": model,
            "credential_ready": cred_ok,
            "credential_summary": _provider_status_badge(provider) if provider in PROVIDER_PRESETS else "unknown",
            "slots": {"small": model_slot("small"), "gus": model_slot("gus")},
        },
        "workspace": {
            "root": str(root),
            "source": identity.workspace_root_source,
            "mode": diag["workspace_mode"],
            "new_workspace": defaults.get("new_workspace", "ask"),
            "new_workspace_mode": defaults.get("new_workspace_mode", "ask"),
        },
        "integrations": {
            "keyring": keyring_available(),
            "command_sandbox": diag["command_sandbox"],
            "mcp_servers": mcp_servers,
            "isymcp_hub_detected": bool(hub_bin),
            "isymcp_hub_path": hub_bin,
            "gateway_mcp_detected": bool(gw_cmd),
            "gateway_key_configured": gw_key_ok,
            "telegram": tg,
            "hive_attached": bool(os.environ.get("HIVE_SOCK") and os.environ.get("AGENT_ID")),
            "tailscale_installed": bool(shutil.which("tailscale")),
        },
        "paths": {
            "state_root": str(state_root()),
            "user_defaults": str(UserDefaultsStore().path),
            "provider_preferences": str(provider_preferences_path()),
            "mcp_config": str(mcp_config_path()),
            "key_store": str(key_store_path()),
        },
        "diagnostics": diag,
    }


def print_setup_summary(io: SetupIO, status: dict[str, Any], *, show_complete_banner: bool = True) -> None:
    """Render a Hermes-style availability summary and quick command cheatsheet."""
    prov = status["provider"]
    ws = status["workspace"]
    integ = status["integrations"]
    paths = status["paths"]

    if not prov["credential_ready"]:
        io.write()
        io.warn(
            f"El proveedor activo ({prov['label']}) aún no tiene API key configurada."
        )
        io.info("Ejecuta `isycode setup provider` o exporta su variable de entorno antes de chatear.")

    io.header("Resumen de integraciones ISyCode")

    rows: list[tuple[str, bool, str | None]] = [
        (
            f"Proveedor ({prov['label']} · {prov['model']})",
            bool(prov["credential_ready"]),
            None if prov["credential_ready"] else "ejecuta `isycode setup provider`",
        ),
        (
            f"Workspace ({ws['root']} · modo {ws['mode']})",
            ws["source"] == "isyroot",
            None if ws["source"] == "isyroot" else "sin .isyroot (usa `isycode setup workspace`)",
        ),
        (
            "OS Keyring (CredentialVault)",
            bool(integ["keyring"]),
            None if integ["keyring"] else "fallback a keys.env (0600)",
        ),
        (
            f"Sandbox de comandos ({integ['command_sandbox']})",
            "ingredients-installed" in str(integ["command_sandbox"]),
            None if "ingredients-installed" in str(integ["command_sandbox"]) else "revisa `isycode doctor`",
        ),
        (
            f"Servidores MCP locales ({', '.join(integ['mcp_servers']) or 'ninguno'})",
            bool(integ["mcp_servers"]),
            None if integ["mcp_servers"] else "opcional: `isycode setup mcp`",
        ),
        (
            "ISyMCP Hub",
            "isymcp-hub" in integ["mcp_servers"],
            None
            if "isymcp-hub" in integ["mcp_servers"]
            else ("detectado, sin registrar (`isycode setup mcp`)" if integ["isymcp_hub_detected"] else "no detectado"),
        ),
        (
            "ISyCo Gateway",
            bool(integ["gateway_mcp_detected"] and integ["gateway_key_configured"]),
            None if (integ["gateway_mcp_detected"] and integ["gateway_key_configured"]) else "opcional: `isycode setup gateway`",
        ),
        (
            "Telegram personal",
            bool(integ["telegram"]["configured"] and not integ["telegram"]["revoked"]),
            None if (integ["telegram"]["configured"] and not integ["telegram"]["revoked"]) else "opt-in: `isycode telegram --help`",
        ),
    ]

    ready = sum(1 for _, ok, _ in rows if ok)
    io.info(f"{ready}/{len(rows)} integraciones listas:")
    for label, ok, hint in rows:
        if ok:
            io.write(f"    {io.style('✓', '1;32')} {label}")
        else:
            suffix = f" {io.style(f'({hint})', '2')}" if hint else ""
            io.write(f"    {io.style('○', '1;33')} {label}{suffix}")

    if show_complete_banner:
        io.banner("✓ ISyCode Setup Complete!", f"Idioma: {status['locale']} · Proveedor: {prov['name']} · Modo: {ws['mode']}")

    io.header("Rutas de configuración")
    for label, value in (
        ("Estado privado:", paths["state_root"]),
        ("Preferencias:", paths["user_defaults"]),
        ("Proveedor:", paths["provider_preferences"]),
        ("MCP locales:", paths["mcp_config"]),
        ("Keys file:", paths["key_store"]),
    ):
        io.write(f"    {io.style(f'{label:<16}', '33')} {value}")

    io.header("Comandos útiles")
    for cmd, desc in (
        ("isycode", "Iniciar la TUI de chat en este workspace"),
        ("isycode setup provider", "Cambiar proveedor, modelo o API key"),
        ("isycode setup workspace", "Configurar .isyroot y modo de Authority"),
        ("isycode setup mcp", "Agregar ISyMCP Hub o presets MCP"),
        ("isycode setup --status", "Ver estado de integraciones sin cambiar nada"),
        ("isycode doctor", "Diagnóstico local completo (JSON)"),
        ("isycode cli", "Explorador semántico de comandos"),
    ):
        io.write(f"    {io.style(f'{cmd:<26}', '1;32')} {desc}")
    io.write()


def print_noninteractive_guidance(io: SetupIO) -> None:
    io.banner("ISyCode Setup — Modo no interactivo", "No se detectó TTY interactivo")
    io.info("Configura ISyCode pasando flags explícitos, por ejemplo:")
    io.write("    isycode setup --non-interactive --provider nvidia --model nvidia/nemotron-3-ultra-550b-a55b --mode flow")
    io.write("    isycode setup --non-interactive --provider openai --api-key-env OPENAI_API_KEY --init-workspace")
    io.write("    isycode setup --status --json")
    io.write()
    io.info("O ejecuta `isycode setup` en una terminal interactiva para usar el asistente guiado.")


# ── Non-interactive execution ────────────────────────────────────────────────


def _apply_noninteractive(args: argparse.Namespace, io: SetupIO, cwd: Path) -> int:
    ensure_state_root()
    changes: dict[str, Any] = {}

    workspace_dir = Path(args.workspace).expanduser().resolve() if args.workspace else cwd.resolve()
    if not workspace_dir.is_dir():
        io.error(f"El directorio de workspace no existe: {workspace_dir}")
        return EXIT_FAILED

    if args.locale:
        UserDefaultsStore().update(locale=args.locale)
        changes["locale"] = args.locale

    if args.provider:
        provider = args.provider.strip().casefold()
        if provider not in PROVIDER_PRESETS:
            io.error(f"Proveedor desconocido: {provider}")
            return EXIT_USAGE
        preset = PROVIDER_PRESETS[provider]
        model = (
            args.model.strip()
            if args.model
            else preset.get("default_model") or provider_default_model(provider) or DEFAULT_MODEL
        )
        save_provider_selection(provider, model)
        changes["provider"] = provider
        changes["model"] = model
    elif args.model:
        provider = selected_provider_name()
        save_provider_selection(provider, args.model.strip())
        changes["provider"] = provider
        changes["model"] = args.model.strip()

    for slot, arg_val in (("small", args.small_model), ("gus", args.gus_model)):
        if arg_val:
            if ":" not in arg_val:
                io.error(f"--{slot}-model debe usar el formato proveedor:modelo")
                return EXIT_USAGE
            slot_provider, slot_model = arg_val.split(":", 1)
            save_model_slot(slot, slot_provider.strip(), slot_model.strip())
            changes[f"slot_{slot}"] = f"{slot_provider.strip().casefold()}:{slot_model.strip()}"

    secret_value = ""
    if args.api_key:
        secret_value = args.api_key
    elif args.api_key_env:
        secret_value = os.environ.get(args.api_key_env, "").strip()
        if not secret_value:
            io.error(f"La variable de entorno {args.api_key_env} está vacía o no definida.")
            return EXIT_FAILED

    if secret_value:
        target_provider = (args.provider or selected_provider_name()).casefold()
        backend, detail = _save_provider_secret(
            target_provider,
            secret_value,
            storage_preference=args.key_storage,
        )
        changes["credential_saved"] = {"provider": target_provider, "backend": backend, "ref": detail}

    if args.init_workspace:
        broad_reason = broad_workspace_reason(workspace_dir)
        if broad_reason is not None:
            io.error(f"Rechazado crear .isyroot en {workspace_dir}: {broad_reason}")
            return EXIT_FAILED
        WorkspaceSetupStore().choose_recurrent(workspace_dir, True)
        changes["init_workspace"] = str(workspace_dir)

    identity = discover_workspace_identity(workspace_dir)
    if args.mode:
        WorkspaceAuthority(identity.workspace_root).set_mode(args.mode)
        changes["workspace_mode"] = args.mode

    defaults_kwargs: dict[str, Any] = {}
    if args.default_mode:
        defaults_kwargs["new_workspace_mode"] = args.default_mode
    if args.new_workspace:
        defaults_kwargs["new_workspace"] = args.new_workspace
    if args.agent_steps is not None:
        defaults_kwargs["agent_steps"] = args.agent_steps
    if args.answer_tokens is not None:
        defaults_kwargs["answer_tokens"] = args.answer_tokens
    if args.chat_token_budget is not None:
        defaults_kwargs["chat_token_budget"] = args.chat_token_budget
    if defaults_kwargs:
        UserDefaultsStore().update(**defaults_kwargs)
        changes["defaults"] = defaults_kwargs

    if args.mcp_preset:
        mcp_added: list[str] = []
        for name in args.mcp_preset:
            if name == "isymcp-hub":
                hub_bin = _detect_isymcp_hub()
                if not hub_bin:
                    io.error("No se encontró `isymcp-hub` en PATH ni en ~/.local/bin/isymcp-hub.")
                    return EXIT_FAILED
                _add_mcp_server("isymcp-hub", [hub_bin])
                mcp_added.append("isymcp-hub")
            elif name in MCP_PRESETS:
                if name not in load_mcp_config():
                    add_mcp_preset(name)
                mcp_added.append(name)
            else:
                io.error(f"Preset MCP desconocido: {name}")
                return EXIT_USAGE
        changes["mcp_added"] = mcp_added

    status = collect_setup_status(workspace_dir)
    if args.json:
        io.write(json.dumps({"changes": changes, "status": status}, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_setup_summary(io, status, show_complete_banner=True)
    return EXIT_OK


# ── Argument parser & entry point ────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="isycode setup",
        description="Asistente de configuración inicial y mantenimiento de ISyCode.",
    )
    parser.add_argument(
        "section",
        nargs="?",
        choices=SECTION_NAMES,
        help="Ejecuta una sola sección del asistente (language, provider, workspace, mcp, gateway, telegram, defaults).",
    )
    parser.add_argument("--quick", action="store_true", help="Configuración rápida (idioma, proveedor y workspace).")
    parser.add_argument("--status", action="store_true", help="Mostrar estado de integraciones sin modificar nada.")
    parser.add_argument("--non-interactive", action="store_true", help="Aplicar configuración por flags sin prompts.")
    parser.add_argument("--json", action="store_true", help="Salida JSON (para --status o --non-interactive).")
    parser.add_argument("--locale", choices=("es", "en", "zh"), help="Idioma de la interfaz.")
    parser.add_argument("--provider", help="Proveedor de inferencia (ej. nvidia, openai, anthropic, chatgpt, ollama).")
    parser.add_argument("--model", help="ID del modelo principal.")
    parser.add_argument("--small-model", help="Slot auxiliar 'small' en formato proveedor:modelo.")
    parser.add_argument("--gus-model", help="Slot auxiliar 'gus' en formato proveedor:modelo.")
    parser.add_argument("--api-key", help="API key para el proveedor seleccionado (preferir --api-key-env).")
    parser.add_argument("--api-key-env", help="Nombre de variable de entorno desde la cual leer la API key.")
    parser.add_argument(
        "--key-storage",
        choices=("auto", "vault", "file"),
        default="auto",
        help="Destino de guardado para API keys (default: auto → OS keyring, fallback keys.env).",
    )
    parser.add_argument("--workspace", help="Ruta del workspace a configurar (default: directorio actual).")
    parser.add_argument("--init-workspace", action="store_true", help="Crear marcador .isyroot en el workspace.")
    parser.add_argument("--mode", choices=WORKSPACE_MODES, help="Modo de Workspace Authority (classic, flow, security).")
    parser.add_argument("--default-mode", choices=NEW_WORKSPACE_MODES, help="Modo por defecto para nuevos workspaces.")
    parser.add_argument("--new-workspace", choices=NEW_WORKSPACE_CHOICES, help="Recurrencia por defecto para carpetas nuevas.")
    parser.add_argument(
        "--mcp-preset",
        action="append",
        help="Registrar preset MCP local (playwright, context7, isymcp-hub). Repetible.",
    )
    parser.add_argument("--agent-steps", type=int, choices=AGENT_STEP_CHOICES, help="Límite de pasos del agente.")
    parser.add_argument(
        "--answer-tokens",
        type=int,
        choices=[n for n in ANSWER_TOKEN_CHOICES if n is not None],
        help="Límite de tokens por respuesta.",
    )
    parser.add_argument(
        "--chat-token-budget",
        type=int,
        choices=CHAT_TOKEN_BUDGET_CHOICES,
        help="Presupuesto de tokens por conversación (0 = sin límite).",
    )
    return parser


def _has_config_flags(args: argparse.Namespace) -> bool:
    return any(
        getattr(args, name) is not None and getattr(args, name) is not False
        for name in (
            "locale",
            "provider",
            "model",
            "small_model",
            "gus_model",
            "api_key",
            "api_key_env",
            "init_workspace",
            "mode",
            "default_mode",
            "new_workspace",
            "mcp_preset",
            "agent_steps",
            "answer_tokens",
            "chat_token_budget",
        )
    )


def main(
    argv: list[str] | None = None,
    *,
    io: SetupIO | None = None,
    cwd: Path | None = None,
) -> int:
    io = io or SetupIO()
    working_dir = (cwd or Path.cwd()).expanduser().resolve()
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE

    if args.status:
        status = collect_setup_status(working_dir)
        if args.json:
            io.write(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print_setup_summary(io, status, show_complete_banner=False)
        return EXIT_OK

    if args.non_interactive or _has_config_flags(args):
        try:
            return _apply_noninteractive(args, io, working_dir)
        except (ConfigurationError, WorkspaceAuthorityError, CredentialVaultError, OSError, ValueError) as exc:
            if args.json:
                io.write(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
            else:
                io.error(str(exc))
            return EXIT_FAILED

    if not io.tty():
        print_noninteractive_guidance(io)
        return EXIT_OK

    try:
        ensure_state_root()
        if args.section:
            io.banner(f"ISyCode Setup — {args.section}", "Ctrl+C en cualquier momento para cancelar")
            _run_single_section(args.section, io, working_dir)
            print_setup_summary(io, collect_setup_status(working_dir), show_complete_banner=False)
            return EXIT_OK

        existing = _is_existing_install()
        io.banner(
            "ISyCode Setup Wizard",
            "Configura proveedores, workspace, MCP y tus integraciones. Ctrl+C para salir.",
        )

        if args.quick:
            setup_language(io)
            setup_provider(io, configure_slots=False)
            setup_workspace(io, cwd=working_dir)
        elif existing:
            io.ok("Ya tienes una configuración previa de ISyCode.")
            io.info("Cada paso mostrará tu valor actual; pulsa Enter para conservarlo.")
            io.info("Tip: salta a una sección con `isycode setup provider|workspace|mcp|gateway|telegram|defaults`.")
            _run_full_sections(io, working_dir)
        else:
            mode_idx = io.ask_choice(
                "¿Cómo quieres configurar ISyCode?",
                [
                    ("Configuración rápida (recomendado)", "Idioma, proveedor/modelo y workspace"),
                    ("Configuración completa", "Todas las secciones: proveedor, workspace, MCP/Hub, Gateway, Telegram y agente"),
                    ("Mínimo (Blank Slate)", "Solo idioma y proveedor; el resto permanece sin cambios"),
                ],
                default_index=0,
            )
            if mode_idx == 0:
                setup_language(io)
                setup_provider(io, configure_slots=False)
                setup_workspace(io, cwd=working_dir)
            elif mode_idx == 1:
                _run_full_sections(io, working_dir)
            else:
                setup_language(io)
                setup_provider(io, configure_slots=False)

        print_setup_summary(io, collect_setup_status(working_dir), show_complete_banner=True)
        return EXIT_OK
    except SetupCancelled:
        io.warn("Setup cancelado. Las secciones pendientes no fueron modificadas.")
        return EXIT_CANCELLED
    except (ConfigurationError, WorkspaceAuthorityError, CredentialVaultError, OSError, ValueError) as exc:
        io.error(str(exc))
        return EXIT_FAILED


def _run_single_section(section: str, io: SetupIO, working_dir: Path) -> None:
    if section == "language":
        setup_language(io)
    elif section == "provider":
        setup_provider(io, configure_slots=True)
    elif section == "workspace":
        setup_workspace(io, cwd=working_dir)
    elif section == "mcp":
        setup_mcp(io)
    elif section == "gateway":
        setup_gateway(io)
    elif section == "telegram":
        setup_telegram(io)
    elif section == "defaults":
        setup_defaults(io)


def _run_full_sections(io: SetupIO, working_dir: Path) -> None:
    setup_language(io)
    setup_provider(io, configure_slots=True)
    setup_workspace(io, cwd=working_dir)
    setup_mcp(io)
    setup_gateway(io)
    setup_telegram(io)
    setup_defaults(io)


__all__ = [
    "EXIT_CANCELLED",
    "EXIT_FAILED",
    "EXIT_OK",
    "EXIT_USAGE",
    "SECTION_NAMES",
    "SetupCancelled",
    "SetupIO",
    "collect_setup_status",
    "main",
    "print_setup_summary",
]
