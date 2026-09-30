"""Named API-key vault backed by the operating system credential store."""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any


def _vault_path() -> Path:
    state_root = os.environ.get("XDG_STATE_HOME")
    root = Path(state_root).expanduser() if state_root else Path.home() / ".local" / "state"
    return root / "isycode" / "credentials.sqlite3"


class CredentialVault:
    """Keep labels in a private DB and secret values in the OS keyring."""

    def __init__(self, path: Path | None = None):
        self.path = path or _vault_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ValueError("Refusing to open a symbolic-link credential vault")
        if os.name != "nt":
            self.path.parent.chmod(0o700)
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR | nofollow, 0o600)
            os.close(fd)
        try:
            import keyring
            from keyring.backends.fail import Keyring as FailKeyring

            self._keyring = keyring.get_keyring()
            backend_priority = getattr(type(self._keyring), "priority", 0)
            children = getattr(self._keyring, "backends", ())
            if isinstance(self._keyring, FailKeyring) or backend_priority <= 0 or any(
                    getattr(type(child), "priority", 0) <= 0 for child in children):
                raise CredentialVaultError("No secure OS keyring backend is available")
        except CredentialVaultError:
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            # Native keyring backends can fail below Python: a broken
            # cryptography/pyo3 binding raises PanicException, which derives
            # from BaseException. Treat any backend load failure as "no secure
            # keyring" so callers fail closed instead of crashing the TUI.
            raise CredentialVaultError("Could not open the operating system keyring") from exc
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS credentials (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                service TEXT NOT NULL,
                purpose TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                revoked_at REAL
            )""")
        self._secure_file()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def _secure_file(self) -> None:
        if os.name != "nt" and self.path.exists():
            self.path.chmod(0o600)

    @staticmethod
    def _validate_label(value: str, field: str) -> str:
        value = " ".join(value.split()) if isinstance(value, str) else ""
        if not 1 <= len(value) <= 96 or any(ord(ch) < 32 for ch in value):
            raise ValueError(f"{field} must contain 1-96 printable characters")
        return value

    def add(self, name: str, service: str, purpose: str, secret: str) -> str:
        name = self._validate_label(name, "name")
        service = self._validate_label(service, "service").casefold()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.:-]{0,63}", service):
            raise ValueError("service id must use 1-64 letters, digits, dot, underscore, colon, or hyphen")
        purpose = self._validate_label(purpose, "purpose")
        if not isinstance(secret, str) or not secret.strip() or "\n" in secret or "\r" in secret:
            raise ValueError("API key must be a non-empty single-line value")
        if len(secret) > 16_384:
            raise ValueError("API key is too long")
        key_id = "cred_" + secrets.token_hex(8)
        now = time.time()
        try:
            self._keyring.set_password("isycode.api-key", key_id, secret.strip())
            with self._connect() as db:
                db.execute(
                    "INSERT INTO credentials VALUES (?, ?, ?, ?, ?, ?, NULL)",
                    (key_id, name, service, purpose, now, now),
                )
        except Exception as exc:
            try:
                self._keyring.delete_password("isycode.api-key", key_id)
            except Exception:
                pass
            raise CredentialVaultError("Could not save the API key to the OS keyring") from exc
        self._secure_file()
        return key_id

    def list_metadata(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,name,service,purpose,created_at,updated_at,revoked_at "
                "FROM credentials ORDER BY created_at DESC"
            ).fetchall()
        return [{
            "id": row["id"], "name": row["name"], "service": row["service"],
            "purpose": row["purpose"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "revoked": row["revoked_at"] is not None,
        } for row in rows]

    def get_secret(self, key_id: str) -> str | None:
        if not isinstance(key_id, str) or not re.fullmatch(r"cred_[a-f0-9]{16}", key_id):
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT id FROM credentials WHERE id=? AND revoked_at IS NULL",
                (key_id,),
            ).fetchone()
        if not row:
            return None
        try:
            return self._keyring.get_password("isycode.api-key", key_id)
        except Exception as exc:
            raise CredentialVaultError("Could not read the API key from the OS keyring") from exc

    def latest_secret_for_service(self, service: str) -> str | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT id FROM credentials WHERE service=? AND revoked_at IS NULL "
                "ORDER BY created_at DESC LIMIT 1", (service,),
            ).fetchone()
        if not row:
            return None
        try:
            return self._keyring.get_password("isycode.api-key", row["id"])
        except Exception as exc:
            raise CredentialVaultError("Could not read the API key from the OS keyring") from exc

    def revoke(self, key_id: str) -> bool:
        if not isinstance(key_id, str) or not re.fullmatch(r"cred_[a-f0-9]{16}", key_id):
            return False
        with self._connect() as db:
            row = db.execute(
                "SELECT id FROM credentials WHERE id=? AND revoked_at IS NULL", (key_id,)
            ).fetchone()
        if not row:
            return False
        try:
            self._keyring.delete_password("isycode.api-key", key_id)
        except Exception as exc:
            raise CredentialVaultError("Could not revoke the API key in the OS keyring") from exc
        with self._connect() as db:
            result = db.execute(
                "UPDATE credentials SET revoked_at=?,updated_at=? WHERE id=? AND revoked_at IS NULL",
                (time.time(), time.time(), key_id),
            )
        self._secure_file()
        return result.rowcount == 1


class CredentialVaultError(RuntimeError):
    """The native credential store is unavailable or rejected an operation."""
