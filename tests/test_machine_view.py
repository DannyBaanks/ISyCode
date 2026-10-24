"""GUS's machine view (ADR 0015): reads across the machine, never credentials."""
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from isycode.action_audit import ActionAuditJournal
from isycode.approvals import ActionApprovalStore
from isycode.gus_dispatch import GusToolDispatcher
from isycode.gus_l0 import gus_turn
from isycode.gus_roots import DEFAULT_SETTINGS, GusRoots, GusSettingsStore
from isycode.machine_view import (
    MAX_FILE_BYTES, MAX_LIST_ENTRIES, MAX_TURN_FILES, MachineView, denied_path,
    machine_budget, permitted_roots,
)
from isycode.workspace_setup import state_root
from test_gus_session import _checkout


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr("isycode.gus_roots.running_checkout", lambda: None)
    home = tmp_path / "home"
    home.mkdir()
    visible = tmp_path / "visible"
    visible.mkdir()
    scope = tmp_path / "scope"
    scope.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    return SimpleNamespace(tmp=tmp_path, home=home, visible=visible, scope=scope, outside=outside)


def _roots(visible, *, mode="folders", folders=(), consent=True, target=None):
    store = GusSettingsStore()
    settings = {**DEFAULT_SETTINGS,
                "read_scope": {"mode": mode, "folders": [str(folder) for folder in folders]},
                "target": str(target) if target is not None else None}
    data = (store.consent(settings, at="2026-10-24T00:00:00+00:00")
            if consent else settings)
    return GusRoots(visible, settings=store, data=data)


def _run(view, action_id, path, *, turn, query=None):
    arguments = {"path": str(path)}
    if query is not None:
        arguments["query"] = query
    with gus_turn(turn) if turn is not None else _no_turn():
        return view.execute(action_id, arguments)


class _no_turn:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def _read(world, *names, **roots_options):
    view = MachineView(_roots(world.visible, **roots_options))
    path = world.scope.joinpath(*names)
    return _run(view, "machine.files.read", path, turn=world.visible)


def test_a_file_inside_the_scope_is_read_with_a_receipt(world):
    (world.scope / "notes.txt").write_text("inside\n", encoding="utf-8")
    view = MachineView(_roots(world.visible, folders=[world.scope]))
    outcome = _run(view, "machine.files.read", world.scope / "notes.txt", turn=world.visible)
    assert outcome.decision == "ALLOW" and outcome.receipt is not None
    assert json.loads(outcome.text) == {"path": str(world.scope / "notes.txt"),
                                        "text": "inside\n"}
    assert ActionAuditJournal(world.scope).verify().receipts >= 1


def test_a_file_outside_the_consented_scope_is_denied(world):
    (world.outside / "secret.txt").write_text("outside\n", encoding="utf-8")
    view = MachineView(_roots(world.visible, folders=[world.scope]))
    for path in (world.outside / "secret.txt", world.tmp / "elsewhere.txt"):
        outcome = _run(view, "machine.files.read", path, turn=world.visible)
        assert outcome.decision == "DENY"
        assert "outside the consented machine scope" in outcome.reason


def test_credentials_and_private_stores_are_never_read_or_listed(world):
    secret = "sk-machine-not-real"
    targets = {
        ".env": f"OPENAI_API_KEY={secret}\n",
        "id_rsa": "-----BEGIN PRIVATE KEY-----\n",
        ".ssh/config": f"Host x\n# {secret}\n",
        ".aws/credentials": f"[default]\naws_secret_access_key={secret}\n",
        "login.keyring": secret,
        "vault.kdbx": secret,
        "Cookies": secret,
        ".bash_history": secret,
    }
    for relative, text in targets.items():
        path = world.scope / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (world.scope / "notes.txt").write_text("ordinary\n", encoding="utf-8")
    view = MachineView(_roots(world.visible, folders=[world.scope]))
    for relative, text in targets.items():
        outcome = _run(view, "machine.files.read", world.scope / relative, turn=world.visible)
        assert outcome.decision == "DENY", relative
        assert secret not in outcome.reason, relative
        assert secret not in (outcome.text or ""), relative
    listing = json.loads(_run(view, "machine.files.list", world.scope,
                               turn=world.visible).text)
    names = {entry["name"] for entry in listing["entries"]}
    assert "notes.txt" in names
    assert not names & {".env", "id_rsa", ".ssh", ".aws", "login.keyring", "vault.kdbx",
                        "Cookies", ".bash_history"}


