"""API credentials: operating-system keyring or memory, never plaintext fallback."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from core.ide_state import state_home, atomic_write, state_lock

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    keyring = None
    KEYRING_AVAILABLE = False


def parse_api_credentials(path: str | Path) -> dict[str, str]:
    """Explicit import of API records only; OAuth tokens are not API keys."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("El archivo debe contener un mapa de providers.")
    keys = {}
    for name, value in data.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
            continue
        if isinstance(value, dict):
            if value.get("type", value.get("auth_type", "api")) not in {"api", "api_key", "apikey"}:
                continue
            if any(field in value for field in ("refresh", "refresh_token", "access", "access_token", "expires")):
                continue
            value = value.get("key")
        if isinstance(value, str) and value.strip():
            value = value.strip()
            keys[name] = value[7:] if value.startswith("Bearer ") else value
    return {name: key for name, key in keys.items() if key}


class SecretBroker:
    """Never logs secret values. Unavailable keyring means session-only storage."""

    SERVICE = "isycode-ide"

    def __init__(self):
        self._cache: dict[str, str] = {}
        self._storage: dict[str, str] = {}
        self._index_file = state_home() / "credential-names.json"

    def _names(self) -> set[str]:
        if not self._index_file.exists():
            return set()
        try:
            values = json.loads(self._index_file.read_text())
            return {name for name in values if isinstance(name, str)} if isinstance(values, list) else set()
        except (OSError, ValueError):
            return set()

    def _remember_name(self, provider: str, present: bool) -> None:
        with state_lock(self._index_file.with_suffix(".lock")):
            names = self._names()
            if present:
                names.add(provider)
            else:
                names.discard(provider)
            atomic_write(self._index_file, json.dumps(sorted(names)) + "\n")

    def set(self, provider: str, key: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", provider):
            raise ValueError("Nombre de provider inválido.")
        key = key.strip()
        if not key or any(ord(char) < 32 for char in key):
            raise ValueError("La clave está vacía o contiene caracteres de control.")
        storage = "session"
        if KEYRING_AVAILABLE:
            try:
                keyring.set_password(self.SERVICE, f"provider:{provider}", key)
                storage = "keyring"
            except Exception:
                # Never include keyring exception text: some backends echo secrets.
                pass
        self._cache[provider] = key
        self._storage[provider] = storage
        if storage == "keyring":
            try:
                self._remember_name(provider, True)
            except OSError:
                pass  # Secret is still durable; only the optional name index failed.
        return storage

    def get(self, provider: str) -> Optional[str]:
        if provider in self._cache:
            return self._cache[provider]
        if KEYRING_AVAILABLE:
            try:
                value = keyring.get_password(self.SERVICE, f"provider:{provider}")
                if value:
                    self._cache[provider] = value
                    self._storage[provider] = "keyring"
                    return value
            except Exception:
                pass
        return None

    def storage_status(self, provider: str) -> str:
        return self._storage.get(provider, "missing") if self.get(provider) else "missing"

    def keyring_status(self) -> dict:
        """Report whether the OS keyring backend is genuinely usable (no secrets written)."""
        if not KEYRING_AVAILABLE or keyring is None:
            return {"available": False, "backend": "none", "detail": "Módulo keyring no instalado; las claves solo viven en memoria de esta sesión."}
        try:
            backend = keyring.get_keyring()
            name = type(backend).__name__
            mod = type(backend).__module__
            if "fail" in name.lower() or "null" in name.lower() or "fail" in mod.lower():
                return {"available": False, "backend": name, "detail": f"Keyring inactivo ({name}); las claves solo viven en memoria de esta sesión."}
            return {"available": True, "backend": name, "detail": f"Keyring del sistema disponible ({name}); las claves se guardan cifradas."}
        except Exception:
            return {"available": False, "backend": "error", "detail": "Keyring no disponible en este entorno; las claves solo viven en memoria de esta sesión."}

    def remove(self, provider: str) -> bool:
        removed = provider in self._cache
        if KEYRING_AVAILABLE:
            try:
                if keyring.get_password(self.SERVICE, f"provider:{provider}") is not None:
                    keyring.delete_password(self.SERVICE, f"provider:{provider}")
                    removed = True
            except Exception:
                # Do not silently claim a durable credential was removed.
                if provider in self._names() or self._storage.get(provider) == "keyring":
                    raise ValueError("No se pudo eliminar la clave del keyring.") from None
        self._cache.pop(provider, None)
        self._storage.pop(provider, None)
        self._remember_name(provider, False)
        return removed

    def list_providers(self) -> list[str]:
        return sorted(self._names() | set(self._cache))

    def inject_into_headers(self, provider: str, headers: dict) -> dict:
        key = self.get(provider)
        if not key:
            raise ValueError(f"Configura una clave API para {provider}.")
        return {**headers, "Authorization": f"Bearer {key}"}

    def has_key(self, provider: str) -> bool:
        return self.get(provider) is not None

    def prompt_and_store(self, provider: str) -> bool:
        import getpass
        key = getpass.getpass(f"Clave API de {provider}: ").strip()
        if not key:
            return False
        storage = self.set(provider, key)
        print("Clave guardada en keyring." if storage == "keyring" else "Clave disponible solo durante esta sesión.")
        return True

    def import_from_opencode(self, path: Path | None = None) -> dict:
        if path is None:
            base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
            path = base / "opencode/auth.json"
        return {name: self.set(name, key) for name, key in parse_api_credentials(path).items()}


def get_secret_broker() -> SecretBroker:
    if not hasattr(get_secret_broker, "_instance"):
        get_secret_broker._instance = SecretBroker()
    return get_secret_broker._instance
