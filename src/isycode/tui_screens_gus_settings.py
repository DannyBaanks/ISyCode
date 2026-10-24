"""GUS settings (ADR 0015): target checkout, scope, memory mode and memories."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static

from isycode.gus_memory import GusMemoryStore
from isycode.gus_roots import GusRoots, GusRootsError, configured_target, running_checkout, validate_target
from isycode.localization import tr
from isycode.tui_dialog import Dialog, DialogAction

SaveTarget = Callable[[Any], None]
Toggle = Callable[[], Awaitable[bool]]
SaveScope = Callable[[str, list[str]], Awaitable[bool]]
SaveMemoryMode = Callable[[str], None]
OpenMemories = Callable[[], Awaitable[None]]
ForgetOne = Callable[[str], Awaitable[bool]]
ForgetAll = Callable[[], Awaitable[bool]]
MAX_LISTED = 50
MAX_LINE_CHARS = 300


class GusSettingsScreen(Dialog):
    """Edit GUS's roots. Nothing here grants an action; it only saves choices."""

    dialog_width = "wide"
    dialog_height = "fit"
    dialog_cancel_result = None

    def __init__(self, roots: GusRoots, *, on_target: SaveTarget,
                 on_toggle: Toggle | None = None, on_scope: SaveScope | None = None,
                 on_memory_mode: SaveMemoryMode | None = None,
                 on_memories: OpenMemories | None = None) -> None:
        super().__init__()
        self.roots = roots
        self.on_target = on_target
        self.on_toggle = on_toggle
        self.on_scope = on_scope
        self.on_memory_mode = on_memory_mode
        self.on_memories = on_memories
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
        if self.on_memories is not None:
            actions.append(DialogAction("gus-settings-memories", tr("Memories")))
        actions.append(DialogAction("gus-settings-save", tr("Save"), variant="primary"))
        return tuple(actions) + (DialogAction("gus-settings-close", tr("Close")),)

    def dismiss_action(self, action_id: str) -> None:
        if action_id == "gus-settings-toggle":
            if self.on_toggle is not None and not self.busy:
                self.run_worker(self._toggle(), exclusive=True, group="gus-settings")
            return
        if action_id == "gus-settings-memories":
            if self.on_memories is not None and not self.busy:
                self.run_worker(self._open_memories(), exclusive=True, group="gus-settings")
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
            if self.on_scope is None:
                if self._save():
                    self._error("")
                    self._refresh()
            elif not self.busy:
                self.run_worker(self._save_with_scope(), exclusive=True, group="gus-settings")
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

    async def _open_memories(self) -> None:
        assert self.on_memories is not None
        self.busy = True
        try:
            await self.on_memories()
        finally:
            self.busy = False
            self._refresh()

    def _save(self) -> bool:
        """Save target and memory mode. The read scope has its own confirmation."""
        try:
            text = self.query_one("#gus-target-input", Input).value.strip()
            target = validate_target(text) if text else configured_target(self.roots.data)
            settings = {**self.roots.data,
                        "target": str(target) if target is not None else None}
            if self.on_memory_mode is not None:
                mode = self.query_one("#gus-memory-input", Input).value.strip().casefold()
                if mode not in {"explicit", "automatic"}:
                    raise GusRootsError(tr("Memory mode must be explicit or automatic"))
                settings["memory_mode"] = mode
            self.roots.settings.write(settings)
            self.roots.data = self.roots.settings.read()
            self.roots.target = target
            if self.on_target is not None:
                self.on_target(target)
            if self.on_memory_mode is not None:
                self.on_memory_mode(settings["memory_mode"])
        except (GusRootsError, OSError, ValueError) as exc:
            self._error(tr("Not saved · {reason}", reason=str(exc)[:180]))
            return False
        return True

    async def _save_with_scope(self) -> None:
        """Target and memory first; a changed read scope only after its confirmation."""
        self.busy = True
        try:
            if not self._save():
                return
            try:
                mode, folders = self._parse_scope(
                    self.query_one("#gus-scope-input", Input).value)
            except GusRootsError as exc:
                self._error(tr("Not saved · {reason}", reason=str(exc)[:180]))
                return
            assert self.on_scope is not None
            if not await self.on_scope(mode, folders):
                return
            self.roots.data = self.roots.settings.read()
            self._error("")
            self._refresh()
        finally:
            self.busy = False

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


