"""Use the official grok CLI sign-in inside ISyCode.

The access token stays in ``~/.grok/auth.json``. This module reads it only to
send a chat request. It never returns the refresh token, and it never writes
the access token into the project, the journal, or preferences.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

ISSUER = "https://auth.x.ai"
SESSION_BASE = "https://cli-chat-proxy.grok.com/v1"
SESSION_HOST = "cli-chat-proxy.grok.com"
SESSION_MODEL = "grok-4.7"


def auth_file() -> Path:
    return Path.home() / ".grok" / "auth.json"


def grok_executable() -> str:
    candidate = os.environ.get("ISYCODE_GROK_EXECUTABLE") or shutil.which("grok")
    if not candidate:
        raise ValueError("Official grok CLI is not installed")
    path = Path(candidate).expanduser().resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("Official grok CLI is not executable")
    return str(path)


def _mode_path() -> Path:
    from isycode.workspace_setup import state_root
    directory = state_root() / "preferences"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory / "xai-auth.json"


def xai_auth_mode() -> str:
    """``session`` uses the grok CLI sign-in. Anything else stays on the API key."""
    try:
        from isycode.workspace_setup import state_root
        path = state_root() / "preferences" / "xai-auth.json"
        info = path.lstat()
    except (OSError, ValueError):
        return "api_key"
    if not path.is_file() or info.st_size > 4096:
        return "api_key"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "api_key"
    if isinstance(data, dict) and data.get("mode") == "session":
        return "session"
    return "api_key"


def set_xai_auth_mode(mode: str) -> None:
    if mode not in {"api_key", "session"}:
        raise ValueError("xAI auth mode is invalid")
    path = _mode_path()
    temporary = path.with_name(".xai-auth-" + os.urandom(4).hex() + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "mode": mode}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            path.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _expires(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _record() -> dict | None:
    path = auth_file()
    try:
        info = path.lstat()
    except OSError:
        return None
    if info.st_size > 65_536 or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    for item in data.values():
        if isinstance(item, dict) and item.get("oidc_issuer") == ISSUER:
            return item
    return None


def status() -> str:
    """``signed-in``, ``expired``, or ``missing``. Never includes credential text."""
    record = _record()
    if not isinstance(record, dict) or not isinstance(record.get("key"), str) or not record["key"]:
        return "missing"
    expires = _expires(record.get("expires_at"))
    if expires is None or expires <= datetime.now(timezone.utc):
        return "expired"
    return "signed-in"


def access_token() -> str:
    """The current access token, or empty. The refresh token is never read out."""
    if status() != "signed-in":
        return ""
    record = _record()
    key = record.get("key") if isinstance(record, dict) else ""
    return key if isinstance(key, str) else ""


def session_transport() -> str | None:
    """Chat base URL for a chosen Grok sign-in. API-key mode keeps api.x.ai."""
    if xai_auth_mode() == "session":
        return SESSION_BASE
    return None


async def run_login(method: str, on_line) -> int:
    """Run official ``grok login``. ``on_line`` sees status text, never a raw token."""
    import asyncio
    if method not in {"device", "browser"}:
        raise ValueError("unsupported grok login")
    flag = "--device-auth" if method == "device" else "--oauth"
    proc = await asyncio.create_subprocess_exec(
        grok_executable(), "login", flag,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE)

    async def _show() -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            shown = public_login_line(line.decode("utf-8", errors="replace"))
            if shown:
                on_line(shown)

    shower = asyncio.create_task(_show())
    try:
        code = await asyncio.wait_for(proc.wait(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        code = 1
    await shower
    return code


def public_login_line(line: str) -> str | None:
    """A grok login status line safe to show. Drops blank lines and bare tokens."""
    text = " ".join(line.replace("\x1b", "").split())
    if not text or len(text) > 240:
        return None
    if len(text) > 80 and " " not in text:
        return None
    return text
