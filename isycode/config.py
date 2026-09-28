"""Runtime configuration and dependency discovery for ISyCode."""
from __future__ import annotations

import os
import tempfile
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent


class ConfigurationError(RuntimeError):
    """A required local configuration value is missing or invalid."""


@dataclass(frozen=True)
class WorkspaceIdentity:
    """Logical workspace identity, independent of launch location and grants."""

    launch_dir: Path
    workspace_root: Path
    workspace_root_source: Literal["isyroot", "fallback"]


def discover_workspace_identity(launch_dir: Path | None = None) -> WorkspaceIdentity:
    """Resolve the nearest regular .isyroot marker, or fall back to launch cwd.

    All paths are canonicalized before walking, so a symlinked launch path is
    treated as its real location. A marker must itself be a regular file; a
    symlink named .isyroot is not an identity boundary.
    """
    requested = launch_dir if launch_dir is not None else Path.cwd()
    try:
        launch = requested.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"Could not resolve launch directory: {exc}") from exc
    if not launch.is_dir():
        raise ConfigurationError(f"Launch directory is not a directory: {launch}")
    current = launch
    while True:
        marker = current / ".isyroot"
        try:
            metadata = marker.lstat()
        except FileNotFoundError:
            metadata = None
        except OSError as exc:
            raise ConfigurationError(f"Could not inspect workspace marker: {exc}") from exc
        if metadata is not None and stat.S_ISREG(metadata.st_mode) and metadata.st_size == 0:
            return WorkspaceIdentity(launch, current.resolve(strict=True), "isyroot")
        parent = current.parent
        if parent == current:
            break
        current = parent
    return WorkspaceIdentity(launch, launch, "fallback")


NVIDIA_NEMOTRON_550B = "nvidia/nemotron-3-ultra-550b-a55b"


def provider_default_model(provider_name: str) -> str | None:
    """Return ISyCode's NVIDIA NIM default without overriding a user model."""
    if provider_name.casefold() != "nvidia":
        return None
    active = os.environ.get("ISYCODE_PROVIDER", os.environ.get(
        "ISYMOTRON_PROVIDER", "nebius")).casefold()
    if active == "nvidia" and (os.environ.get("ISYCODE_MODEL") or os.environ.get("ISYMOTRON_MODEL")):
        return None
    return NVIDIA_NEMOTRON_550B


def find_isymotron_root() -> Path:
    """Find the sibling IsyMotron checkout or use an explicit override."""
    configured = os.environ.get("ISYMOTRON_ROOT")
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.append(PROJECT_ROOT.parent / "IsyMotron")

    for candidate in candidates:
        root = candidate.resolve()
        if (root / "agents" / "planner.py").is_file() and (root / "core").is_dir():
            return root

    expected = candidates[0] if configured else PROJECT_ROOT.parent / "IsyMotron"
    raise ConfigurationError(
        "IsyMotron was not found. Set ISYMOTRON_ROOT to its checkout; "
        f"the default sibling path checked was {expected}."
    )


def load_api_key(provider_name: str | None = None) -> str:
    """Load the selected provider key from env or IsyMotron's external store."""
    selected_provider = (provider_name or os.environ.get("ISYCODE_PROVIDER", os.environ.get(
        "ISYMOTRON_PROVIDER", "nebius"))).casefold()
    # Generic overrides describe only the active provider. Explicit provider
    # lookups (for example, the Roundtrip reviewer) resolve their own key.
    generic_override_applies = (
        provider_name is None or provider_name.casefold() == selected_provider)
    if generic_override_applies:
        value = os.environ.get("ISYMOTRON_API_KEY", "").strip()
        if value:
            return value
    configured_file = (os.environ.get("ISYMOTRON_API_KEY_FILE")
                       if generic_override_applies else None)
    if configured_file:
        key_file = Path(configured_file).expanduser()
    else:
        provider = selected_provider
        key_env = {
            "openai": "OPENAI_API_KEY",
            "nvidia": "NVIDIA_NIM_API_KEY",
            "nebius": "NEBIUS_API_KEY",
            "ollama": "OLLAMA_API_KEY",
            "llamacpp": "LLAMACPP_API_KEY",
        }.get(provider)
        if not key_env:
            return ""
        provider_value = os.environ.get(key_env, "").strip()
        if provider_value:
            return provider_value

        if os.name == "nt":
            config_home = Path(
                os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
            ) / "isymotron"
        else:
            config_home = Path(
                os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
            ) / "isymotron"
        store_override = os.environ.get("ISYMOTRON_KEY_STORE")
        if store_override:
            store_path = Path(store_override).expanduser()
        else:
            store_path = config_home / "keys.env"
        try:
            for line in store_path.read_text(encoding="utf-8").splitlines():
                name, separator, stored = line.partition("=")
                if separator and name.strip() == key_env:
                    return stored.strip()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ConfigurationError(
                f"Could not read the IsyMotron key store: {exc}"
            ) from exc

        # Backwards compatibility with the original ISyCode NVIDIA key file.
        if provider == "nvidia":
            legacy_home = Path(
                os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
            )
            legacy_file = legacy_home / "isycode" / "NVAPI.txt"
            if not legacy_file.is_file():
                return ""
            key_file = legacy_file
        else:
            return ""

    try:
        value = key_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ConfigurationError(
            f"The configured API key file does not exist: {key_file}"
        ) from exc
    except OSError as exc:
        raise ConfigurationError(f"Could not read the configured API key file: {exc}") from exc

    if not value:
        raise ConfigurationError(f"The API key file is empty: {key_file}")
    return value


