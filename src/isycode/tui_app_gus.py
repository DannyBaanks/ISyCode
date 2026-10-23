"""GUS entry points in the TUI (ADR 0011, MK4): /gus and the Settings switch."""
from __future__ import annotations

from isycode import gus_slot
from isycode.gus_role import GusRoleError, is_isycode_checkout, load_gus_role
from isycode.gus_session import GusState
from isycode.localization import tr
from isycode.providers import PRESETS
from isycode.tui_screens_approval import TailscaleConfirmScreen
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
        if not await self._await_screen(TailscaleConfirmScreen(
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
            root, lambda: WorkspaceAuthority(root), self._gus_slot_label(), initial=initial))

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