def test_the_checkouts_own_isycode_folder_is_ordinary_project_data(world):
    (world.scope / ".isycode").mkdir()
    (world.scope / ".isycode" / "settings.toml").write_text("label = 'x'\n", encoding="utf-8")
    outcome = _read(world, ".isycode", "settings.toml", folders=[world.scope])
    assert outcome.decision == "ALLOW"
    assert "label" in json.loads(outcome.text)["text"]


def test_the_isycode_state_root_is_never_readable(world):
    state_file = Path(state_root()) / "ledger.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("{}\n", encoding="utf-8")
    view = MachineView(_roots(world.visible, mode="machine"))
    outcome = _run(view, "machine.files.read", state_file, turn=world.visible)
    assert outcome.decision == "DENY"
    assert "state directory" in outcome.reason


def test_symlinks_are_never_followed(world):
    (world.outside / "secret.txt").write_text("outside\n", encoding="utf-8")
    (world.scope / "inside.txt").write_text("inside\n", encoding="utf-8")
    (world.scope / "out-link.txt").symlink_to(world.outside / "secret.txt")
    (world.scope / "in-link.txt").symlink_to(world.scope / "inside.txt")
    for name in ("out-link.txt", "in-link.txt"):
        outcome = _read(world, name, folders=[world.scope])
        assert outcome.decision == "DENY", name
        assert "symlinks are not followed" in outcome.reason


def test_a_file_with_several_hard_links_is_refused(world):
    source = world.scope / "source.txt"
    source.write_text("linked\n", encoding="utf-8")
    os.link(source, world.scope / "second-name.txt")
    outcome = _read(world, "second-name.txt", folders=[world.scope])
    assert outcome.decision == "DENY"
    assert "hard link" in outcome.reason


def test_devices_pipes_directories_and_binaries_are_refused(world):
    fifo = world.scope / "pipe"
    try:
        os.mkfifo(fifo)
    except (AttributeError, OSError):
        fifo = None
    (world.scope / "binary.bin").write_bytes(b"\x00\x01\x02needle")
    (world.scope / "large.txt").write_text("a" * (MAX_FILE_BYTES + 1), encoding="utf-8")
    (world.scope / "folder").mkdir()
    (world.scope / "folder" / "inside.txt").write_text("x\n", encoding="utf-8")
    view = MachineView(_roots(world.visible, folders=[world.scope]))
    folder = _run(view, "machine.files.read", world.scope / "folder", turn=world.visible)
    assert folder.decision == "DENY" and "directory" in folder.reason
    binary = _run(view, "machine.files.read", world.scope / "binary.bin", turn=world.visible)
    assert binary.decision == "ERROR" and "binary" in binary.reason
    large = _run(view, "machine.files.read", world.scope / "large.txt", turn=world.visible)
    assert large.decision == "ERROR" and "256 KiB" in large.reason
    if fifo is not None:
        pipe = _run(view, "machine.files.read", fifo, turn=world.visible)
        assert pipe.decision == "DENY" and "pipes" in pipe.reason


def test_machine_reads_run_only_inside_a_gus_turn_and_with_consent(world):
    (world.scope / "notes.txt").write_text("inside\n", encoding="utf-8")
    consented = MachineView(_roots(world.visible, folders=[world.scope]))
    denied = _run(consented, "machine.files.read", world.scope / "notes.txt", turn=None)
    assert denied.decision == "DENY" and "GUS turn" in denied.reason

    unconsented = MachineView(_roots(world.visible, folders=[world.scope], consent=False))
    denied = _run(unconsented, "machine.files.read", world.scope / "notes.txt", turn=world.visible)
    assert denied.decision == "DENY" and "consent" in denied.reason


def test_machine_paths_must_be_absolute_and_bounded(world):
    (world.scope / "notes.txt").write_text("inside\n", encoding="utf-8")
    view = MachineView(_roots(world.visible, folders=[world.scope]))
    with gus_turn(world.visible):
        relative = view.execute("machine.files.read", {"path": "notes.txt"})
        huge = view.execute("machine.files.read", {"path": "/" + "a" * 5000})
    assert relative.decision == "DENY" and "absolute" in relative.reason
    assert huge.decision == "DENY" and "bounded" in huge.reason


