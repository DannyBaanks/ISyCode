"""Explicit official CLI accounts, separate from API keys and global routing."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path

from core.connectors.codex import CodexConnector
from core.ide_state import atomic_write, state_home, state_lock
from core.processes import capture_process


KINDS = {"codex-subscription": "codex", "claude-subscription": "claude", "grok-subscription": "grok"}
ENDPOINTS = {"codex-subscription": "https://chatgpt.com/backend-api/codex",
             "claude-subscription": "https://api.anthropic.com",
             "grok-subscription": "https://cli-chat-proxy.grok.com/v1"}


class SubscriptionError(ValueError):
    pass


def binary_hash(path):
    handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest = hashlib.sha256()
    with os.fdopen(handle, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 512_000_000 or info.st_mode & (stat.S_ISUID | stat.S_ISGID):
            raise SubscriptionError("El CLI seleccionado no es un ejecutable regular soportado.")
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


class SubscriptionService:
    def __init__(self):
        self.path = state_home() / "subscriptions.json"

    def _profiles(self):
        if not self.path.exists():
            return {}
        if self.path.is_symlink() or self.path.stat().st_size > 65536:
            raise SubscriptionError("Registro de conectores no válido.")
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict):
            raise SubscriptionError("Registro de conectores no válido.")
        return data

    def configure(self, kind, executable=None):
        if kind not in KINDS:
            raise SubscriptionError("Conector no soportado.")
        selected = executable or shutil.which(KINDS[kind])
        if not selected:
            raise SubscriptionError("Instala el CLI oficial y selecciona su ejecutable.")
        path = Path(selected).expanduser().resolve(strict=True)
        if not os.access(path, os.X_OK):
            raise SubscriptionError("El CLI no es ejecutable.")
        profile = {"kind": kind, "executable": str(path), "sha256": binary_hash(path),
                   "home": str(state_home() / "accounts" / kind), "auth": "subscription"}
        with state_lock(self.path.with_suffix(".lock")):
            profiles = self._profiles()
            profiles[kind] = profile
            atomic_write(self.path, json.dumps(profiles, indent=2) + "\n")
        return profile

    def identity(self, kind):
        profile = self._profiles().get(kind)
        if not isinstance(profile, dict) or profile.get("kind") != kind:
            raise SubscriptionError("Configura este conector en Providers → Suscripciones.")
        home = state_home() / "accounts" / kind
        if profile.get("home") != str(home) or home.is_symlink():
            raise SubscriptionError("El perfil de suscripción debe usar su carpeta privada.")
        path = profile.get("executable")
        if not isinstance(path, str) or not Path(path).is_absolute() or not os.access(path, os.X_OK):
            raise SubscriptionError("El CLI configurado ya no está disponible.")
        if binary_hash(path) != profile.get("sha256"):
            raise SubscriptionError("El ejecutable del conector cambió. Revisa su actualización y vuelve a configurarlo.")
        return dict(profile)

    def environment(self, identity):
        home = Path(identity["home"])
        for item in (home, *home.parents):
            if item.is_symlink():
                raise SubscriptionError("El perfil no puede atravesar enlaces simbólicos.")
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        allowed = {"LANG", "LC_ALL", "TZ", "DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "XDG_CURRENT_DESKTOP"}
        env = {k: v for k, v in os.environ.items() if k in allowed}
        env.update(PATH="/usr/bin:/bin", HOME=str(home), CODEX_HOME=str(home), CLAUDE_CONFIG_DIR=str(home),
                   XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(home / ".local/share"),
                   XDG_CACHE_HOME=str(home / ".cache"), DISABLE_AUTOUPDATER="1", NO_COLOR="1")
        return env

    def claude_command(self, identity, model, schema):
        return [identity["executable"], "--restricted", "--safe-mode", "--tools", "", "--strict-mcp-config",
                "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "", "--settings", '{"disableAllHooks":true}',
                "--permission-mode", "manual", "--permission-prompts", "none", "--no-chrome",
                "--no-session-persistence", "--model", model, "--print", "--output-format", "json",
                "--json-schema", json.dumps(schema)]

    async def inspect(self, kind):
        identity = self.identity(kind)
        if kind == "codex-subscription":
            async with CodexConnector(identity["executable"], Path(identity["home"]), timeout_s=30) as peer:
                account = await peer.account()
                return {"authenticated": account["authenticated"], "state": "signed_in" if account["authenticated"] else "login_required",
                        "models": await peer.models() if account["authenticated"] else [], "method": account["method"]}
        if kind == "claude-subscription":
            output = await capture_process([identity["executable"], "--safe-mode", "--restricted", "--setting-sources", "", "auth", "status", "--json"],
                                           env=self.environment(identity), cwd=identity["home"], timeout=20, limit=65536)
            try:
                account = json.loads(output.stdout)
            except ValueError:
                raise SubscriptionError("Claude no produjo un estado de autenticación válido.") from None
            authenticated = output.returncode == 0 and isinstance(account, dict) and account.get("loggedIn") is True and account.get("authMethod") == "claude.ai"
            return {"authenticated": authenticated, "state": "signed_in" if authenticated else "login_required", "models": []}
        token = self.grok_token(identity)
        return {"authenticated": False, "state": "stored_session_unverified" if token else "login_required_or_expired", "models": []}

    def grok_token(self, identity):
        path = Path(identity["home"]) / ".grok" / "auth.json"
        if path.is_symlink() or path.parent.is_symlink():
            raise SubscriptionError("El almacén de sesión de Grok no admite enlaces.")
        if not path.exists():
            return ""
        info = path.stat()
        if info.st_size > 65536 or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise SubscriptionError("Protege el archivo de sesión de Grok con permisos privados.")
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return ""
        for item in data.values():
            if not isinstance(item, dict) or item.get("oidc_issuer") != "https://auth.x.ai":
                continue
            try:
                expiry = datetime.fromisoformat(item.get("expires_at", "").replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if expiry.tzinfo and expiry > datetime.now(timezone.utc) and isinstance(item.get("key"), str):
                return item["key"]
        return ""

    async def login(self, kind, on_challenge):
        identity = self.identity(kind)
        if kind == "codex-subscription":
            async with CodexConnector(identity["executable"], Path(identity["home"]), timeout_s=300) as peer:
                challenge = await peer.start_login("browser")
                on_challenge(challenge)
                await peer.wait_login(challenge["login_id"])
                return {"authenticated": True, "state": "signed_in", "models": await peer.models()}
        # Native login owns credentials and opens the browser itself. No output
        # is retained or surfaced; peer output can contain tokens or account data.
        args = [identity["executable"], "auth", "login", "--claudeai"] if kind == "claude-subscription" else [identity["executable"], "login", "--oauth"]
        on_challenge({"message": "El CLI oficial abrirá el navegador. Completa el acceso y vuelve aquí."})
        output = await capture_process(args, env=self.environment(identity), cwd=identity["home"], timeout=300, limit=65536)
        if output.returncode:
            raise SubscriptionError("El acceso no terminó. Revisa el CLI oficial; no se importa otra cuenta ni una clave API.")
        return await self.inspect(kind)

    async def logout(self, kind):
        identity = self.identity(kind)
        if kind == "codex-subscription":
            async with CodexConnector(identity["executable"], Path(identity["home"]), timeout_s=30) as peer:
                await peer.logout()
        else:
            args = [identity["executable"], "auth", "logout"] if kind == "claude-subscription" else [identity["executable"], "logout"]
            output = await capture_process(args, env=self.environment(identity), cwd=identity["home"], timeout=30, limit=65536)
            if output.returncode:
                raise SubscriptionError("El CLI no pudo cerrar esta sesión privada.")
        return await self.inspect(kind)
