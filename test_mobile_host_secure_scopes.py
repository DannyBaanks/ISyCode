import hashlib
import json
import sqlite3
import time

import pytest

from isycode.mobile_host import ApiKeyStore, PAIR_SCOPES


def test_secure_mobile_credentials_cannot_be_issued_with_unimplemented_scopes(tmp_path):
    store = ApiKeyStore(tmp_path / "keystore.sqlite3")

    with pytest.raises(ValueError, match="unknown or empty scope set"):
        store.issue("wide-key", scopes=frozenset({"files:write"}))


def test_pairing_credentials_have_only_the_narrow_mobile_scopes(tmp_path):
    store = ApiKeyStore(tmp_path / "keystore.sqlite3")
    key_id, raw_key, _ = store.issue("paired device")

    credential = store.authenticate(raw_key)
    metadata = store.list_metadata()

    assert credential is not None
    assert credential["id"] == key_id
    assert credential["scopes"] == PAIR_SCOPES
    assert not credential["scopes"] & {"files:read", "files:write", "session:create",
                                        "session:read", "session:write", "session:approve"}
    assert metadata[0]["id"] == key_id
    assert "digest" not in metadata[0]
    assert raw_key not in repr(metadata)


def test_secure_authentication_rejects_a_legacy_broad_scope_credential(tmp_path):
    database = tmp_path / "keystore.sqlite3"
    store = ApiKeyStore(database)
    raw_key = "isy_legacy_broad_scope_test"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO api_keys VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
            ("key_legacy", "legacy", hashlib.sha256(raw_key.encode()).hexdigest(),
             json.dumps(["files:write", "session:create"]), json.dumps(["*"]),
             time.time(), time.time() + 3600),
        )

    assert store.authenticate(raw_key) is None


def test_secure_mobile_key_revocation_is_immediate_and_idempotent(tmp_path):
    store = ApiKeyStore(tmp_path / "keystore.sqlite3")
    key_id, raw_key, _ = store.issue("revocable device")

    assert store.authenticate(raw_key) is not None
    assert store.revoke(key_id) is True
    assert store.authenticate(raw_key) is None
    assert store.revoke(key_id) is False


def test_secure_mobile_key_expiry_is_enforced_at_authentication(tmp_path, monkeypatch):
    import isycode.mobile_host as mobile_host_module

    now = 10_000.0
    monkeypatch.setattr(mobile_host_module.time, "time", lambda: now)
    store = ApiKeyStore(tmp_path / "keystore.sqlite3")
    _, raw_key, expires_at = store.issue("short lived device", ttl_seconds=60)
    assert store.authenticate(raw_key) is not None

    now = expires_at + 1

    assert store.authenticate(raw_key) is None