def test_the_visible_workspace_and_the_target_stay_readable_outside_the_scope(world):
    (world.visible / "note.txt").write_text("visible\n", encoding="utf-8")
    target = world.tmp / "target"
    target.mkdir()
    (target / "code.py").write_text("print('t')\n", encoding="utf-8")
    roots = SimpleNamespace(visible=world.visible, target=target,
                            data={**DEFAULT_SETTINGS,
                                  "read_scope": {"mode": "folders",
                                                 "folders": [str(world.scope)]}},
                            consent_ready=lambda: True)
    view = MachineView(roots)
    assert str(target) in {str(root) for root in permitted_roots(roots.data,
                                                                 visible=world.visible,
                                                                 target=target)}
    for path, text in ((world.visible / "note.txt", "visible\n"),
                       (target / "code.py", "print('t')\n")):
        outcome = _run(view, "machine.files.read", path, turn=world.visible)
        assert outcome.decision == "ALLOW"
        assert json.loads(outcome.text)["text"] == text


def test_reads_are_budgeted_per_turn(world):
    files = []
    for index in range(MAX_TURN_FILES + 1):
        path = world.scope / f"file-{index}.txt"
        path.write_text(f"{index}\n", encoding="utf-8")
        files.append(path)
    view = MachineView(_roots(world.visible, folders=[world.scope]))
    with gus_turn(world.visible), machine_budget():
        for path in files[:MAX_TURN_FILES]:
            assert view.execute("machine.files.read", {"path": str(path)}).decision == "ALLOW"
        outcome = view.execute("machine.files.read", {"path": str(files[-1])})
    assert outcome.decision == "ERROR" and str(MAX_TURN_FILES) in outcome.reason


def test_the_turn_byte_budget_stops_whole_reads(world):
    size = 250_000
    files = []
    for index in range(9):
        path = world.scope / f"chunk-{index}.txt"
        path.write_text("a" * size, encoding="utf-8")
        files.append(path)
    view = MachineView(_roots(world.visible, folders=[world.scope]))
    with gus_turn(world.visible), machine_budget():
        outcomes = [view.execute("machine.files.read", {"path": str(path)})
                    for path in files[:8]]
        refused = view.execute("machine.files.read", {"path": str(files[8])})
    assert all(outcome.decision == "ALLOW" for outcome in outcomes)
    assert refused.decision == "ERROR" and "2 MiB" in refused.reason


def test_listing_is_bounded_and_grep_skips_private_and_dependency_folders(world):
    many = world.scope / "many"
    many.mkdir()
    for index in range(MAX_LIST_ENTRIES + 5):
        (many / f"entry-{index}.txt").write_text("", encoding="utf-8")
    text = world.scope / "text"
    text.mkdir()
    (text / "code.py").write_text("needle here\nsecond NEEDLE\n", encoding="utf-8")
    (text / ".env").write_text("needle=1\n", encoding="utf-8")
    (text / "node_modules").mkdir()
    (text / "node_modules" / "dep.js").write_text("needle\n", encoding="utf-8")
    (text / "report.txt").write_text("nothing\n", encoding="utf-8")
    view = MachineView(_roots(world.visible, folders=[world.scope]))

    listing = json.loads(_run(view, "machine.files.list", many, turn=world.visible).text)
    assert len(listing["entries"]) == MAX_LIST_ENTRIES and listing["truncated"] is True

    grep = json.loads(_run(view, "machine.files.grep", text, turn=world.visible,
                           query="needle").text)
    paths = {Path(match["path"]).name for match in grep["matches"]}
    assert paths == {"code.py"}
    assert [match["line"] for match in grep["matches"]] == [1, 2]
    assert grep["files_scanned"] == 2 and grep["truncated"] is False

    search = json.loads(_run(view, "machine.files.search", text, turn=world.visible,
                             query="report").text)
    assert [Path(match["path"]).name for match in search["matches"]] == ["report.txt"]
    assert all(Path(match["path"]).name not in {".env", "dep.js"} for match in search["matches"])


def test_another_users_home_is_refused_when_the_scope_is_the_machine():
    home = Path("/home/danny")
    assert "another user's home" in denied_path(
        Path("/home/someone-else/notes.txt"), (Path("/"),), home=home)
    assert denied_path(home / "notes.txt", (Path("/"),), home=home) is None
    assert denied_path(Path("/opt/data/notes.txt"), (Path("/"),), home=home) is None