class GusMemoryScreen(Dialog):
    """Read and forget GUS's memories about the person. The model cannot delete."""

    dialog_width = "wide"
    dialog_height = "fill"
    dialog_cancel_result = None
    AUTO_FOCUS = "#gus-memory-forget-input"

    def __init__(self, roots: GusRoots, *, on_forget: ForgetOne,
                 on_forget_all: ForgetAll) -> None:
        super().__init__()
        self.roots = roots
        self.on_forget = on_forget
        self.on_forget_all = on_forget_all
        self.busy = False

    def dialog_heading(self) -> str:
        return tr("GUS memory")

    def dialog_hint(self) -> str:
        return tr("GUS remembers these across workspaces. Deleting asks you first; GUS "
                  "cannot delete a memory by itself.")

    def dialog_actions(self) -> tuple[DialogAction, ...]:
        return (DialogAction("gus-memory-close", tr("Close")),
                DialogAction("gus-memory-forget-one", tr("Forget one")),
                DialogAction("gus-memory-forget-all", tr("Forget all")))

    def compose_body(self) -> ComposeResult:
        with Vertical(id="gus-memory-body"):
            yield Static(self._status(), id="gus-memory-status", markup=False)
            with Vertical(id="gus-memory-list"):
                for index, entry in enumerate(self._entries(), 1):
                    yield self._line(index, entry)
            yield Static(tr("Number to forget"), classes="gus-settings-label")
            yield Input(placeholder=tr("1"), id="gus-memory-forget-input")
            yield Static("", id="gus-memory-error", markup=False)

    def _entries(self) -> list[dict[str, str]]:
        try:
            return GusMemoryStore(root=self.roots.settings.directory.parent).entries()
        except (OSError, ValueError):
            return []

    def _status(self) -> str:
        entries = self._entries()
        shown = min(len(entries), MAX_LISTED)
        return tr("Mode: {mode} · {count} memories{shown}",
                  mode=tr(self.roots.memory_mode()),
                  count=len(entries),
                  shown="" if shown == len(entries) else tr(" · showing {shown}", shown=shown))

    @staticmethod
    def _line(index: int, entry: dict[str, str]) -> Static:
        workspace = Path(entry.get("workspace") or "").name
        text = entry.get("text", "").replace("\n", " ")
        suffix = f" · {workspace}" if workspace else ""
        return Static(f"{index}. {text[:MAX_LINE_CHARS]}{suffix}",
                      classes="gus-memory-line", markup=False)

    def _error(self, text: str = "") -> None:
        try:
            self.query_one("#gus-memory-error", Static).update(text)
        except Exception:
            pass

    def _reload(self) -> None:
        try:
            container = self.query_one("#gus-memory-list", Vertical)
            container.remove_children()
            for index, entry in enumerate(self._entries(), 1):
                container.mount(self._line(index, entry))
            self.query_one("#gus-memory-status", Static).update(self._status())
        except Exception:
            pass

    def dismiss_action(self, action_id: str) -> None:
        if action_id == "gus-memory-forget-one":
            if not self.busy:
                self.run_worker(self._forget_one(), exclusive=True, group="gus-memory")
            return
        if action_id == "gus-memory-forget-all":
            if not self.busy:
                self.run_worker(self._forget_all(), exclusive=True, group="gus-memory")
            return
        self.dismiss(None)

    async def _forget_one(self) -> None:
        entries = self._entries()
        value = self.query_one("#gus-memory-forget-input", Input).value.strip()
        try:
            index = int(value)
        except ValueError:
            self._error(tr("Write the number of one memory."))
            return
        if not 1 <= index <= len(entries):
            self._error(tr("There is no memory with that number."))
            return
        self.busy = True
        try:
            if await self.on_forget(entries[index - 1]["id"]):
                self.query_one("#gus-memory-forget-input", Input).value = ""
                self._error("")
                self._reload()
        finally:
            self.busy = False

    async def _forget_all(self) -> None:
        self.busy = True
        try:
            if await self.on_forget_all():
                self._error("")
                self._reload()
        finally:
            self.busy = False


__all__ = ["GusMemoryScreen", "GusSettingsScreen"]
