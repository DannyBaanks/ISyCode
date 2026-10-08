"""The side rail shows IsySentinel's live decisions and active permissions; it decides nothing."""
import asyncio

from isycode import action_audit
from isycode.action_audit import add_decision_listener, remove_decision_listener
from isycode.action_runtime import LocalWorkspaceReadOwner
from isycode.sentinel_rail import SentinelFeed, active_permissions, render
from isycode.tui import TUIApp, plain_text
from isycode.user_defaults import UserDefaultsStore
from isycode.workspace_authority import WorkspaceAuthority


def record(action, verdict, failed=(), approval=None, **extra):
    body = {"kind": "decision", "time": 1_700_000_000.0, "action": action,
            "authority": verdict == "ALLOW", "sentinel": verdict, "failed_checks": list(failed)}
    if approval:
        body["approval"] = approval
    return {**body, **extra}


# ── Presentation ───────────────────────────────────────────────────────
def test_only_grants_sentinel_would_accept_are_shown_as_active():
    policy = {"mode": "security", "grants": {
        "workspace.files.read": {"enabled": True},
        "workspace.files.list": {"enabled": True},          # same Settings label: listed once
        "workspace.command.run": {"enabled": False},        # explicit denial
        "no.such.action": {"enabled": True},                # no Secure owner: never active
    }}
    assert active_permissions(policy) == [("Read and search workspace files", True)]
    policy["grants"]["workspace.files.search"] = {"enabled": False}   # one of the three denied
    assert active_permissions(policy) == [("Read and search workspace files", False)]


def test_decisions_show_verdict_failed_checks_and_who_approved_newest_first():
    feed = SentinelFeed()
    feed.add(record("workspace.files.read", "ALLOW"))
    feed.add(record("workspace.command.run", "DENY", failed=["Authority", "Approval"]))
    feed.add(record("workspace.files.write", "ALLOW", approval="user"))
    body, title = render(feed, {"mode": "classic", "grants": {}}, trusted=True)
    text = body.plain
    assert title == "IsySentinel · 2 allow · 1 deny"
    assert "Mode · Classic · trusted folder" in text
    assert "deny · Authority, Approval" in text and "allow · you approved" in text
    assert text.index("workspace.files.write") < text.index("workspace.files.read")


def test_nothing_but_journal_fields_reaches_the_rail():
    feed = SentinelFeed()
    feed.add(record("workspace.files.read", "ALLOW", parameters={"path": "secret/.env"},
                    target="/home/x/secret", prompt="leak me"))
    text = render(feed, None)[0].plain
    assert "secret" not in text and "leak me" not in text
    assert "Permissions" in text and "unavailable" in text.lower()   # no policy: nothing assumed


def test_a_malformed_record_is_ignored():
    feed = SentinelFeed()
    feed.add({"kind": "receipt", "action": "x"})
    feed.add({"action": None})
    feed.add("not a record")
    assert not feed.recent and feed.allowed == feed.denied == 0


# ── The journal observer ───────────────────────────────────────────────
def test_the_journal_tells_observers_after_writing_and_a_broken_observer_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "w"
    root.mkdir()
    (root / "a.txt").write_text("hi")
    authority = WorkspaceAuthority(root)
    authority.set_mode("security")
    seen = []

    def broken(_record):
        raise RuntimeError("observer bug")

    add_decision_listener(broken)
    add_decision_listener(seen.append)
    try:
        owner = LocalWorkspaceReadOwner(root, authority)
        assert owner.execute("workspace.files.read", {"path": "a.txt"}).decision == "DENY"
        authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[str(root.resolve())])
        assert owner.execute("workspace.files.read", {"path": "a.txt"}).decision == "ALLOW"
    finally:
        remove_decision_listener(broken)
        remove_decision_listener(seen.append)
    assert [(r["action"], r["sentinel"]) for r in seen] == [
        ("workspace.files.read", "DENY"), ("workspace.files.read", "ALLOW")]
    assert "parameters" not in seen[0] and "a.txt" not in str(seen)
    seen[0]["sentinel"] = "ALLOW"                      # observers get a copy
    report = action_audit.ActionAuditJournal(root).verify()
    assert report.status == "PASS" and report.decisions == 2


# ── In the TUI ─────────────────────────────────────────────────────────
def test_the_rail_updates_live_and_reports_the_journal(tmp_path, monkeypatch, capsys):
    from test_daily_tui import configure
    root = configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace="recurring")
    (root / "a.txt").write_text("hi")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause()
            for _ in range(40):
                await pilot.pause(0.05)
                if app._sentinel_feed.journal:
                    break
            authority = WorkspaceAuthority(root)
            authority.set_grant("workspace.files.read", enabled=False)   # explicit denial
            owner = LocalWorkspaceReadOwner(root, authority)
            await asyncio.to_thread(owner.execute, "workspace.files.read", {"path": "a.txt"})
            await pilot.pause(0.2)
            section = app.query_one("#rail-sentinel")
            shown = plain_text(app.query_one("#sentinel-status"))
            assert "workspace.files.read" in shown and "deny" in shown
            assert "Mode · Classic" in shown and "Active permissions" in shown
            lines = shown.splitlines()
            label = lines.index("✓ Read and search workspace files")
            assert "partial" in lines[label + 1]                         # the denial stays visible
            assert "credentials.add" not in shown                        # readable labels, not ids
            assert "Journal ·" in shown
            assert "1 Deny" in section.title or "1 deny" in section.title
        assert app._on_journal_decision not in action_audit._decision_listeners

    with capsys.disabled():
        asyncio.run(scenario())
