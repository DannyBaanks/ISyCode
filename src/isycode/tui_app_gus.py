"""GUS entry points in the TUI (ADR 0011, ADR 0015): /gus, Settings, gus/* branches and GUS turns."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from isycode import gus_slot
from isycode.git_owner import GitOwner
from isycode.gus_dispatch import GusToolDispatcher
from isycode.gus_l0 import fingerprint as l0_fingerprint
from isycode.gus_memory import GusMemoryOwner, GusMemoryStore
from isycode.gus_role import GusRoleError, load_gus_role
from isycode.gus_roots import GusRoots, GusRootsError, GusSettingsStore, scope_text
from isycode.gus_session import GusState, GusUnavailable, gus_work
from isycode.localization import tr
from isycode.providers import PRESETS
from isycode.tui_screens_approval import (
    CommandApprovalScreen, CommitApprovalScreen, GusBranchApprovalScreen, ConfirmScreen,
    WriteApprovalScreen,
)
from isycode.tui_screens_gus import GusScreen
from isycode.tui_screens_gus_settings import GusMemoryScreen, GusSettingsScreen
from isycode.tui_theme import GREEN, MUTED, RED, YELLOW


class GusMixin:
    def _gus_roots(self) -> GusRoots:
        return GusRoots(self._workspace_root)

    def _gus_enabled_here(self) -> bool:
        try:
            return GusState(self._workspace_root).enabled()
        except OSError:
            return False

    def _record_gus_consent(self) -> None:
        """Consent is about this scope and target; changing either asks again."""
        try:
            store = GusSettingsStore()
            data = store.read()
            store.consent(data, at=datetime.now().astimezone().isoformat(timespec="seconds"))
        except (GusRootsError, OSError, ValueError):
            pass                              # machine reads stay denied without a consent record

    async def _enable_gus_here(self) -> bool:
        """GK4-00: GUS answers in a workspace only after this explicit confirmation."""
        slot = gus_slot.gus_model()
        destination = (tr("{provider} / {model}", provider=PRESETS[slot["provider"]]["label"],
                          model=slot["model"]) if slot else tr("no model chosen yet"))
        try:
            roots = self._gus_roots()
            target = roots.target
        except (GusRootsError, OSError):
            target = None
        if not await self._await_screen(ConfirmScreen(
                tr("Enable GUS in this workspace?"),
                tr("GUS is your assistant with its own model ({destination}). It can read this "
                   "computer except credentials and secrets, and everything it reads can be sent "
                   "to that model. It edits only {target}, on a gus/* branch, and never the L0 "
                   "kernel. Your conversation and memories are yours, shared across workspaces "
                   "and stored outside the checkout. It grants itself nothing; turn it off any "
                   "time in Settings.", destination=destination,
                   target=target if target is not None else tr("no checkout configured yet")),
                tr("Enable GUS"))):
            return False
        try:
            GusState(self._workspace_root).enable()
        except (OSError, ValueError) as exc:
            self._set_activity(tr("GUS could not be enabled · {reason}", reason=type(exc).__name__), RED)
            return False
        self._record_gus_consent()
        self._set_activity(tr("GUS enabled in this workspace"), GREEN)
        self._paint_workspace_chrome()
        return True

    async def _open_gus(self, initial: str = "") -> None:
        try:
            load_gus_role()
        except GusRoleError as exc:
            # GK1-01: a role that asks for more than ADR 0011 allows never loads.
            self._set_activity(tr("GUS role not loaded · {reason}", reason=str(exc)[:160]), RED)
            return
        if not self._gus_enabled_here() and not await self._enable_gus_here():
            return
        try:
            roots = self._gus_roots()
        except (GusRootsError, OSError) as exc:
            self._set_activity(tr("GUS settings unavailable · {reason}", reason=str(exc)[:160]), RED)
            return
        await self._await_screen(GusScreen(
            roots, self._gus_slot_label(), initial=initial,
            work=self._run_gus_turn, remember=self._remember_gus_memory,
            report_text=self._gus_report_text,
            seal=self._seal_gus_generation, generation_text=self._generation_text,
            settings=self._open_gus_settings, undo=self._undo_latest_gus_turn))

    async def _open_gus_settings(self) -> None:
        try:
            roots = self._gus_roots()
        except (GusRootsError, OSError) as exc:
            self._set_activity(tr("GUS settings unavailable · {reason}", reason=str(exc)[:160]), RED)
            return
        await self._await_screen(GusSettingsScreen(
            roots, on_target=lambda target: self._paint_workspace_chrome(),
            on_toggle=self._toggle_gus_setting, on_scope=self._save_gus_scope,
            on_memory_mode=self._gus_memory_mode_changed,
            on_memories=self._open_gus_memory))

    def _gus_memory_mode_changed(self, mode: str) -> None:
        self._set_activity(tr("GUS memory mode · {mode}", mode=mode), MUTED)

    async def _open_gus_memory(self) -> None:
        try:
            roots = self._gus_roots()
        except (GusRootsError, OSError) as exc:
            self._set_activity(tr("GUS settings unavailable · {reason}", reason=str(exc)[:160]), RED)
            return
        await self._await_screen(GusMemoryScreen(
            roots, on_forget=self._forget_gus_memory,
            on_forget_all=self._clear_gus_memories))

    async def _remember_gus_memory(self, arguments) -> str:
        """One ``memory_remember`` call: review it in explicit mode, then store it."""
        if isinstance(arguments, str):
            try:
                payload = json.loads(arguments)
            except json.JSONDecodeError:
                payload = None
        else:
            payload = arguments
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            return self._memory_error("memory text must be a string")
        try:
            roots = self._gus_roots()
            owner = GusMemoryOwner(roots, self._action_approvals)
            preview = await asyncio.to_thread(
                owner.prepare, "remember",
                {"text": text, "workspace": str(roots.visible)})
        except (GusRootsError, OSError, ValueError) as exc:
            return self._memory_error(str(exc))
        approval = None
        if owner.write_requires_approval():
            if not await self._approve_memory(preview):
                return json.dumps({"status": "rejected_by_user"})
            approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.execute, preview, approval)
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            return self._memory_error(outcome.reason or outcome.decision)
        return outcome.text

    @staticmethod
    def _memory_error(reason: str) -> str:
        return json.dumps({"error": "ISyCode denied the call", "reason": str(reason)[:300]},
                          ensure_ascii=False)

    async def _approve_memory(self, preview) -> bool:
        return bool(await self._await_screen(ConfirmScreen(
            tr("Let GUS remember this?"),
            tr("GUS will keep this note for future conversations, across workspaces, and can "
               "show or forget it in Settings:\n{text}", text=(preview.text or "")[:2000]),
            tr("Remember"))))

    async def _forget_gus_memory(self, memory_id: str) -> bool:
        return await self._gus_memory_delete(
            "forget", {"id": memory_id}, tr("Forget this GUS memory?"),
            tr("GUS will delete this memory. This cannot be undone."))

    async def _clear_gus_memories(self) -> bool:
        try:
            roots = self._gus_roots()
            count = len(GusMemoryStore(root=roots.settings.directory.parent).entries())
        except (GusRootsError, OSError, ValueError):
            count = 0
        return await self._gus_memory_delete(
            "clear", {}, tr("Forget all GUS memories?"),
            tr("GUS will delete all {count} memories. This cannot be undone.", count=count))

    async def _gus_memory_delete(self, operation: str, arguments: dict,
                                 title: str, detail: str) -> bool:
        try:
            roots = self._gus_roots()
            owner = GusMemoryOwner(roots, self._action_approvals)
            preview = await asyncio.to_thread(owner.prepare, operation, arguments)
        except (GusRootsError, OSError, ValueError) as exc:
            self._set_activity(tr("GUS memory unchanged · {reason}", reason=str(exc)[:160]), YELLOW)
            return False
        if not await self._await_screen(ConfirmScreen(title, detail, tr("Forget"))):
            self._set_activity(tr("GUS memory unchanged"), MUTED)
            return False
        approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.execute, preview, approval)
        if outcome.decision != "ALLOW":
            self._set_activity(tr("GUS memory unchanged · {reason}", reason=outcome.reason[:160]), RED)
            return False
        self._set_activity(tr("GUS memory updated"), GREEN)
        return True

    async def _save_gus_scope(self, mode: str, folders: list[str]) -> bool:
        """A read scope is machine access: changing it asks again (ADR 0015)."""
        try:
            roots = self._gus_roots()
        except (GusRootsError, OSError) as exc:
            self._set_activity(tr("GUS settings unavailable · {reason}", reason=str(exc)[:160]), RED)
            return False
        try:
            current = roots.settings.read()
            candidate = {**current, "read_scope": {"mode": mode, "folders": list(folders)}}
            if (candidate["read_scope"] == current.get("read_scope")
                    and roots.settings.consented(candidate)):
                return True
            scope = scope_text(candidate)
            allowed = await self._await_screen(ConfirmScreen(
                tr("Let GUS read this scope?"),
                tr("GUS will be able to read {scope} on this computer, except credentials, keys, "
                   "private stores, shell histories and the ISyCode state. Everything it reads can "
                   "be sent to its model. Edits stay limited to {target}, on a gus/* branch.",
                   scope=scope, target=roots.target if roots.target is not None
                   else tr("no checkout configured yet")),
                tr("Use this scope")))
            if not allowed:
                self._set_activity(tr("GUS read scope unchanged"), MUTED)
                return False
            roots.settings.consent(
                candidate, at=datetime.now().astimezone().isoformat(timespec="seconds"))
        except (GusRootsError, OSError, ValueError) as exc:
            self._set_activity(tr("GUS read scope not saved · {reason}", reason=str(exc)[:160]), RED)
            return False
        self._set_activity(tr("GUS read scope · {scope}", scope=scope), GREEN)
        return True

    async def _toggle_gus_setting(self) -> bool:
        """On/off from the GUS settings form, without leaving the form."""
        if self._gus_enabled_here():
            try:
                GusState(self._workspace_root).disable()
            except OSError:
                return True
            self._set_activity(tr("GUS turned off in this workspace"), MUTED)
            self._paint_workspace_chrome()
            return False
        return await self._enable_gus_here()

    async def _create_gus_branch(self, topic: str) -> str | None:
        """MK5b: create and switch to ``gus/<topic>`` after an exact approval; the branch or None."""
        try:
            roots = self._gus_roots()
        except (GusRootsError, OSError) as exc:
            self._set_activity(tr("GUS target unavailable · {reason}", reason=str(exc)[:160]), YELLOW)
            return None
        target = roots.target
        if target is None:
            self._set_activity(tr("GUS has no configured ISyCode checkout to edit."), YELLOW)
            return None
        try:
            owner = GitOwner(target, roots.authority(), self._action_approvals)
            preview = await asyncio.to_thread(owner.preview_gus_branch, topic)
        except (OSError, ValueError, GusRootsError) as exc:
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
            digest = (await asyncio.to_thread(l0_fingerprint, target)).digest
            GusState(target).record_branch(preview.branch, preview.base, digest)
        except (OSError, ValueError):
            pass                              # gate V then reports the unknown start
        self._set_activity(tr("On {branch} · receipt {receipt_id}", branch=preview.branch,
                              receipt_id=outcome.receipt.receipt_id), GREEN)
        return preview.branch

    async def _approve_gus_change(self, kind: str, preview) -> bool:
        """The person reviews the exact change GUS proposed, in the GUS window."""
        if kind == "memory":
            return await self._approve_memory(preview)
        if kind == "command":
            return bool(await self._await_screen(CommandApprovalScreen(preview)))
        if kind == "commit":
            return bool(await self._await_screen(CommitApprovalScreen(preview)))
        return bool(await self._await_screen(WriteApprovalScreen(preview)))

    async def _run_gus_turn(self, text: str, state: GusState, *, complete=None, on_status=None):
        """MK5c: one GUS turn with tools, recorded and checked against L0.

        The turn is recorded in a turn journal on the target (Flow's, in any
        mode), so /undo puts it back. The L0 fingerprint is taken before and
        after; if L0 changed anyway, the turn is undone at once and the paths
        are reported. Returns the reply and a report: files the turn changed,
        L0 paths that changed, and any that are still changed after the undo.
        """
        from isycode.turn_journal import TurnJournal
        try:
            roots = self._gus_roots()
        except (GusRootsError, OSError) as exc:
            raise GusUnavailable(str(exc)) from exc
        target = roots.target
        if target is None:
            raise GusUnavailable("GUS has no configured ISyCode checkout to edit.")
        ready, reason = roots.target_ready()
        if not ready:
            raise GusUnavailable(reason)
        if TurnJournal.running(target) is not None:
            raise GusUnavailable("Another turn is recording GUS's target; try again when it ends.")
        if on_status:
            on_status(tr("preparing {target}", target=target.name))
        before = await asyncio.to_thread(l0_fingerprint, target)
        turn = TurnJournal.begin(target)
        token = turn.pin()
        failure: Exception | None = None
        reply = None
        try:
            dispatcher = GusToolDispatcher(roots, self._action_approvals,
                                           approve=self._approve_gus_change)
            reply = await gus_work(roots, text, dispatcher, complete=complete, state=state,
                                   on_status=on_status)
        except Exception as exc:              # the L0 check below still runs
            failure = exc
        finally:
            turn.unpin(token)
            turn.finish()
        report = {"changed": [change["path"] for change in turn.changes()], "l0": [], "l0_still": []}
        report["l0"] = (await asyncio.to_thread(l0_fingerprint, target)).changed(before)
        if report["l0"]:
            await self._undo_gus_turn(turn.turn_id, roots)
            report["l0_still"] = (await asyncio.to_thread(l0_fingerprint, target)).changed(before)
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
        try:
            roots = self._gus_roots()
        except (GusRootsError, OSError) as exc:
            self._set_activity(tr("GUS target unavailable · {reason}", reason=str(exc)[:160]), YELLOW)
            return None
        target = roots.target
        branch = current_gus_branch(target) if target is not None else None
        if target is None or branch is None:
            self._set_activity(tr("Generations are sealed on a gus/* branch · /gus branch <topic>"), YELLOW)
            return None
        state = GusState(target)
        if not await self._await_screen(ConfirmScreen(
                tr("Seal GUS's work on {branch}?", branch=branch),
                tr("ISyCode checks what GUS committed on this branch. V: nothing in L0 changed. "
                   "T: the tests of the touched code. A: the coverage auditor and L0 tests. "
                   "L: lint. T, A and L run in the command sandbox. Only if all pass is the work "
                   "sealed; you activate it by merging the branch."),
                tr("Run the gates"))):
            return None
        recorded = state.branch(branch)
        authority = roots.authority()
        if recorded is None:
            changes = {"clean": True, "changes": [], "base": "", "head": "", "diff": ""}
        else:
            outcome = await asyncio.to_thread(
                GitOwner(target, authority, self._action_approvals).generation_changes,
                recorded["base"])
            if outcome.decision != "ALLOW" or outcome.receipt is None:
                self._set_activity(tr("GUS generation not prepared · {reason}", reason=outcome.reason[:160]), RED)
                return None
            changes = json.loads(outcome.text)
        digest = (await asyncio.to_thread(l0_fingerprint, target)).digest
        owner = CommandRunOwner(target, authority, self._action_approvals)

        async def runner(argv):
            try:
                preview = await asyncio.to_thread(owner.prepare, list(argv), ".", 600)
            except (OSError, ValueError) as exc:
                return None, str(exc)
            approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
            with gus_turn(target):              # a gate that touches L0 is not promoted
                result = await owner.run(preview, approval)
            if result.decision != "ALLOW":
                return None, result.reason
            payload = json.loads(result.text)
            return (None if payload.get("timed_out") else payload.get("exit_code")), payload.get("output", "")

        self._set_activity(tr("GUS gates running on {branch}…", branch=branch), MUTED)
        record = await build_generation(target, branch, changes, recorded, digest, runner)
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

    async def _undo_gus_turn(self, turn_id: str, roots: GusRoots | None = None) -> None:
        """Put one GUS turn back after L0 changed; ISyCode starts this, not the model."""
        from isycode.workspace_write import WorkspaceWriteOwner
        try:
            roots = roots or self._gus_roots()
        except (GusRootsError, OSError):
            return
        target = roots.target
        if target is None:
            return
        try:
            owner = WorkspaceWriteOwner(target, roots.authority(), self._action_approvals)
            preview = await asyncio.to_thread(owner.preview_turn_undo, turn_id)
            approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
            await asyncio.to_thread(owner.apply_turn_undo, preview, approval)
        except (OSError, ValueError):
            pass                              # the second fingerprint reports what is left

    async def _undo_latest_gus_turn(self) -> bool:
        """The person undoes GUS's last recorded turn on the target."""
        from isycode.turn_journal import TurnJournal
        from isycode.workspace_write import WorkspaceWriteOwner
        try:
            roots = self._gus_roots()
            target = roots.target
            if target is None:
                self._set_activity(tr("GUS has no configured ISyCode checkout to edit."), YELLOW)
                return False
            turn = await asyncio.to_thread(TurnJournal.latest, target)
            if turn is None:
                self._set_activity(tr("No recorded GUS turn to undo."), MUTED)
                return False
            owner = WorkspaceWriteOwner(target, roots.authority(), self._action_approvals)
            preview = await asyncio.to_thread(owner.preview_turn_undo, turn.turn_id)
            approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
            outcome = await asyncio.to_thread(owner.apply_turn_undo, preview, approval)
        except (GusRootsError, OSError, ValueError) as exc:
            self._set_activity(tr("Nothing undone · {reason}", reason=str(exc)[:160]), YELLOW)
            return False
        if outcome.decision != "ALLOW":
            self._set_activity(tr("Nothing undone · {reason}", reason=outcome.reason[:160]), RED)
            return False
        self._set_activity(tr("GUS turn restored · {count} files", count=len(preview.steps)), GREEN)
        return True

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
