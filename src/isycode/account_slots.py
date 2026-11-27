"""Multi-account slot registry and quota-aware switching for ISyCode logins.

Inspired by agy-dash's multi-account vault: each subscription provider
(``antigravity``, ``chatgpt``, ``grok``) supports multiple isolated account
slots (``primary``, ``pro2``, ``pro3``, ...).

Security invariants:
- Never stores OAuth tokens, refresh tokens, cookies, API keys, or login URLs.
- Only non-secret metadata (slot name, label, plan/email label, auth state,
  sanitized quota numbers, timestamps) is persisted in ``registry.json`` (0600).
- ``primary`` preserves the original single-account directory so existing
  sign-ins keep working without migration.
- Isolated slots live under ``state_root()/accounts/<provider>-slots/<slot>``
  so credentials never collide across subscriptions.
- Deletion refuses ``primary``, requires ``confirmed=True``, and unlinks
  symlinks without ever descending outside the slot directory.
"""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any, Callable

from isycode.platform_storage import storage
from isycode.workspace_setup import state_root

MULTI_ACCOUNT_PROVIDERS: tuple[str, ...] = ("antigravity", "chatgpt", "claude", "grok")
PRIMARY_SLOT = "primary"
QUOTA_WARN_PCT = 20.0
QUOTA_CRIT_PCT = 5.0
_SLOT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")


def validate_slot_name(slot: str) -> str:
    """Normalize and validate an account slot identifier (1..24 safe ASCII chars)."""
    if not isinstance(slot, str):
        raise ValueError("Account slot name must be text")
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", slot.strip().lower()).strip("-")
    if not clean or not _SLOT_RE.fullmatch(clean):
        raise ValueError(f"Invalid account slot name: {slot!r}")
    return clean


def _validate_provider(provider: str) -> str:
    clean = (provider or "").strip().casefold()
    if clean == "xai":
        clean = "grok"
    if clean not in MULTI_ACCOUNT_PROVIDERS:
        raise ValueError(f"Unsupported multi-account provider: {provider!r}")
    return clean


def _clean_text(value: Any, limit: int = 80) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = " ".join(ch for ch in value.strip() if ord(ch) >= 32 and ord(ch) != 127)
    # collapse runs of whitespace properly
    cleaned = " ".join(value.replace("\x7f", " ").split())
    cleaned = "".join(ch for ch in cleaned if ord(ch) >= 32)
    return cleaned[:limit]


def registry_path() -> Path:
    return (state_root() / "accounts" / "registry.json").absolute()


def _slots_root(provider: str) -> Path:
    prov = _validate_provider(provider)
    folder = {
        "antigravity": "antigravity-slots",
        "chatgpt": "chatgpt-codex-slots",
        "claude": "claude-code-slots",
        "grok": "grok-slots",
    }[prov]
    return (state_root() / "accounts" / folder).absolute()


def slot_home(provider: str, slot: str | None = None, *, path: Path | None = None) -> Path:
    """Return the dedicated home directory for ``(provider, slot)``."""
    prov = _validate_provider(provider)
    resolved_slot = validate_slot_name(slot) if slot is not None else active_slot(prov, path=path)
    if resolved_slot == PRIMARY_SLOT:
        if prov == "antigravity":
            return (state_root() / "accounts" / "antigravity").absolute()
        if prov == "chatgpt":
            return (state_root() / "accounts" / "chatgpt-codex").absolute()
        if prov == "claude":
            return (state_root() / "accounts" / "claude-code").absolute()
        return Path.home().absolute()
    return (_slots_root(prov) / resolved_slot).absolute()


