"""GUS entry points in the TUI (ADR 0011, MK4–MK5): /gus, Settings, gus/* branches and GUS turns."""
from __future__ import annotations

import asyncio

from isycode import gus_slot
from isycode.git_owner import GitOwner
from isycode.gus_role import GusRoleError, is_isycode_checkout, load_gus_role
from isycode.gus_l0 import fingerprint as l0_fingerprint
from isycode.gus_session import GusState, GusUnavailable, gus_work
from isycode.localization import tr
from isycode.providers import PRESETS
from isycode.tui_screens_approval import GusBranchApprovalScreen, ConfirmScreen
from isycode.tui_screens_gus import GusScreen
from isycode.tui_theme import GREEN, MUTED, RED, YELLOW
from isycode.workspace_authority import WorkspaceAuthority


class GusMixin:
    def _gus_enabled_here(self) -> bool:
        try:
            return GusState(self._workspace_root).enabled()
        except OSError:
            return False

    async def _enable_gus_here(self) -> bool:
        """GK4-00: GUS answers in a workspace only after this explicit confirmation."""
        slot = gus_slot.gus_model()
        destination = (tr("{provider} / {model}", provider=PRESETS[slot["provider"]]["label"],
                          model=slot["model"]) if slot else tr("no model chosen yet"))
        if not await self._await_screen(ConfirmScreen(
                tr("Enable GUS in this workspace?"),
                tr("GUS maintains ISyCode with its own model ({destination}). Enabling it here lets GUS "
                   "read its fixed project context (AGENTS.md, the design skill and standard, ADR "
                   "titles) with receipts and send it, with your messages to GUS, to that model. In "
                   "this version GUS has no tools: it reads and answers. It grants itself nothing; "
                   "turn it off any time in Settings.", destination=destination),
                tr("Enable GUS"))):
            return False
        try:
            GusState(self._workspace_root).enable()
        except (OSError, ValueError) as exc:
            self._set_activity(tr("GUS could not be enabled · {reason}", reason=type(exc).__name__), RED)
            return False
        self._set_activity(tr("GUS enabled in this workspace"), GREEN)
        self._paint_workspace_chrome()
        return True

    async def _open_gus(self, initial: str = "") -> None:
        if not is_isycode_checkout(self._workspace_root):
            self._set_activity(tr("GUS works only in the ISyCode repository."), YELLOW)
            return
        try:
            load_gus_role()
        except GusRoleError as exc:
            # GK1-01: a role that asks for more than ADR 0011 allows never loads.
            self._set_activity(tr("GUS role not loaded · {reason}", reason=str(exc)[:160]), RED)
            return
        if not self._gus_enabled_here() and not await self._enable_gus_here():
            return
        root = self._workspace_root
        await self._await_screen(GusScreen(
            root, lambda: WorkspaceAuthority(root), self._gus_slot_label(), initial=initial,
            work=self._run_gus_turn, report_text=self._gus_report_text,
            seal=self._seal_gus_generation, generation_text=self._generation_text))

    async def _create_gus_branch(self, topic: str) -> str | None:
        """MK5b: create and switch to ``gus/<topic>`` after an exact approval; the branch or None."""
        if not is_isycode_checkout(self._workspace_root):
            self._set_activity(tr("GUS works only in the ISyCode repository."), YELLOW)
            return None
        root = self._workspace_root
        try:
            owner = GitOwner(root, WorkspaceAuthority(root), self._action_approvals)
            preview = await asyncio.to_thread(owner.preview_gus_branch, topic)
        except (OSError, ValueError) as exc:
            self._set_activity(tr("GUS branch not proposed · {reason}", reason=str(exc)[:160]), YELLOW)
            return None
        if not await self._await_screen(GusBranchApprovalScreen(preview)):
            self._set_activity(tr("GUS branch rejected · nothing changed"), MUTED)
            return None
        approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.create_gus_branch, preview, approval)
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            self._set_activity(tr("GUS branch {decision} · {reason}", decision=outcome.decision,
                                  reason=outcome.reason[:160]), RED)
            return None
        try:
            digest = (await asyncio.to_thread(l0_fingerprint, root)).digest
            GusState(root).record_branch(preview.branch, preview.base, digest)
        except (OSError, ValueError):
            pass                              # gate V then reports the unknown start
        self._set_activity(tr("On {branch} · receipt {receipt_id}", branch=preview.branch,
                              receipt_id=outcome.receipt.receipt_id), GREEN)
        return preview.branch

    async def _run_gus_turn(self, text: str, state: GusState, *, complete=None, on_status=None):
        """MK5c: one GUS turn with tools, recorded and checked against L0.

        The turn is recorded in a turn journal (Flow's, in any mode), so /undo
        puts it back. The L0 fingerprint is taken before and after; if L0 changed
        anyway, the turn is undone at once and the paths are reported. Returns the
        reply and a report: files the turn changed, L0 paths that changed, and
        any that are still changed after the undo.
        """
        from isycode.turn_journal import TurnJournal
        root = self._workspace_root
        if TurnJournal.running(root) is not None:
            raise GusUnavailable("Another turn is recording this workspace; try again when it ends.")
        before = await asyncio.to_thread(l0_fingerprint, root)
        turn = TurnJournal.begin(root)
        token = turn.pin()
        failure: Exception | None = None
        reply = None
        try:
            reply = await gus_work(root, WorkspaceAuthority(root), text, self._dispatch_chat_tool,
                                   complete=complete, state=state, on_status=on_status)
        except Exception as exc:              # the L0 check below still runs
            failure = exc
        finally:
            turn.unpin(token)
            turn.finish()
        report = {"changed": [change["path"] for change in turn.changes()], "l0": [], "l0_still": []}
        report["l0"] = (await asyncio.to_thread(l0_fingerprint, root)).changed(before)
        if report["l0"]:
            await self._undo_gus_turn(turn.turn_id)
            report["l0_still"] = (await asyncio.to_thread(l0_fingerprint, root)).changed(before)
        if failure is not None:
            if isinstance(failure, GusUnavailable) and (report["changed"] or report["l0"]):
                raise GusUnavailable(f"{failure} {self._gus_report_text(report)}") from failure
            raise failure
        return reply, report

    async def _seal_gus_generation(self) -> dict | None:
        """MK5d: run the V/T/A/L/S gates on GUS's committed work and keep the result privately."""
        import json
        from isycode.command_runner import CommandRunOwner
        from isycode.gus_generation import build_generation
        from isycode.gus_l0 import current_gus_branch, gus_turn
        root = self._workspace_root
        branch = current_gus_branch(root) if is_isycode_checkout(root) else None
        if branch is None:
            self._set_activity(tr("Generations are sealed on a gus/* branch · /gus branch <topic>"), YELLOW)
            return None
        state = GusState(root)
        if not await self._await_screen(ConfirmScreen(
                tr("Seal GUS's work on {branch}?", branch=branch),
                tr("ISyCode checks what GUS committed on this branch. V: nothing in L0 changed. "
                   "T: the tests of the touched code. A: the coverage auditor and L0 tests. "
                   "L: lint. T, A and L run in the command sandbox. Only if all pass is the work "
                   "sealed; you activate it by merging the branch."),
                tr("Run the gates"))):
            return None
        recorded = state.branch(branch)
        authority = WorkspaceAuthority(root)
        if recorded is None:
            changes = {"clean": True, "changes": [], "base": "", "head": "", "diff": ""}
        else:
            outcome = await asyncio.to_thread(
                GitOwner(root, authority, self._action_approvals).generation_changes, recorded["base"])
            if outcome.decision != "ALLOW" or outcome.receipt is None:
                self._set_activity(tr("GUS generation not prepared · {reason}", reason=outcome.reason[:160]), RED)
                return None
            changes = json.loads(outcome.text)
        digest = (await asyncio.to_thread(l0_fingerprint, root)).digest
        owner = CommandRunOwner(root, authority, self._action_approvals)

        async def runner(argv):
            try:
                preview = await asyncio.to_thread(owner.prepare, list(argv), ".", 600)
            except (OSError, ValueError) as exc:
                return None, str(exc)
            approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
            with gus_turn(root):              # a gate that touches L0 is not promoted
                result = await owner.run(preview, approval)
            if result.decision != "ALLOW":
                return None, result.reason
            payload = json.loads(result.text)
            return (None if payload.get("timed_out") else payload.get("exit_code")), payload.get("output", "")

        self._set_activity(tr("GUS gates running on {branch}…", branch=branch), MUTED)
        record = await build_generation(root, branch, changes, recorded, digest, runner)
        state.save_generation(record)
        self._set_activity(self._generation_text(record), GREEN if record["state"] == "SEALED" else RED)
        return record

    @staticmethod
    def _generation_text(record: dict) -> str:
        gates = " ".join(f"{gate['gate']}:{gate['status']}" for gate in record["gates"])
        if record["state"] == "SEALED":
            return tr("Sealed {branch} · {gates} · seal {seal}", branch=record["branch"], gates=gates,
                      seal=record["seal"][:12])
        failed = next((gate for gate in record["gates"] if gate["status"] != "PASS"), None)
        return tr("Rejected {branch} · {gates} · {reason}", branch=record["branch"], gates=gates,
                  reason=(failed or {}).get("detail", "")[:160])

    async def _undo_gus_turn(self, turn_id: str) -> None:
        """Put one GUS turn back after L0 changed; ISyCode starts this, not the model."""
        from isycode.workspace_write import WorkspaceWriteOwner
        root = self._workspace_root
        try:
            owner = WorkspaceWriteOwner(root, WorkspaceAuthority(root), self._action_approvals)
            preview = await asyncio.to_thread(owner.preview_turn_undo, turn_id)
            approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
            await asyncio.to_thread(owner.apply_turn_undo, preview, approval)
        except (OSError, ValueError):
            pass                              # the second fingerprint reports what is left

    @staticmethod
    def _gus_report_text(report: dict) -> str:
        if report.get("l0_still"):
            return tr("L0 changed and is still changed: {paths}. Review it with git.",
                      paths=", ".join(report["l0_still"][:8]))
        if report.get("l0"):
            return tr("L0 changed ({paths}); the whole turn was undone.", paths=", ".join(report["l0"][:8]))
        if report.get("changed"):
            return tr("Changed {count} files · /undo puts this turn back.", count=len(report["changed"]))
        return ""

    async def _toggle_gus_here(self) -> None:
        if self._gus_enabled_here():
            GusState(self._workspace_root).disable()
            self._set_activity(tr("GUS turned off in this workspace"), MUTED)
            self._paint_workspace_chrome()
        else:
            await self._enable_gus_here()
        self._menu_stack = []
        self._open_settings_menu()


__all__ = ["GusMixin"]
