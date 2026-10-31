"""Every approval opens on its refusing action, even with a long scrolling body (freeze fix)."""
import asyncio
import inspect

from textual.app import App
from textual.widgets import Button

from isycode import tui_screens_approval
from isycode.tui_screens_approval import ApprovalScreen, ConfirmScreen


def test_the_whole_approval_family_auto_focuses_its_first_button():
    assert ApprovalScreen.AUTO_FOCUS == "Button"
    family = [cls for _, cls in inspect.getmembers(tui_screens_approval, inspect.isclass)
              if issubclass(cls, ApprovalScreen) and cls is not ApprovalScreen]
    assert len(family) >= 9
    for cls in family:
        # A subclass names its own refusing button, never falls back to the app default.
        assert cls.AUTO_FOCUS not in (None, "*"), cls.__name__
        assert cls.AUTO_FOCUS.startswith("#"), (cls.__name__, cls.AUTO_FOCUS)


def test_a_long_approval_opens_on_reject_and_enter_refuses():
    results = []

    class Host(App):
        def on_mount(self):
            body = "\n".join(f"line {index} of a long review" for index in range(200))
            self.push_screen(ConfirmScreen("Allow this?", body, "Allow"), results.append)

    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            for _ in range(40):
                await pilot.pause(0.05)
                if isinstance(pilot.app.screen.focused, Button):
                    break
            screen = pilot.app.screen
            assert screen.focused is screen.query(Button).first()
            await pilot.press("enter")
            for _ in range(40):
                if results:
                    break
                await pilot.pause(0.05)
            assert results == [False]

    asyncio.run(scenario())


def test_escape_refuses_on_a_bare_approval_screen():
    """The family docstring promises Esc refuses; a bare subclass must inherit it."""
    from textual.widgets import Static

    results = []

    class BareApprovalScreen(ApprovalScreen):
        # Deliberately no escape binding of its own: the base contract is under test.
        def compose(self):
            yield Static("\n".join(f"line {index} of a long review" for index in range(200)))
            yield Button("Reject")
            yield Button("Allow")

        def on_button_pressed(self, event):
            self.dismiss(event.button.label == "Allow")

    class Host(App):
        def on_mount(self):
            self.push_screen(BareApprovalScreen(), results.append)

    async def scenario():
        async with Host().run_test(size=(80, 24)) as pilot:
            for _ in range(40):
                await pilot.pause(0.05)
                if isinstance(pilot.app.screen.focused, Button):
                    break
            await pilot.press("escape")
            for _ in range(40):
                if results:
                    break
                await pilot.pause(0.05)
            assert results == [False]

    asyncio.run(scenario())


def _request(root, action_id="workspace.files.write", owner="workspace_write"):
    from isycode.security import ActionRequest
    return ActionRequest(action_id, root, str(root / "src/app.py"), {}, execution_owner=owner)


def _dialogs(tmp_path):
    """Every dialog of the approval family, with the refusing button it names."""
    from isycode.command_runner import CommandPreview
    from isycode.git_owner import BranchPreview, CommitPreview
    from isycode.workspace_write import WritePreview
    from isycode.tui_screens_approval import (BatchApprovalScreen, BrowserReadPreviewScreen,
                                              CommandApprovalScreen, CommitApprovalScreen,
                                              ContextAccessScreen, DeleteSessionScreen,
                                              GusBranchApprovalScreen, LocalMCPConfirmScreen,
                                              MemoryConfirmScreen, WorkspacePackConfirmScreen,
                                              WriteApprovalScreen)
    write_request = _request(tmp_path)
    write = WritePreview(write_request, "src/app.py", "+print('app')\n", False, "print('app')\n")
    command = CommandPreview(_request(tmp_path, "workspace.command.run", "workspace_command"),
                             ("pytest", "-q"), "pytest", ".", 60, (("src/secret.env", False),))
    commit = CommitPreview(_request(tmp_path, "git.commit", "workspace_git"),
                           "message", ("src/app.py",), "+print('app')\n")
    branch = BranchPreview(_request(tmp_path, "git.branch.create", "workspace_git"),
                           "gus/notes", "0" * 40, "main")
    return [
        (ConfirmScreen("Allow this?", "details", "Allow"), "#tailscale-cancel"),
        (WriteApprovalScreen(write), "#write-approval-reject"),
        (BatchApprovalScreen([write]), "#batch-approval-reject"),
        (CommandApprovalScreen(command), "#command-approval-reject"),
        (CommitApprovalScreen(commit), "#commit-approval-reject"),
        (GusBranchApprovalScreen(branch), "#gus-branch-reject"),
        (LocalMCPConfirmScreen("Start server?", "body", "{}", "Start"), "#local-mcp-cancel"),
        (BrowserReadPreviewScreen("Page", "content", 4000, 1200), "#browser-read-discard"),
        (WorkspacePackConfirmScreen("src/app.py"), "#workspace-pack-cancel"),
        (MemoryConfirmScreen("remember", "Danny prefers Spanish", sends_to_model=True),
         "#memory-confirm-cancel"),
        (DeleteSessionScreen("Work — 2026-10-30"), "#delete-session-cancel"),
        (ContextAccessScreen(tmp_path / "notes.md", requested_by_agent=True), "#context-access-no"),
    ]


class _DialogHost(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen

    def on_mount(self):
        self.push_screen(self._screen)


def test_every_approval_dialog_opens_on_the_button_it_names(tmp_path):
    """AUTO_FOCUS, not a focus asked for in on_mount, is what lands the refusing button.

    The dialogs used to query that button by id in on_mount; the family now names it
    in AUTO_FOCUS alone, so this checks the named button really is the one focused.
    """
    async def scenario():
        for screen, selector in _dialogs(tmp_path):
            host = _DialogHost(screen)
            async with host.run_test(size=(120, 40)) as pilot:
                for _ in range(40):
                    await pilot.pause(0.05)
                    if screen.focused is not None:
                        break
                assert screen.focused is not None, type(screen).__name__
                assert screen.focused is screen.query_one(selector, Button), type(screen).__name__
                assert host._exception is None, type(screen).__name__

    asyncio.run(scenario())


def test_an_approval_dismissed_before_it_mounts_does_not_take_the_app_down():
    """A pushed screen is published before Textual has composed it.

    Dismissing it in that instant pops a dialog that never showed: the screen is
    already closing when its compose runs, and Textual drops every widget it
    composed. Asking one of those absent widgets for its id there raised
    NoMatches, and Textual turns that into a panic that ends the app — a macOS
    suite run died on the branch approval this way, nine minutes from its end.
    """
    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(ConfirmScreen("Allow this?", "body", "Allow"), results.append)
            self.screen.dismiss(True)          # same frame: nothing has composed yet

    async def scenario():
        app = Host()
        async with app.run_test(size=(80, 24)) as pilot:
            for _ in range(40):
                await pilot.pause(0.05)
                if results:
                    break
            assert results == [True]           # the answer still reaches the caller
        assert app._exception is None          # run_test re-raises it: this is the crash gate

    asyncio.run(scenario())
