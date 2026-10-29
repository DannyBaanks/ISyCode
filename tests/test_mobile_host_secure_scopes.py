import hashlib
import json
import sqlite3
import time

import pytest

import asyncio
import urllib.request

from isycode.approvals import ActionApprovalStore
from isycode.mobile_host import ApiKeyStore, MobileHostOwner, MobileHostStatus, PAIR_SCOPES
from isycode.workspace_authority import WorkspaceAuthority


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


def test_mobile_host_owner_requires_scoped_grant_and_single_use_approval(tmp_path):
    class FakeHost:
        bind = "127.0.0.1"
        port = 8765
        _pair_authorizer = None

        async def start(self):
            return MobileHostStatus("ready", self.bind, self.port, False, None, ())

        async def stop(self):
            return None

    authority = WorkspaceAuthority(tmp_path, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    owner = MobileHostOwner(tmp_path, authority, approvals, host=FakeHost())
    request = owner.start_request()
    confirmation = approvals.issue(request, ttl_seconds=30)

    allowed, _ = asyncio.run(owner.authorize_and_launch(confirmation))
    assert allowed is False

    authority.set_grant("mobile.host.start", enabled=True,
                        network_hosts=["127.0.0.1:8765"])
    authority.set_grant("mobile.pair", enabled=True, targets=["mobile-host"])
    confirmation = approvals.issue(request, ttl_seconds=30)
    allowed, _ = asyncio.run(owner.authorize_and_launch(confirmation))

    assert allowed is True
    assert owner.authorize_pair("a" * 64, "Test phone") is True
    assert owner.authorize_pair("not-a-digest", "Test phone") is False


def test_mobile_host_owner_rejects_non_loopback_configuration(tmp_path):
    class FakeHost:
        bind = "0.0.0.0"
        port = 8765
        _pair_authorizer = None

        async def start(self):
            raise AssertionError("unsafe configuration must fail before start")

    authority = WorkspaceAuthority(tmp_path, state_directory=tmp_path / "authority")
    owner = MobileHostOwner(tmp_path, authority, ActionApprovalStore(), host=FakeHost())
    request = owner.start_request()
    authority.set_grant("mobile.host.start", enabled=True,
                        network_hosts=["127.0.0.1:8765"])
    approval = ActionApprovalStore().issue(request, ttl_seconds=30)

    allowed, reason = asyncio.run(owner.authorize_and_launch(approval))

    assert allowed is False
    assert "loopback" in reason


def test_mobile_host_start_receipt_failure_stops_listener(tmp_path, monkeypatch):
    class FakeHost:
        bind = "127.0.0.1"
        port = 8765
        stopped = False

        async def start(self):
            return MobileHostStatus("ready", self.bind, self.port, False, None, ())

        async def stop(self):
            self.stopped = True

    authority = WorkspaceAuthority(tmp_path, state_directory=tmp_path / "authority")
    authority.set_grant("mobile.host.start", enabled=True,
                        network_hosts=["127.0.0.1:8765"])
    approvals = ActionApprovalStore()
    host = FakeHost()
    owner = MobileHostOwner(tmp_path, authority, approvals, host=host)
    monkeypatch.setattr(owner.gate, "persist_receipt", lambda *_: False)
    approval = approvals.issue(owner.start_request(), ttl_seconds=30)

    allowed, reason = asyncio.run(owner.authorize_and_launch(approval))

    assert allowed is False
    assert "receipt" in reason
    assert host.stopped is True


def test_mobile_host_prefixed_health_and_pair_exchange_are_loopback_only(
        tmp_path, monkeypatch):
    import json
    from isycode.mobile_host import MobileHost

    monkeypatch.setenv("ISYCODE_MOBILE_HOST_BIND", "127.0.0.1")
    monkeypatch.setenv("ISYCODE_MOBILE_HOST_PORT", "0")
    authorizations = []
    host = MobileHost(key_store=ApiKeyStore(tmp_path / "host.sqlite3"),
                      pair_authorizer=lambda digest, name: authorizations.append(
                          (digest, name)) or True)
    host._pair_recorder = lambda *args: True

    async def scenario():
        status = await host.start()
        try:
            url = f"http://127.0.0.1:{status.port}/isycode/v1/health"
            response = await asyncio.to_thread(urllib.request.urlopen, url)
            assert response.status == 200
            assert json.loads(response.read()) == {
                "service": "isycode-mobile-host", "version": 1, "state": "ready"}

            code = host.pairing_code_for_local_settings()
            body = json.dumps({"code": code, "device_name": "Disposable phone"}).encode()
            request = urllib.request.Request(
                f"http://127.0.0.1:{status.port}/isycode/v1/pair/exchange", data=body,
                headers={"Content-Type": "application/json"})
            paired = await asyncio.to_thread(urllib.request.urlopen, request)
            result = json.loads(paired.read())
            assert paired.status == 201
            assert set(result["scopes"]) == set(PAIR_SCOPES)
            assert len(authorizations) == 1
            assert len(authorizations[0][0]) == 64
            assert authorizations[0][0] != hashlib.sha256(code.encode()).hexdigest()
            assert authorizations[0][1] == "Disposable phone"
            assert host.pairing_code_for_local_settings() is None
        finally:
            await host.stop()

    asyncio.run(scenario())