@contextmanager
def _file_lock(target: Path):
    storage.ensure_directory(target.parent, repair=True)
    lock_path = target.with_name(target.name + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.name == "posix":
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "posix":
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
    if target.is_symlink():
        raise ValueError("Account registry path must not be a symlink")
    storage.ensure_directory(target.parent, repair=True)
    temporary = target.parent / (".registry-" + secrets.token_hex(8) + ".tmp")
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        storage.protect(temporary)
        storage.replace(temporary, target)
        storage.sync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _default_primary_entry() -> dict[str, Any]:
    return {
        "slot": PRIMARY_SLOT,
        "label": "Primary",
        "plan": "",
        "email": "",
        "authenticated": False,
        "quota": {},
        "updated_at": "",
    }


def _normalize_provider_bucket(raw: Any) -> dict[str, Any]:
    bucket = raw if isinstance(raw, dict) else {}
    accounts_raw = bucket.get("accounts")
    accounts: dict[str, dict[str, Any]] = {}
    if isinstance(accounts_raw, dict):
        for raw_slot, raw_entry in accounts_raw.items():
            try:
                safe = validate_slot_name(str(raw_slot))
            except ValueError:
                continue
            entry = raw_entry if isinstance(raw_entry, dict) else {}
            quota = entry.get("quota") if isinstance(entry.get("quota"), dict) else {}
            accounts[safe] = {
                "slot": safe,
                "label": _clean_text(entry.get("label"), 64) or ("Primary" if safe == PRIMARY_SLOT else safe),
                "plan": _clean_text(entry.get("plan"), 80),
                "email": _clean_text(entry.get("email"), 120),
                "authenticated": bool(entry.get("authenticated", False)),
                "quota": quota,
                "updated_at": _clean_text(entry.get("updated_at"), 40),
            }
    if PRIMARY_SLOT not in accounts:
        accounts[PRIMARY_SLOT] = _default_primary_entry()
    raw_active = bucket.get("active_slot")
    try:
        act = validate_slot_name(str(raw_active)) if raw_active else PRIMARY_SLOT
    except ValueError:
        act = PRIMARY_SLOT
    if act not in accounts:
        act = PRIMARY_SLOT
    return {"active_slot": act, "accounts": accounts}


def load_registry(path: Path | None = None) -> dict[str, Any]:
    """Load non-secret multi-account registry, seeding ``primary`` for each provider."""
    reg_file = path or registry_path()
    raw: dict[str, Any] = {}
    try:
        if reg_file.is_file() and not reg_file.is_symlink() and reg_file.stat().st_size <= 512_000:
            parsed = json.loads(reg_file.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                raw = parsed
    except (OSError, UnicodeError, json.JSONDecodeError):
        raw = {}

    providers_raw = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
    providers = {
        prov: _normalize_provider_bucket(providers_raw.get(prov))
        for prov in MULTI_ACCOUNT_PROVIDERS
    }
    return {"version": 1, "providers": providers}


def save_registry(data: dict[str, Any], path: Path | None = None) -> None:
    """Persist sanitized multi-account metadata atomically with 0600 permissions."""
    reg_file = path or registry_path()
    providers_raw = data.get("providers") if isinstance(data, dict) else {}
    sanitized = {
        "version": 1,
        "providers": {
            prov: _normalize_provider_bucket(
                providers_raw.get(prov) if isinstance(providers_raw, dict) else {}
            )
            for prov in MULTI_ACCOUNT_PROVIDERS
        },
    }
    _atomic_write_json(reg_file, sanitized)


def update_registry(mutate: Callable[[dict[str, Any]], None], path: Path | None = None) -> dict[str, Any]:
    """Reload, mutate, and atomically save the account registry under a file lock."""
    reg_file = path or registry_path()
    with _file_lock(reg_file):
        reg = load_registry(path=reg_file)
        mutate(reg)
        save_registry(reg, path=reg_file)
        return load_registry(path=reg_file)


def active_slot(provider: str, *, path: Path | None = None) -> str:
    prov = _validate_provider(provider)
    reg = load_registry(path=path)
    return reg["providers"][prov]["active_slot"]


def set_active_slot(provider: str, slot: str, *, path: Path | None = None) -> str:
    prov = _validate_provider(provider)
    safe = validate_slot_name(slot)

    def _mutate(reg: dict[str, Any]) -> None:
        bucket = reg["providers"][prov]
        if safe not in bucket["accounts"]:
            raise ValueError(f"Account slot {safe!r} does not exist for {prov}")
        bucket["active_slot"] = safe

    update_registry(_mutate, path=path)
    return safe


def list_accounts(provider: str, *, path: Path | None = None) -> list[dict[str, Any]]:
    prov = _validate_provider(provider)
    reg = load_registry(path=path)
    bucket = reg["providers"][prov]
    act = bucket["active_slot"]
    ordered_keys = [PRIMARY_SLOT] + sorted(k for k in bucket["accounts"] if k != PRIMARY_SLOT)
    items: list[dict[str, Any]] = []
    for key in ordered_keys:
        entry = dict(bucket["accounts"][key])
        entry["active"] = (key == act)
        items.append(entry)
    return items


def next_suggested_slot(provider: str, *, path: Path | None = None) -> str:
    prov = _validate_provider(provider)
    reg = load_registry(path=path)
    existing = set(reg["providers"][prov]["accounts"])
    index = 2
    while f"pro{index}" in existing:
        index += 1
    return f"pro{index}"


def add_account_slot(provider: str, slot: str, *, label: str = "", path: Path | None = None) -> dict[str, Any]:
    """Register a new isolated account slot and create its private directory."""
    prov = _validate_provider(provider)
    safe = validate_slot_name(slot)
    if safe == PRIMARY_SLOT:
        raise ValueError("Cannot add duplicate 'primary' slot")
    clean_label = _clean_text(label, 64) or safe

    def _mutate(reg: dict[str, Any]) -> None:
        accounts = reg["providers"][prov]["accounts"]
        if safe in accounts:
            raise ValueError(f"Account slot {safe!r} already exists for {prov}")
        accounts[safe] = {
            "slot": safe,
            "label": clean_label,
            "plan": "",
            "email": "",
            "authenticated": False,
            "quota": {},
            "updated_at": "",
        }

    reg = update_registry(_mutate, path=path)
    storage.ensure_directory(slot_home(prov, safe, path=path), repair=True)
    return dict(reg["providers"][prov]["accounts"][safe])


def record_account_auth(
    provider: str,
    slot: str,
    *,
    authenticated: bool,
    plan: str | None = None,
    email: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Update non-secret auth status/plan metadata after a verified login or logout."""
    prov = _validate_provider(provider)
    safe = validate_slot_name(slot)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _mutate(reg: dict[str, Any]) -> None:
        accounts = reg["providers"][prov]["accounts"]
        if safe not in accounts:
            accounts[safe] = {
                "slot": safe,
                "label": "Primary" if safe == PRIMARY_SLOT else safe,
                "plan": "",
                "email": "",
                "authenticated": False,
                "quota": {},
                "updated_at": "",
            }
        entry = accounts[safe]
        entry["authenticated"] = bool(authenticated)
        if plan is not None:
            entry["plan"] = _clean_text(plan, 80)
        if email is not None:
            entry["email"] = _clean_text(email, 120)
        if not authenticated:
            entry["quota"] = {}
        entry["updated_at"] = now

    reg = update_registry(_mutate, path=path)
    return dict(reg["providers"][prov]["accounts"][safe])


def record_account_quota(
    provider: str,
    slot: str,
    quota: dict[str, Any],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Store sanitized quota numbers (never credentials) for an account slot."""
    prov = _validate_provider(provider)
    safe = validate_slot_name(slot)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_quota = {
        "ok": bool(quota.get("ok")),
        "families": quota.get("families") if isinstance(quota.get("families"), dict) else {},
        "min_pct": quota.get("min_pct"),
        "updated_at": _clean_text(quota.get("updated_at"), 40) or now,
    }

    def _mutate(reg: dict[str, Any]) -> None:
        accounts = reg["providers"][prov]["accounts"]
        if safe not in accounts:
            return
        entry = accounts[safe]
        entry["quota"] = safe_quota
        if safe_quota["ok"]:
            entry["authenticated"] = True
        entry["updated_at"] = now

    reg = update_registry(_mutate, path=path)
    return dict(reg["providers"][prov]["accounts"].get(safe, {}))


def _slot_family_pct(entry: dict[str, Any], family: str) -> float | None:
    quota = entry.get("quota")
    if not isinstance(quota, dict) or not quota.get("ok"):
        return None
    families = quota.get("families")
    if isinstance(families, dict):
        fam_entry = families.get(family) or families.get("gemini")
        if isinstance(fam_entry, dict):
            values = [
                float(bucket["pct"])
                for win in ("5h", "weekly")
                for bucket in (fam_entry.get(win),)
                if isinstance(bucket, dict) and isinstance(bucket.get("pct"), (int, float))
            ]
            if values:
                return min(values)
    min_pct = quota.get("min_pct")
    return float(min_pct) if isinstance(min_pct, (int, float)) else None


def choose_best_account(
    provider: str,
    current_slot: str | None = None,
    *,
    model_name: str = "",
    path: Path | None = None,
) -> str:
    """Pick another authenticated slot with the highest remaining quota for ``model_name``."""
    prov = _validate_provider(provider)
    reg = load_registry(path=path)
    bucket = reg["providers"][prov]
    cur = validate_slot_name(current_slot) if current_slot else bucket["active_slot"]
    accounts = bucket["accounts"]
    cur_email = str(accounts.get(cur, {}).get("email", "")).strip().lower()

    family = "gemini"
    if prov == "antigravity" and model_name:
        from isycode.antigravity_connector import model_to_quota_family
        family = model_to_quota_family(model_name)

    best_slot = ""
    best_score = -2.0
    for sname, sdata in accounts.items():
        if sname == cur or not sdata.get("authenticated", False):
            continue
        other_email = str(sdata.get("email", "")).strip().lower()
        if cur_email and other_email and other_email == cur_email:
            continue
        pct = _slot_family_pct(sdata, family)
        score = pct if pct is not None else -0.5
        if score > best_score:
            best_score = score
            best_slot = sname
    return best_slot


def compute_quota_alert(
    provider: str,
    *,
    model_name: str = "",
    warn_pct: float = QUOTA_WARN_PCT,
    crit_pct: float = QUOTA_CRIT_PCT,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Return a quota alert dict when the active slot is low, suggesting the best alternative slot."""
    prov = _validate_provider(provider)
    reg = load_registry(path=path)
    bucket = reg["providers"][prov]
    cur_slot = bucket["active_slot"]
    cur = bucket["accounts"].get(cur_slot)
    if not cur:
        return None
    family = "gemini"
    if prov == "antigravity" and model_name:
        from isycode.antigravity_connector import model_to_quota_family
        family = model_to_quota_family(model_name)
    pct = _slot_family_pct(cur, family)
    if pct is None or pct > warn_pct:
        return None
    target = choose_best_account(prov, cur_slot, model_name=model_name, path=path)
    target_pct = _slot_family_pct(bucket["accounts"][target], family) if target else None
    return {
        "level": "CRITICAL" if pct <= crit_pct else "WARN",
        "provider": prov,
        "active_slot": cur_slot,
        "family": family,
        "pct": pct,
        "target_slot": target,
        "target_pct": target_pct,
    }


def _purge_isolated_slot_dir(provider: str, slot: str) -> tuple[int, int]:
    """Delete only local files inside an isolated slot directory; never follow symlinks."""
    safe = validate_slot_name(slot)
    if safe == PRIMARY_SLOT:
        raise ValueError("Refusing to purge primary account slot")
    slots_root = _slots_root(provider).resolve(strict=False)
    target_dir = (slots_root / safe).resolve(strict=False)
    if not target_dir.is_relative_to(slots_root) or target_dir == slots_root:
        raise ValueError("Refusing to delete path outside isolated slots root")
    if not target_dir.exists() and not target_dir.is_symlink():
        return (0, 0)
    if target_dir.is_symlink():
        target_dir.unlink()
        return (0, 1)

    files_deleted = 0
    symlinks_unlinked = 0
    for root_str, dirnames, filenames in os.walk(target_dir, topdown=False, followlinks=False):
        rp = Path(root_str).resolve(strict=False)
        if not rp.is_relative_to(target_dir):
            continue
        for fname in filenames:
            fp = rp / fname
            if fp.is_symlink():
                fp.unlink()
                symlinks_unlinked += 1
            elif fp.parent.resolve(strict=False).is_relative_to(target_dir):
                try:
                    fp.chmod(0o600)
                except OSError:
                    pass
                fp.unlink()
                files_deleted += 1
        for dname in dirnames:
            dp = rp / dname
            if dp.is_symlink():
                dp.unlink()
                symlinks_unlinked += 1
            elif dp.is_dir() and dp.resolve(strict=False).is_relative_to(target_dir):
                try:
                    dp.rmdir()
                except OSError:
                    pass
    try:
        target_dir.rmdir()
    except OSError:
        pass
    return (files_deleted, symlinks_unlinked)


def remove_account_slot(
    provider: str,
    slot: str,
    *,
    confirmed: bool = False,
    purge_local: bool = True,
    path: Path | None = None,
) -> tuple[bool, str]:
    """Remove an isolated account slot after explicit confirmation; never removes ``primary``."""
    prov = _validate_provider(provider)
    safe = validate_slot_name(slot)
    if safe == PRIMARY_SLOT:
        return False, "The primary account slot cannot be removed; disconnect it instead."
    reg = load_registry(path=path)
    if safe not in reg["providers"][prov]["accounts"]:
        return False, f"Account slot [{safe}] is not registered for {prov}."
    if not confirmed:
        return False, f"Explicit confirmation is required to remove [{safe}]."

    if purge_local:
        _purge_isolated_slot_dir(prov, safe)

    def _mutate(data: dict[str, Any]) -> None:
        bucket = data["providers"][prov]
        bucket["accounts"].pop(safe, None)
        if bucket.get("active_slot") == safe:
            bucket["active_slot"] = PRIMARY_SLOT

    update_registry(_mutate, path=path)
    return True, f"Removed isolated account slot [{safe}] for {prov}."


__all__ = [
    "MULTI_ACCOUNT_PROVIDERS",
    "PRIMARY_SLOT",
    "QUOTA_CRIT_PCT",
    "QUOTA_WARN_PCT",
    "active_slot",
    "add_account_slot",
    "choose_best_account",
    "compute_quota_alert",
    "list_accounts",
    "load_registry",
    "next_suggested_slot",
    "record_account_auth",
    "record_account_quota",
    "registry_path",
    "remove_account_slot",
    "save_registry",
    "set_active_slot",
    "slot_home",
    "update_registry",
    "validate_slot_name",
]
