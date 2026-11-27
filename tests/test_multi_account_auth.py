"""Tests for the Antigravity OAuth fix and unified agy-dash-style multi-account slots."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import stat

import pytest

from isycode.account_slots import (
    PRIMARY_SLOT,
    active_slot,
    add_account_slot,
    choose_best_account,
    compute_quota_alert,
    list_accounts,
    next_suggested_slot,
    record_account_auth,
    record_account_quota,
    registry_path,
    remove_account_slot,
    set_active_slot,
    slot_home,
    validate_slot_name,
)
from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import GrokAuthSystembility, ProviderAuthSystembility
from isycode.antigravity_connector import AntigravityConnector
from isycode.approvals import ActionApprovalStore
from isycode.grok_auth import GrokAuthOwner
from isycode.grok_session import access_token, auth_file_for_slot, run_login, status as grok_status
from isycode.provider_auth import (
    ANTIGRAVITY_AUTH_HOSTS,
    AUTH_HOSTS,
    ProviderAuthOwner,
)
from isycode.providers import Provider
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


def _isolated_state(tmp_path: Path, monkeypatch) -> Path:
    state = tmp_path / "state"
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(state))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    return state


def _fake_exe(tmp_path: Path, name: str) -> Path:
    exe = tmp_path / name
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o700)
    return exe.resolve()


# ── Antigravity OAuth environment fix ───────────────────────────────────

@pytest.mark.skipif(os.name == "nt", reason="POSIX D-Bus & DISPLAY isolation")
def test_antigravity_env_isolates_dbus_and_provides_display_for_oauth_capture(tmp_path, monkeypatch):
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    fake_agy = _fake_exe(tmp_path, "agy")
    home = tmp_path / "slot-home"

    # Normal inference/quota mode: D-Bus isolated, no browser allowed, no DISPLAY needed.
    conn_normal = AntigravityConnector(str(fake_agy), home, allow_browser_capture=False)
    conn_normal._prepare_home()
    env_normal = conn_normal._environment()
    assert env_normal["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/nonexistent"
    assert env_normal["AGY_NO_BROWSER"] == "1"
    assert "DISPLAY" not in env_normal

    # OAuth browser capture mode: D-Bus still isolated (so each slot is independent),
    # and DISPLAY is set so `agy acp --stdio` emits the Google OAuth URL to the shim.
    conn_login = AntigravityConnector(str(fake_agy), home, allow_browser_capture=True)
    conn_login._prepare_home()
    conn_login._extra_path_dir = home / ".capture-bin"
    env_login = conn_login._environment()
    assert env_login["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/nonexistent"
    assert env_login["DISPLAY"] == ":0"
    assert "AGY_NO_BROWSER" not in env_login


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fake script")
def test_antigravity_close_during_pending_login_does_not_deadlock(tmp_path):
    """Cancelling or closing while authenticate RPC is pending must exit promptly."""
    script = tmp_path / "fake_agy_hang_auth.py"
    py = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else "/usr/bin/env python3"
    script.write_text(
        f"#!{py}\n"
        "import json, os, subprocess, sys\n"
        "for raw in sys.stdin:\n"
        "    msg = json.loads(raw)\n"
        "    if msg.get('method') == 'initialize':\n"
        "        sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'protocolVersion':1,'agentCapabilities':{}}}) + '\\n')\n"
        "        sys.stdout.flush()\n"
        "    elif msg.get('method') == 'authenticate':\n"
        "        b = os.environ.get('BROWSER', '')\n"
        "        if b:\n"
        "            subprocess.run([b, 'https://accounts.google.com/o/oauth2/auth?state=pend'], check=False)\n"
        "        # Keep authenticate pending until closed, just like real browser OAuth.\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    home = tmp_path / "managed-home"

    async def scenario():
        async with AntigravityConnector(str(script), home, timeout_s=15.0, allow_browser_capture=True) as conn:
            ch = await conn.start_login("browser")
            assert ch["url"].startswith("https://accounts.google.com/o/oauth2/auth")
            # Exiting the context manager cancels pending _login_task without deadlocking close().

    asyncio.run(asyncio.wait_for(scenario(), timeout=5.0))


# ── Multi-account slot registry (agy-dash style) ────────────────────────

def test_slot_registry_lifecycle_quota_selection_and_safe_removal(tmp_path, monkeypatch):
    _isolated_state(tmp_path, monkeypatch)

    assert validate_slot_name("Pro 2!") == "pro-2"
    with pytest.raises(ValueError):
        validate_slot_name("   ")

    # Primary seeded automatically and keeps original directory paths.
    assert active_slot("antigravity") == PRIMARY_SLOT
    assert slot_home("antigravity", PRIMARY_SLOT).name == "antigravity"
    assert slot_home("chatgpt", PRIMARY_SLOT).name == "chatgpt-codex"
    assert next_suggested_slot("antigravity") == "pro2"

    added = add_account_slot("antigravity", "pro2", label="Trabajo Pro")
    assert added["slot"] == "pro2"
    assert next_suggested_slot("antigravity") == "pro3"
    assert slot_home("antigravity", "pro2").parent.name == "antigravity-slots"

    if os.name == "posix":
        mode = stat.S_IMODE(registry_path().stat().st_mode)
        assert mode == 0o600

    # Record auth & quota across two accounts and test quota alert + best-slot routing.
    record_account_auth("antigravity", PRIMARY_SLOT, authenticated=True, plan="Pro", email="one@example.invalid")
    record_account_auth("antigravity", "pro2", authenticated=True, plan="Ultra", email="two@example.invalid")
    record_account_quota("antigravity", PRIMARY_SLOT, {
        "ok": True,
        "families": {"gemini": {"5h": {"pct": 4.0, "reset_time": ""}, "weekly": {"pct": 50.0, "reset_time": ""}}},
        "min_pct": 4.0,
    })
    record_account_quota("antigravity", "pro2", {
        "ok": True,
        "families": {"gemini": {"5h": {"pct": 92.0, "reset_time": ""}, "weekly": {"pct": 88.0, "reset_time": ""}}},
        "min_pct": 88.0,
    })

    assert choose_best_account("antigravity", PRIMARY_SLOT, model_name="gemini-4-neon-high") == "pro2"
    alert = compute_quota_alert("antigravity", model_name="gemini-4-neon-high")
    assert alert is not None
    assert alert["level"] == "CRITICAL"
    assert alert["target_slot"] == "pro2"
    assert alert["target_pct"] == 88.0

    set_active_slot("antigravity", "pro2")
    assert active_slot("antigravity") == "pro2"
    accounts = list_accounts("antigravity")
    assert [a["slot"] for a in accounts] == ["primary", "pro2"]
    assert accounts[1]["active"] is True

    # Removal refuses primary and unconfirmed requests, and never follows symlinks outside slot.
    ok, _ = remove_account_slot("antigravity", PRIMARY_SLOT, confirmed=True)
    assert not ok
    ok, _ = remove_account_slot("antigravity", "pro2", confirmed=False)
    assert not ok

    outside_file = tmp_path / "do_not_delete.txt"
    outside_file.write_text("precious user data", encoding="utf-8")
    pro2_dir = slot_home("antigravity", "pro2")
    (pro2_dir / "local.txt").write_text("local", encoding="utf-8")
    if os.name != "nt":
        (pro2_dir / "ext_link").symlink_to(outside_file)

    ok, _ = remove_account_slot("antigravity", "pro2", confirmed=True)
    assert ok
    assert active_slot("antigravity") == PRIMARY_SLOT
    assert outside_file.exists() and outside_file.read_text(encoding="utf-8") == "precious user data"
    assert not pro2_dir.exists()


# ── Sentinel boundary & Owners for Antigravity, ChatGPT, and Grok ───────

@pytest.mark.parametrize("provider,hosts", [
    ("antigravity", ANTIGRAVITY_AUTH_HOSTS),
    ("chatgpt", AUTH_HOSTS),
])
def test_provider_auth_owner_and_sentinel_support_isolated_slots(tmp_path, monkeypatch, provider, hosts):
    _isolated_state(tmp_path, monkeypatch)
    root = tmp_path / "workspace"
    root.mkdir()
    exe = _fake_exe(tmp_path, "agy" if provider == "antigravity" else "codex")
    monkeypatch.setenv("ISYCODE_AGY_EXECUTABLE" if provider == "antigravity" else "ISYCODE_CODEX_EXECUTABLE", str(exe))

    add_account_slot(provider, "pro2")
    authority = WorkspaceAuthority(root)
    approvals = ActionApprovalStore()

    seen_homes: list[Path] = []

    class FakeConnector:
        def __init__(self, executable, home, **kwargs):
            seen_homes.append(Path(home))
        async def __aenter__(self): return self
        async def start_login(self, method):
            url = ("https://accounts.google.com/o/oauth2/auth?state=ok"
                   if provider == "antigravity" else "https://auth.openai.com/oauth/authorize")
            return {"method": method, "login_id": "id_pro2", "url": url, "provider": provider}
        async def wait_login(self, login_id): return True
        async def account(self): return {"authenticated": True, "method": provider, "plan": "Pro-2"}
        async def logout(self): return None
        async def close(self): return None

    owner = ProviderAuthOwner(
        root, authority, approvals, executable=str(exe),
        connector_factory=FakeConnector, provider=provider, slot="pro2",
    )
    req = owner.request("login", "browser", slot="pro2")
    ident = req.parameters["connector"]
    assert ident["account_slot"] == "pro2"
    assert Path(ident["home"]) == slot_home(provider, "pro2")
    assert ProviderAuthSystembility.identity_valid(ident, target=provider) is True

    # Tampered slot / mismatched home must be denied by Sentinel.
    bad_ident = dict(ident, home=str(slot_home(provider, PRIMARY_SLOT)))
    assert ProviderAuthSystembility.identity_valid(bad_ident, target=provider) is False
    bad_primary = dict(ident, account_slot="primary")
    assert ProviderAuthSystembility.identity_valid(bad_primary, target=provider) is False

    authority.set_grant("provider.authenticate", enabled=True, targets=[provider],
                        executables=[str(exe)], network_hosts=list(hosts))

    async def run():
        out, ch = await owner.begin(req, approvals.issue(req, ttl_seconds=30))
        assert out.decision == "ALLOW" and ch is not None
        fin, acct = await owner.finish()
        assert fin.decision == "ALLOW" and acct["slot"] == "pro2"
        assert seen_homes == [slot_home(provider, "pro2")]
        assert ActionAuditJournal(root).verify().status == "PASS"

    asyncio.run(run())

    # Switching active slot updates Provider.connector_identity seamlessly.
    set_active_slot(provider, "pro2")
    prov = Provider(name=provider, model="auto")
    assert prov.connector_identity["account_slot"] == "pro2"
    assert Path(prov.connector_identity["home"]) == slot_home(provider, "pro2")


def test_grok_multi_account_isolation_auth_owner_and_token_switch(tmp_path, monkeypatch):
    _isolated_state(tmp_path, monkeypatch)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    root = tmp_path / "workspace"
    root.mkdir()
    exe = _fake_exe(tmp_path, "grok")
    monkeypatch.setenv("ISYCODE_GROK_EXECUTABLE", str(exe))

    add_account_slot("grok", "pro2")

    def write_grok_auth(slot: str, token_val: str) -> None:
        p = auth_file_for_slot(slot)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"https://auth.x.ai::client": {
            "key": token_val, "refresh_token": "stay-private",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "oidc_issuer": "https://auth.x.ai", "auth_mode": "oidc",
        }}), encoding="utf-8")

    write_grok_auth(PRIMARY_SLOT, "tok-primary")
    write_grok_auth("pro2", "tok-pro2")

    assert grok_status(PRIMARY_SLOT) == "signed-in"
    assert grok_status("pro2") == "signed-in"
    assert access_token() == "tok-primary"
    set_active_slot("grok", "pro2")
    assert access_token() == "tok-pro2"
    set_active_slot("grok", PRIMARY_SLOT)
    assert access_token() == "tok-primary"

    # GrokAuthSystembility accepts valid isolated slot and rejects traversal.
    authority = WorkspaceAuthority(root)
    approvals = ActionApprovalStore()
    owner = GrokAuthOwner(root, authority, approvals, slot="pro2")
    req = owner.request("browser", slot="pro2")
    assert req.parameters["slot"] == "pro2"
    assert GrokAuthSystembility().evaluate(req, None).passed is True

    bad_req = ActionRequest(
        "grok.login", root, "grok",
        {"executable": str(exe.resolve()), "operation": "login", "method": "browser", "slot": "../evil"},
        execution_owner="grok_auth",
    )
    assert GrokAuthSystembility().evaluate(bad_req, None).passed is False

    # run_login with isolated slot passes HOME=<slot_home> to the subprocess.
    captured_env: list[dict] = []

    class _Stderr:
        async def readline(self): return b""

    class _Proc:
        stderr = _Stderr()
        async def wait(self): return 0

    async def fake_exec(*args, **kwargs):
        captured_env.append(kwargs.get("env") or {})
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    code = asyncio.run(run_login("browser", lambda line: None, executable=str(exe.resolve()), slot="pro2"))
    assert code == 0
    assert captured_env and Path(captured_env[0]["HOME"]) == slot_home("grok", "pro2")


# ── TUI /accounts command & dialogs at 80x24 ────────────────────────────

def test_tui_accounts_command_and_slot_screen_at_80x24(tmp_path, monkeypatch, capsys):
    from test_daily_tui import configure
    from isycode.provider_auth_screens import AccountSlotScreen
    from isycode.tui import TUIApp

    configure(tmp_path, monkeypatch)
    add_account_slot("antigravity", "pro2")
    monkeypatch.setenv("ISYCODE_PROVIDER", "antigravity")

    async def run():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()

            # 1. /accounts opens Antigravity accounts menu showing primary and pro2.
            _, cmd, arg = app._plugins.route("/accounts")
            assert cmd is not None
            await cmd.handler(app, arg)
            assert app._menu_mode == "account_slots"
            values = [e.get("value") for e in app._menu_entries]
            assert "antigravity:primary" in values
            assert "antigravity:pro2" in values
            assert any(e.get("kind") == "account_slot_add" for e in app._menu_entries)
            assert any(e.get("kind") == "account_slot_remove" and e.get("value") == "antigravity:pro2"
                       for e in app._menu_entries)

            # 2. `/accounts use pro2` switches active slot immediately and reflects in status.
            _, cmd, arg = app._plugins.route("/accounts use pro2")
            await cmd.handler(app, arg)
            assert active_slot("antigravity") == "pro2"
            assert "[pro2]" in app._usage_status_text()

            # 3. AccountSlotScreen fits cleanly in 80x24 and returns typed slot name.
            screen = AccountSlotScreen("Google Antigravity", suggested="pro3")
            result_task = asyncio.create_task(app._await_screen(screen))
            await pilot.pause()
            btn = screen.query_one("#account-slot-save")
            assert btn.region.bottom <= 24
            # Activate the real button by keyboard; a click during modal layout
            # can miss its target on the Windows runner.
            btn.focus()
            await pilot.press("enter")
            chosen = await asyncio.wait_for(result_task, 5)
            assert chosen == "pro3"

            # 4. All three auth menus and the provider selector expose the multi-account manager.
            app._open_provider_menu()
            assert any(e["kind"] == "account_slots_open" and e["value"] == "antigravity" for e in app._menu_entries[:4])
            assert any(e["kind"] == "account_slots_open" and e["value"] == "" for e in app._menu_entries[:4])
            app._open_antigravity_auth_methods()
            assert any(e["kind"] == "account_slots_open" and e["value"] == "antigravity" for e in app._menu_entries)
            app._open_auth_methods()
            assert any(e["kind"] == "account_slots_open" and e["value"] == "chatgpt" for e in app._menu_entries)
            app._open_xai_auth_methods()
            assert any(e["kind"] == "account_slots_open" and e["value"] == "grok" for e in app._menu_entries)

            # 5. Scoped ModelsScreen for Antigravity exposes the Accounts button.
            from isycode.tui_screens_harness import ModelsScreen
            ms = ModelsScreen(
                [{"kind": "model", "value": "antigravity|gemini-4-neon-medium", "label": "Gemini 4 Neon Medium"}],
                provider_scope="antigravity",
            )
            ms_task = asyncio.create_task(app._await_screen(ms))
            await pilot.pause()
            acct_btn = ms.query_one("#models-accounts")
            assert "[pro2]" in str(acct_btn.label)
            acct_btn.press()
            res = await asyncio.wait_for(ms_task, 5)
            assert res == {"kind": "account_slots_open", "value": "antigravity"}

    with capsys.disabled():
        asyncio.run(run())
