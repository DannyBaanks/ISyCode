"""TUI Grok sign-in reaches the CLI only through GrokAuthOwner mediation."""
import asyncio

import pytest

from isycode.tui import TUIApp, TailscaleConfirmScreen
from test_daily_tui import configure


@pytest.mark.parametrize("cancel", [False, True])
def test_xai_signin_confirms_then_runs_only_through_the_owner(
        tmp_path, monkeypatch, capsys, cancel):
    project = configure(tmp_path, monkeypatch)
    executable = tmp_path / "grok"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    monkeypatch.setenv("ISYCODE_GROK_EXECUTABLE", str(executable))

    spawned = []

    async def fake_login(method, on_line, program=None):
        spawned.append((method, program))
        on_line("device code: FAKE123")
        return 0

    monkeypatch.setattr("isycode.grok_session.run_login", fake_login)
    monkeypatch.setattr("isycode.grok_session.status", lambda: "signed-in")

    from isycode.grok_session import SESSION_HOST
    from isycode.workspace_authority import WorkspaceAuthority
    authority = WorkspaceAuthority(project)
    grant = authority.effective_policy().get("grants", {}).get("provider.request", {})
    authority.set_grant("provider.request", enabled=True,
                        network_hosts=sorted(set(grant.get("network_hosts", ()))
                                             | {SESSION_HOST}))

    async def run():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as p:
            await app.wait_for_ready()
            from isycode.action_audit import ActionAuditJournal
            task = asyncio.create_task(app._connect_xai_login("device"))
            for _ in range(100):
                await p.pause(0.01)
                if isinstance(app.screen, TailscaleConfirmScreen):
                    break
            assert isinstance(app.screen, TailscaleConfirmScreen)
            # Capture the baseline only after the confirm modal is up. On slow
            # CI runners a single pause() does not drain startup work; a late
            # background receipt would otherwise appear after a baseline taken
            # too early and pollute the cancel-path equality check.
            baseline = ActionAuditJournal(project).verify()
            if cancel:
                await p.press("escape")
            else:
                await p.press("tab", "enter")
            await asyncio.wait_for(task, 10)
            report = ActionAuditJournal(project).verify()
            policy = WorkspaceAuthority(project).effective_policy()
            grok_grant = policy.get("grants", {}).get("grok.login", {})
            if cancel:
                assert spawned == []
                assert grok_grant.get("enabled") is not True
                assert report.decisions == baseline.decisions
                assert report.receipts == baseline.receipts
            else:
                assert spawned == [("device", str(executable.resolve()))]
                assert grok_grant.get("enabled") is True
                assert grok_grant.get("executables") == [str(executable.resolve())]
                assert report.status == "PASS"
                assert report.decisions > baseline.decisions
                assert report.receipts > baseline.receipts
                notes = [item[1] for item in app._active_lane().lines
                         if item[0] == "note"]
                assert any("device code: FAKE123" in note for note in notes)
                from isycode.providers import selected_provider_name
                assert selected_provider_name() == "xai"

    with capsys.disabled():
        asyncio.run(run())


def test_xai_signin_without_the_grok_cli_reports_and_never_opens_the_modal(
        tmp_path, monkeypatch, capsys):
    project = configure(tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    monkeypatch.delenv("ISYCODE_GROK_EXECUTABLE", raising=False)

    lines = []
    spawned = []

    async def fake_login(method, on_line, program=None):
        spawned.append(method)
        return 0

    monkeypatch.setattr("isycode.grok_session.run_login", fake_login)

    async def run():
        app = TUIApp()
        async with app.run_test(size=(80, 24)) as p:
            await app.wait_for_ready()
            original = app._append
            app._append = lambda value, *args, **kwargs: lines.append(str(value))
            await app._connect_xai_login("browser")
            app._append = original
            assert not isinstance(app.screen, TailscaleConfirmScreen)
            assert spawned == []
            assert any("Grok CLI not found" in line for line in lines)

    with capsys.disabled():
        asyncio.run(run())
