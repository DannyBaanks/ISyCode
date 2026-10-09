"""M15 is closed by evidence: every former UNWIRED primitive is owner-only or unreachable."""
import asyncio
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from isycode import action_coverage
from isycode.action_runtime import OWNER_ACTIONS
from isycode.mobile_host import ApiKeyStore, MobileHost


# ── The scanner that keeps M15 closed ─────────────────────────────────
def test_scanner_finds_hidden_callers_through_types_not_names(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "sneaky.py").write_text('''
from isycode.chat_sessions import ChatSessionStore
from isycode.mobile_host import ApiKeyStore
from isycode.bridge import BridgeClient

class Holder:
    def __init__(self, root):
        self.store = ChatSessionStore(root)          # generic name, typed by assignment

    @property
    def vault(self) -> ApiKeyStore:                  # typed by return annotation
        return ApiKeyStore()

    def go(self, sid, other: "ChatSessionStore"):    # typed by parameter annotation
        self.store.rename(sid, "x")
        self.vault.issue("x")
        other.fork(sid)
        BridgeClient("agent").hello()
''', encoding="utf-8")
    found = {item["callsite"].rsplit(":", 1)[0] + " " + item["reason"].split()[0]
             for item in action_coverage.primitive_caller_violations(package)}
    assert found == {"sneaky.Holder.go ChatSessionStore.rename", "sneaky.Holder.go ApiKeyStore.issue",
                     "sneaky.Holder.go ChatSessionStore.fork", "sneaky.Holder.go BridgeClient.__init__"}


def test_scanner_sees_exactly_the_reviewed_product_callers(monkeypatch):
    monkeypatch.setattr(action_coverage, "PRIMITIVE_CALLERS",
                        {key: frozenset() for key in action_coverage.PRIMITIVE_CALLERS})
    seen = {item["callsite"].rsplit(":", 1)[0] for item in action_coverage.primitive_caller_violations()}
    # Seen (so the scanner is not blind) and allowed by the real table.
    assert seen == {"mobile_host.MobileHost._pair", "workspace_memory.WorkspaceMemoryOwner.execute"}


def test_product_has_no_unreviewed_primitive_caller():
    assert action_coverage.primitive_caller_violations() == []


def test_every_covered_callsite_names_an_owner_that_owns_its_action():
    for action, callsite, owner, status in action_coverage.KNOWN_EFFECT_CALLSITES:
        if status in {"COVERED", "COVERED_VARIANT"}:
            assert owner and action in OWNER_ACTIONS.get(owner, ()), (action, callsite, owner)


# ── ApiKeyStore.issue/revoke only behind mobile.pair ──────────────────
def _pair(monkeypatch, tmp_path, *, authorizer, recorder):
    monkeypatch.setenv("ISYCODE_MOBILE_HOST_BIND", "127.0.0.1")
    monkeypatch.setenv("ISYCODE_MOBILE_HOST_PORT", "0")
    keys = ApiKeyStore(tmp_path / "keys.sqlite3")
    host = MobileHost(key_store=keys, pair_authorizer=authorizer)
    host._pair_recorder = recorder

    async def scenario():
        status = await host.start()
        try:
            body = json.dumps({"code": host.pairing_code_for_local_settings(),
                               "device_name": "phone"}).encode()
            request = urllib.request.Request(
                f"http://127.0.0.1:{status.port}/isycode/v1/pair/exchange", data=body,
                headers={"Content-Type": "application/json"})
            try:
                response = await asyncio.to_thread(urllib.request.urlopen, request)
                return response.status
            except urllib.error.HTTPError as error:
                return error.code
        finally:
            await host.stop()

    return asyncio.run(scenario()), keys.list_metadata()


@pytest.mark.parametrize("authorizer", [None, lambda challenge, name: False])
def test_no_pairing_key_is_minted_without_the_owner_authorizing_mobile_pair(
        tmp_path, monkeypatch, authorizer):
    status, keys = _pair(monkeypatch, tmp_path, authorizer=authorizer, recorder=lambda *a: True)
    assert status == 403 and keys == []


def test_a_minted_key_is_revoked_when_the_pairing_receipt_cannot_be_recorded(tmp_path, monkeypatch):
    status, keys = _pair(monkeypatch, tmp_path, authorizer=lambda challenge, name: True,
                         recorder=lambda *a: False)
    assert status == 503
    assert keys and all(item["revoked"] for item in keys)  # minted, then rolled back


def test_an_authorized_pairing_mints_exactly_one_key(tmp_path, monkeypatch):
    status, keys = _pair(monkeypatch, tmp_path, authorizer=lambda challenge, name: True,
                         recorder=lambda *a: True)
    assert status == 201 and len(keys) == 1


# ── ChatSessionsScreen goes through the owner ─────────────────────────
def test_sessions_screen_forks_through_the_owner_and_the_journal(tmp_path, monkeypatch, capsys):
    from textual.app import App
    from textual.widgets import OptionList

    from isycode.action_audit import ActionAuditJournal
    from isycode.session_owner import ChatSessionOwner
    from isycode.tui_screens_sessions import ChatSessionsScreen
    from isycode.workspace_authority import WorkspaceAuthority

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root)
    authority.set_mode("classic")
    owner = ChatSessionOwner(root, authority, tmp_path / "sessions")
    _, sid = owner.record(None, "user", "Original question")
    before = ActionAuditJournal(root).verify().receipts
    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(ChatSessionsScreen(owner), results.append)

    async def scenario():
        async with Host().run_test() as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            screen.query_one("#sessions-list", OptionList).highlighted = 0
            await pilot.click("#sessions-fork")
            for _ in range(20):
                await pilot.pause(0.05)
                if results:
                    break

    with capsys.disabled():
        asyncio.run(scenario())
    child = results[0]
    assert child and child != sid
    assert owner.resume(child)[1].messages[0]["content"] == "Original question"
    assert ActionAuditJournal(root).verify().receipts > before  # fork + reads are journaled
    source = Path(action_coverage.__file__).with_name("tui_screens_sessions.py").read_text()
    screen_source = source.split("class ChatSessionsScreen")[1].split("\nclass ")[0]
    assert "session_store" not in screen_source and "ChatSessionStore" not in screen_source
