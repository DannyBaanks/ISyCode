"""GUS settings (ADR 0015): target checkout, scope and memory mode."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static

from isycode.gus_roots import GusRoots, GusRootsError, configured_target, running_checkout, validate_target
from isycode.localization import tr
from isycode.tui_dialog import Dialog, DialogAction

SaveTarget = Callable[[Any], None]
Toggle = Callable[[], Awaitable[bool]]
SaveScope = Callable[[str, list[str]], None]
SaveMemoryMode = Callable[[str], None]


class GusSettingsScreen(Dialog):
    """Edit GUS's roots. Nothing here grants an action; it only saves choices."""

    dialog_width = "wide"
    dialog_height = "fit"
    dialog_cancel_result = None

    def __init__(self, roots: GusRoots, *, on_target: SaveTarget,
                 on_toggle: Toggle | None = None, on_scope: SaveScope | None = None,
                 on_memory_mode: SaveMemoryMode | None = None) -> None:
        super().__init__()
        self.roots = roots
        self.on_target = on_target
        self.on_toggle = on_toggle
        self.on_scope = on_scope
        self.on_memory_mode = on_memory_mode
        self.busy = False

    def dialog_heading(self) -> str:
        return tr("GUS settings")

    def dialog_hint(self) -> str:
        return tr("GUS reads the machine except credentials. It edits only the target checkout, "
                  "on a gus/* branch, and never L0.")

    def compose_body(self) -> ComposeResult:
        with Vertical(id="gus-settings-body"):
            yield Static(self._status(), id="gus-settings-status", markup=False)
            yield Static(tr("Editable ISyCode checkout"), classes="gus-settings-label")
            target = self.roots.target
            yield Input(value=str(target) if target is not None else "",
                        placeholder=tr("/path/to/ISyCode checkout"), id="gus-target-input")
            if self.on_scope is not None:
                yield Static(tr("Read scope"), classes="gus-settings-label")
                yield Input(value=self._scope_value(), placeholder=tr("all, home, or folders separated by :"),
                            id="gus-scope-input")
            if self.on_memory_mode is not None:
                yield Static(tr("Memory mode · explicit or automatic"), classes="gus-settings-label")
                yield Input(value=self.roots.memory_mode(), id="gus-memory-input")
            yield Static("", id="gus-settings-error", markup=False)

    def _scope_value(self) -> str:
        scope = self.roots.read_scope()
        mode = scope.get("mode")
        if mode in {"machine", "home"}:
            return str(mode)
        folders = scope.get("folders") or []
        return ":".join(str(folder) for folder in folders)

    def _status(self) -> str:
        target = self.roots.target
        return tr("GUS here: {state}\nTarget: {target}\nRead scope: {scope}",
                  state=tr("on") if self.roots.enabled() else tr("off"),
                  target=target if target is not None else tr("none · GUS talks and reads only"),
                  scope=self._scope_value() or tr("none"))

    def _error(self, text: str = "") -> None:
        try:
            field = self.query_one("#gus-settings-error", Static)
        except Exception:
            return
        field.update(text)

    def _refresh(self) -> None:
        try:
            self.query_one("#gus-settings-status", Static).update(self._status())
        except Exception:
            pass

    def dialog_actions(self) -> tuple[DialogAction, ...]:
        actions = [DialogAction("gus-settings-toggle", tr("Turn GUS on or off here"))]
        actions.append(DialogAction("gus-settings-running", tr("Use the running checkout")))
        actions.append(DialogAction("gus-settings-save", tr("Save"), variant="primary"))
        return tuple(actions) + (DialogAction("gus-settings-close", tr("Close")),)

    def dismiss_action(self, action_id: str) -> None:
        if action_id == "gus-settings-toggle":
            if self.on_toggle is not None and not self.busy:
                self.run_worker(self._toggle(), exclusive=True, group="gus-settings")
            return
        if action_id == "gus-settings-running":
            candidate = running_checkout()
            if candidate is None:
                self._error(tr("This ISyCode is not running from a checkout."))
                return
            self.query_one("#gus-target-input", Input).value = str(candidate)
            self._error("")
            return
        if action_id == "gus-settings-save":
            self._save()
            return
        self.dismiss(None)

    async def _toggle(self) -> None:
        assert self.on_toggle is not None
        self.busy = True
        try:
            await self.on_toggle()
        finally:
            self.busy = False
            self._refresh()

    def _save(self) -> None:
        text = self.query_one("#gus-target-input", Input).value.strip()
        try:
            target = validate_target(text) if text else configured_target(self.roots.data)
            self.roots.settings.write({**self.roots.data,
                                       "target": str(target) if target is not None else None})
            self.roots.target = target
            if self.on_target is not None:
                self.on_target(target)
            if self.on_memory_mode is not None:
                mode = self.query_one("#gus-memory-input", Input).value.strip().casefold()
                if mode not in {"explicit", "automatic"}:
                    raise GusRootsError(tr("Memory mode must be explicit or automatic"))
                self.on_memory_mode(mode)
            if self.on_scope is not None:
                mode, folders = self._parse_scope(self.query_one("#gus-scope-input", Input).value)
                self.on_scope(mode, folders)
        except (GusRootsError, OSError, ValueError) as exc:
            self._error(tr("Not saved · {reason}", reason=str(exc)[:180]))
            return
        self._error("")
        self._refresh()

    @staticmethod
    def _parse_scope(value: str) -> tuple[str, list[str]]:
        text = value.strip().casefold()
        if text in {"", "machine", "all", "/"}:
            return "machine", []
        if text in {"home", "~"}:
            return "home", []
        folders = [part.strip() for part in value.split(":") if part.strip()]
        if not folders:
            raise GusRootsError(tr("A folder scope needs at least one folder"))
        resolved = []
        for folder in folders:
            try:
                path = Path(folder).expanduser().resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise GusRootsError(tr("Folder unavailable · {folder}", folder=folder)) from exc
            if not path.is_dir():
                raise GusRootsError(tr("Not a folder · {folder}", folder=folder))
            resolved.append(str(path))
        return "folders", resolved


__all__ = ["GusSettingsScreen"]
