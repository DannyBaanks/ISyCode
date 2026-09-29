import json
import os
import stat
from dataclasses import replace

import pytest

from isycode.private_access import OwnedServeRoute, PrivateAccessStateStore


def route():
    return OwnedServeRoute(
        route_id="gateway-main",
        host="host.tailnet.ts.net",
        path="/",
        target="http://127.0.0.1:8787",
        created_at="2026-09-29T12:00:00Z",
        last_verified_status="online",
    )


def test_missing_file_recovers_as_empty_state(tmp_path):
    store = PrivateAccessStateStore(tmp_path / "state")
    state = store.load()
    assert state.owned_routes == ()
    store.record_owned_route(route())
    assert store.load().owned_routes == (route(),)
    store.clear_owned_route("gateway-main")
    assert store.load().owned_routes == ()


def test_atomic_creation_and_replacement(tmp_path):
    store = PrivateAccessStateStore(tmp_path / "state")
    store.record_owned_route(route())
    assert store.load().owned_routes == (route(),)
    assert not list(store.state_directory.glob("*.tmp"))
    store.record_owned_route(replace(route(), last_verified_status="offline"))
    assert store.load().owned_routes[0].last_verified_status == "offline"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_state_directory_and_file_permissions_are_private(tmp_path):
    store = PrivateAccessStateStore(tmp_path / "state")
    store.record_owned_route(route())
    assert stat.S_IMODE(store.state_directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.state_path.stat().st_mode) == 0o600


def test_symlink_state_file_is_rejected(tmp_path):
    store = PrivateAccessStateStore(tmp_path / "state")
    target = tmp_path / "other"
    target.write_text("{}")
    store.state_path.symlink_to(target)
    with pytest.raises(ValueError):
        store.load()


@pytest.mark.parametrize("payload", ["{", "[]", "{}" + " " * 300000])
def test_malformed_or_oversized_state_is_rejected(tmp_path, payload):
    store = PrivateAccessStateStore(tmp_path / "state")
    store.state_path.write_text(payload)
    with pytest.raises(ValueError):
        store.load()


@pytest.mark.parametrize("mutate", [
    lambda data: data.update(owner="someone-else"),
    lambda data: data.update(version=999),
    lambda data: data["routes"][0].update(auth_url="https://login.tailscale.com/a"),
])
def test_wrong_owner_version_and_secret_fields_are_rejected(tmp_path, mutate):
    store = PrivateAccessStateStore(tmp_path / "state")
    store.record_owned_route(route())
    data = json.loads(store.state_path.read_text())
    mutate(data)
    store.state_path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        store.load()


def test_route_count_limit_is_enforced_before_write(tmp_path):
    store = PrivateAccessStateStore(tmp_path / "state")
    for index in range(8):
        store.record_owned_route(replace(route(), route_id=f"gateway-{index}"))
    before = store.state_path.read_bytes()
    with pytest.raises(ValueError):
        store.record_owned_route(replace(route(), route_id="gateway-ninth"))
    assert store.state_path.read_bytes() == before
    assert len(store.load().owned_routes) == 8


def test_encoded_size_limit_is_enforced_before_replace(tmp_path, monkeypatch):
    store = PrivateAccessStateStore(tmp_path / "state")
    store.record_owned_route(route())
    before = store.state_path.read_bytes()
    monkeypatch.setattr(store, "MAX_BYTES", len(before) - 1)
    with pytest.raises(ValueError):
        store.record_owned_route(replace(route(), last_verified_status="offline"))
    assert store.state_path.read_bytes() == before
    monkeypatch.undo()
    assert store.load().owned_routes == (route(),)


def test_symlinked_parent_directory_is_rejected(tmp_path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    link = tmp_path / "linked-parent"
    link.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ValueError):
        PrivateAccessStateStore(link / "state")
    assert not (real_parent / "state").exists()


def test_failed_atomic_replace_preserves_existing_state(tmp_path, monkeypatch):
    store = PrivateAccessStateStore(tmp_path / "state")
    store.record_owned_route(route())
    before = store.state_path.read_bytes()
    def fail_replace(*_args):
        raise OSError("injected replacement failure")
    monkeypatch.setattr("isycode.private_access.os.replace", fail_replace)
    with pytest.raises(OSError):
        store.record_owned_route(replace(route(), last_verified_status="offline"))
    assert store.state_path.read_bytes() == before
    monkeypatch.undo()
    assert store.load().owned_routes == (route(),)


def test_wrong_adapter_version_is_rejected(tmp_path):
    store = PrivateAccessStateStore(tmp_path / "state")
    store.record_owned_route(route())
    data = json.loads(store.state_path.read_text())
    data["adapter_version"] = 2
    store.state_path.write_text(json.dumps(data))
    store.state_path.chmod(0o600)
    with pytest.raises(ValueError):
        store.load()