def test_the_dispatcher_routes_machine_tools_to_the_machine_view(world):
    (world.scope / "notes.txt").write_text("from outside\n", encoding="utf-8")
    (world.scope / ".env").write_text("TOKEN=not-real\n", encoding="utf-8")
    target = _checkout(world.tmp / "isycode")
    store = GusSettingsStore()
    data = store.consent({**store.read(), "target": str(target),
                          "read_scope": {"mode": "folders",
                                         "folders": [str(world.scope)]}},
                         at="2026-10-24T00:00:00+00:00")
    roots = GusRoots(world.visible, settings=store, data=data)
    dispatcher = GusToolDispatcher(roots, ActionApprovalStore(), approve=None)

    def call(name, **arguments):
        return {"id": "call_1", "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)}}

    with gus_turn(target):
        _, output = asyncio.run(dispatcher(call("machine_read",
                                                path=str(world.scope / "notes.txt"))))
        assert json.loads(output)["text"] == "from outside\n"
        _, refused = asyncio.run(dispatcher(call("machine_read",
                                                 path=str(world.scope / ".env"))))
        _, outside = asyncio.run(dispatcher(call("machine_read",
                                                 path=str(world.outside / "secret.txt"))))
    assert json.loads(refused)["error"] == "ISyCode denied the call"
    assert json.loads(outside)["error"] == "ISyCode denied the call"


def test_the_settings_form_asks_before_widening_the_machine_scope(tmp_path, monkeypatch, capsys):
    """Pilot 120x40: a new read scope is machine access, so Save asks first."""
    from test_daily_tui import configure
    from textual.widgets import Input
    from isycode.tui import TUIApp
    from isycode.tui_screens_approval import ConfirmScreen
    from isycode.tui_screens_gus_settings import GusSettingsScreen

    configure(tmp_path, monkeypatch)
    external = tmp_path / "external"
    external.mkdir()

    async def until(pilot, condition, what):
        for _ in range(200):
            if condition():
                return
            await pilot.pause(0.05)
        raise AssertionError(f"timed out waiting for {what}")

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.wait_for_ready()
            task = asyncio.ensure_future(app._open_gus_settings())
            await until(pilot, lambda: isinstance(app.screen, GusSettingsScreen), "the settings form")
            form = app.screen
            form.query_one("#gus-scope-input", Input).value = str(external)
            await pilot.click("#gus-settings-save")
            await until(pilot, lambda: isinstance(app.screen, ConfirmScreen), "the scope prompt")
            copy = str(app.screen.query_one("#tailscale-confirm-copy Static").render())
            assert str(external) in copy
            app.screen.dismiss(True)
            await until(pilot, lambda: GusSettingsStore().read()["read_scope"] == {
                "mode": "folders", "folders": [str(external)]}, "the saved scope")
            assert form.query_one("#gus-scope-input").region.width > 0
            form.dismiss(None)
            await task

    with capsys.disabled():
        asyncio.run(scenario())


def test_a_scripted_gus_turn_reads_outside_the_workspace_and_refuses_env(
        tmp_path, monkeypatch, capsys):
    """Pilot 80x24: GUS reads a machine file through its tools and never returns .env."""
    from test_daily_tui import configure
    from test_gus_work import _call, _committed_repo, _scripted, _settings_target
    from isycode.gus_session import GusState
    from isycode.providers import record_model_metadata, save_model_slot
    from isycode.tui import TUIApp

    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n")
    record_model_metadata("openai", "gus-fixture", {"context_length": 200_000})
    save_model_slot("gus", "openai", "gus-fixture")
    external = tmp_path / "external"
    external.mkdir()
    (external / "note.txt").write_text("outside hello\n", encoding="utf-8")
    (external / ".env").write_text("OPENAI_API_KEY=sk-not-real\n", encoding="utf-8")
    steps = [
        {"text": "", "tool_calls": [
            _call("machine_read", "c1", path=str(external / "note.txt")),
            _call("machine_read", "c2", path=str(external / ".env"))]},
        {"text": "Read the note; .env is refused.", "tool_calls": []},
    ]
    seen = []
    monkeypatch.setattr("isycode.chat_transport.provider_complete", _scripted(steps, seen))

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.wait_for_ready()
            root = app._workspace_root
            _checkout(root)
            _committed_repo(root)
            _settings_target(root)
            store = GusSettingsStore()
            data = store.read()
            store.consent({**data, "read_scope": {"mode": "folders",
                                                  "folders": [str(external)]}},
                          at="2026-10-24T00:00:00+00:00")
            GusState(root).enable()
            reply, report = await app._run_gus_turn("read my note", GusState(root))
            assert reply.text.startswith("Read the note")
            outputs = [message["content"] for message in seen[-1][0]
                       if message.get("role") == "tool"]
            assert "outside hello" in outputs[0]
            assert "ISyCode denied the call" in outputs[1] and "sk-not-real" not in outputs[1]
            assert report == {"changed": [], "l0": [], "l0_still": []}

    with capsys.disabled():
        asyncio.run(scenario())