def key_store_path() -> Path:
    """Return the external IsyMotron key store used by the sibling runtime."""
    override = os.environ.get("ISYMOTRON_KEY_STORE")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "isymotron" / "keys.env"


def credential_state(provider_name: str) -> str:
    """Describe credential presence without exposing its value."""
    preset = _provider_preset(provider_name)
    if not preset.get("key_required", True):
        return "optional"
    key_env = preset["key_env"]
    generic_override_applies = (
        provider_name.casefold() == os.environ.get(
            "ISYMOTRON_PROVIDER", "nebius").casefold()
        and bool(os.environ.get("ISYMOTRON_API_KEY")))
    if os.environ.get(key_env) or generic_override_applies:
        return "environment"
    if (provider_name.casefold() == os.environ.get(
            "ISYMOTRON_PROVIDER", "nebius").casefold()
            and os.environ.get("ISYMOTRON_API_KEY_FILE")):
        try:
            if Path(os.environ["ISYMOTRON_API_KEY_FILE"]).expanduser().read_text(
                    encoding="utf-8").strip():
                return "environment"
        except FileNotFoundError:
            pass
        except OSError:
            return "unavailable"
    try:
        for line in key_store_path().read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == key_env and value.strip():
                return "stored"
    except FileNotFoundError:
        pass
    except OSError:
        return "unavailable"
    if provider_name == "nvidia":
        legacy = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        try:
            if (legacy / "isycode" / "NVAPI.txt").read_text(encoding="utf-8").strip():
                return "legacy"
        except (FileNotFoundError, OSError):
            pass
    return "missing"


def save_api_key(provider_name: str, value: str) -> Path:
    """Atomically store a provider key outside the repo with restrictive mode."""
    preset = _provider_preset(provider_name)
    if not preset.get("key_required", True):
        raise ConfigurationError(f"{provider_name} does not require an API key.")
    key_env = preset["key_env"]
    secret = value.strip()
    if not secret or "\n" in secret or "\r" in secret:
        raise ConfigurationError("Enter a non-empty single-line API key.")
    target = key_store_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.is_symlink():
            raise ConfigurationError("Refusing to replace a symbolic-link credential store.")
        try:
            existing = target.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            existing = []
        updated = []
        found = False
        for line in existing:
            name, separator, _ = line.partition("=")
            if separator and name.strip() == key_env:
                if not found:
                    updated.append(f"{key_env}={secret}")
                    found = True
            else:
                updated.append(line)
        if not found:
            updated.append(f"{key_env}={secret}")
        fd, temporary = tempfile.mkstemp(prefix=".keys-", dir=target.parent, text=True)
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("\n".join(updated) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            if os.name != "nt":
                target.chmod(0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except ConfigurationError:
        raise
    except OSError as exc:
        raise ConfigurationError("Could not save the key in IsyMotron's external store.") from exc
    return target


def _provider_preset(provider_name: str) -> dict:
    """Resolve provider metadata from the installed IsyMotron source."""
    try:
        from agents.provider import PRESETS
        return PRESETS[provider_name.casefold()]
    except (ImportError, KeyError) as exc:
        raise ConfigurationError(f"Unknown provider: {provider_name}") from exc
