"""Chat transcript widgets for the ISyCode TUI.

Moved verbatim from tui.py. isycode.tui re-exports these names.
"""
from __future__ import annotations

from textual.binding import Binding
from textual.widgets import (
    Button,
    Collapsible,
    Input,
    OptionList,
    Static,
    TextArea,
    Tree,
)
from textual.events import Click
from textual.widgets._collapsible import CollapsibleTitle
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from pathlib import Path
from textual.scrollbar import ScrollBar
from rich.style import Style
from rich.text import Text
from textual.widget import Widget
import time as _time
from rich.cells import cell_len
import inspect
from isycode.tui_theme import (
    MUTED,
    _fit_cells,
    _elapsed_label,
    _semantic_box_title,
    CYAN,
    plain_text,
    static_content,
)
from isycode.localization import tr
from isycode.tui_copy import extract_range, exact_selected_text, open_copy_menu, selectable_markdown, remember_copy_selection
from rich.markdown import Markdown as RichMarkdown

SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
SPINNER_FRAMES_ASCII = ("|", "/", "-", "\\")



def activate_on_second_click(host, event, key) -> bool:
    """Return whether this click should open a row that is already selected.

    The first click only arms that row. Textual click chains can also span
    different widgets, so event.chain alone must never activate a newly
    selected row. A later click on that same row opens it.
    """
    if getattr(host, "_activate_key", None) == key:
        host._activate_key = None
        return True
    host._activate_key = key
    return False


class PreviewOptionList(OptionList):
    """Show option detail on one click and select only on a second click."""

    async def _on_click(self, event: Click) -> None:
        option_index = event.style.meta.get("option")
        if (option_index is None or option_index < 0 or option_index >= len(self._options)
                or self._options[option_index].disabled):
            return
        prevent_default = getattr(event, "prevent_default", None)
        if prevent_default is not None:
            prevent_default()
        self.highlighted = option_index
        if activate_on_second_click(self, event, option_index):
            self.action_select()


class Banner(Static):
    """Compact terminal header with the active workspace."""

    def set_compact(self, compact: bool) -> None:
        del compact
        self.styles.height = 1
        wordmark = ":3_ ISYCODE"
        header = Text(wordmark, style="bold #e94560")
        identity = getattr(self.app, "_workspace_identity", None)
        launch = identity.launch_dir if identity else Path.cwd().resolve()
        path = str(launch)
        rail = self.screen.query_one(SidePanel)
        width = self.app.size.width
        if rail.display and rail.region.width:
            # Use the sidebar's measured left edge after layout. Subtracting its
            # width from the terminal width can overestimate the main column
            # when borders or platform-specific layout insets are present.
            measured_width = rail.region.x - self.region.x
            if measured_width > 0:
                width = measured_width
            else:
                width -= rail.region.width
        mode = "Security"
        workspace_mode = getattr(self.app, "_workspace_mode", None)
        if callable(workspace_mode):
            try:
                mode = "Classic" if workspace_mode() == "classic" else "Security"
            except Exception:
                mode = "Security"
        mark = f"  {'[C]' if mode == 'Classic' else '[S]'} {mode}" if getattr(self.app, "_ascii_only", False) else f"  ◇ {mode}"
        # Two spaces are prepended to the path, and two more stay clear of the frame.
        available = max(1, width - 4 - cell_len(wordmark + mark))
        if cell_len(path) > available:
            tail = path[-max(0, available - 1):] if available > 1 else ""
            while cell_len(tail) > available - 1:
                tail = tail[1:]
            path = "…" + tail
        header.append(f"  {path}", style=MUTED)
        header.append(" " * max(0, width - 2 - cell_len(header.plain + mark)))
        header.append(mark, style=CYAN if mode == "Classic" else MUTED)
        self.update(header)


class ActivityStatus(Static):
    """Repaint the cat after this widget receives its final resized geometry."""

    def on_resize(self, event) -> None:
        if self.is_mounted and self.app.is_mounted:
            self.app._refresh_activity()


class IdleBoard(Static):
    """One-time ASCII landscape and integration status in the chat history."""

    def on_mount(self) -> None:
        self.styles.height = "auto"
        self._painted_width = 0
        self._painted_rows = 0

    def on_resize(self, event) -> None:
        width = self.content_size.width
        rows = self.app._landscape_row_budget()
        if width and (width, rows) != (self._painted_width, self._painted_rows):
            self.app._paint_idle()


class BoxTitle(CollapsibleTitle, inherit_bindings=False):
    BINDINGS = [Binding("space", "toggle_collapsible", "Expand / collapse", show=False)]

    def action_toggle_collapsible(self) -> None:
        if isinstance(self.parent, ExpandableBox):
            self.parent.action_toggle_box()

    def on_mouse_down(self, event):
        if isinstance(self.parent, ExpandableBox):
            remember_copy_selection(self.parent)

    async def _on_click(self, event) -> None:
        # prevent_default skips CollapsibleTitle._on_click. Textual runs every
        # handler in the class chain, and that base handler would toggle again.
        event.prevent_default()
        event.stop()
        self.focus(scroll_visible=False)
        parent = self.parent
        if event.chain == 2 and isinstance(parent, ExpandableBox):
            open_copy_menu(parent, parent.copy_text())


class ExpandableBox(Collapsible, inherit_bindings=False):
    """Local keyboard expansion, shared by chat cards and sidebar sections."""

    can_focus = True
    BINDINGS = [Binding("space", "toggle_box", "Expand / collapse", show=False)]
    DEFAULT_CSS = """
    ExpandableBox { border-bottom: solid #414650; border-subtitle-align: right; }
    ExpandableBox:focus-within { border-bottom: solid #bb8cff; }
    ExpandableBox CollapsibleTitle { width: 1fr; }
    """

    def __init__(self, *children, **kwargs) -> None:
        self._marquee_internal = False
        self._marquee_base_title = kwargs.get("title", "")
        self._marquee_enabled = False
        self._marquee_offset = 0
        self._marquee_direction = 1
        self._marquee_timer = None
        super().__init__(*children, **kwargs)
        self._title = BoxTitle(label=_semantic_box_title(self.title), collapsed_symbol=self._title.collapsed_symbol,
                               expanded_symbol=self._title.expanded_symbol, collapsed=self.collapsed)

    def on_mount(self) -> None:
        self._marquee_enabled = bool(getattr(self.app, "_compact_marquee_default", False)) and not getattr(self.app, "_reduced_motion", False)
        if self._marquee_enabled:
            self._marquee_timer = self.set_interval(0.18, self._marquee_tick)

    def on_unmount(self) -> None:
        if self._marquee_timer is not None:
            self._marquee_timer.stop()
            self._marquee_timer = None

    def _watch_title(self, title: str) -> None:
        if not getattr(self, "_marquee_internal", False):
            self._marquee_base_title = title
        self._title.label = _semantic_box_title(title)

    def _compact_preview(self) -> str:
        if hasattr(self, "_full_text"):
            return " ".join(self._full_text[:500].split())
        return " ".join(" ".join(plain_text(widget).split()) for widget in self.query(Static)
                        if not isinstance(widget, CollapsibleTitle))

    def toggle_marquee(self) -> None:
        self._marquee_enabled = not self._marquee_enabled and not getattr(self.app, "_reduced_motion", False)
        self._marquee_offset = 0
        self._marquee_direction = 1
        if self._marquee_timer is not None:
            self._marquee_timer.stop()
            self._marquee_timer = None
        if self._marquee_enabled and self.is_mounted:
            self._marquee_timer = self.set_interval(0.18, self._marquee_tick)
        if not self._marquee_enabled:
            if hasattr(self, "_paint_preview"):
                self._paint_preview()
            else:
                self._set_marquee_title(self._marquee_base_title)
        self._marquee_tick()

    def _set_marquee_title(self, title: str) -> None:
        self._marquee_internal = True
        try:
            self.title = title
        finally:
            self._marquee_internal = False

    def _marquee_tick(self) -> None:
        if not self._marquee_enabled or not self.collapsed or getattr(self, "_streaming", False):
            return
        preview = self._compact_preview()
        base = getattr(self, "_base_title", self._marquee_base_title)
        budget = self.content_size.width - cell_len(base) - 9
        if not preview or budget < 1 or "Running" in base:
            return
        maximum = max(0, len(preview) - budget)
        self._marquee_offset = min(maximum, max(0, self._marquee_offset))
        shown = _fit_cells(preview[self._marquee_offset:], budget)
        self._set_marquee_title(base + "     " + shown)
        if maximum:
            if self._marquee_offset >= maximum:
                self._marquee_direction = -1
            elif self._marquee_offset == 0:
                self._marquee_direction = 1
            self._marquee_offset += self._marquee_direction

    def _watch_collapsed(self, collapsed: bool) -> None:
        if collapsed and (self.has_focus_within or self.has_focus):
            self.focus(scroll_visible=False)
        super()._watch_collapsed(collapsed)
        if not collapsed and not hasattr(self, "_full_text"):
            self._set_marquee_title(self._marquee_base_title)
        self._paint_expand_hint()


    def on_descendant_focus(self, event) -> None:
        self._paint_expand_hint()
        if hasattr(self, "_paint_preview"):
            self._paint_preview()

    def on_descendant_blur(self, event) -> None:
        self.call_after_refresh(self._paint_expand_hint)
        if hasattr(self, "_paint_preview"):
            self.call_after_refresh(self._paint_preview)

    def on_focus(self) -> None:
        self._paint_expand_hint()
        if hasattr(self, "_paint_preview"):
            self._paint_preview()

    def on_blur(self) -> None:
        self.on_focus()

    def _paint_expand_hint(self) -> None:
        self.border_subtitle = Text(tr("Space expand / collapse · double-click copy"), style=MUTED) if self.has_focus or self.has_focus_within else ""

    def copy_text(self) -> str:
        if hasattr(self, "_full_text"):
            return self._full_text
        return "\n".join(widget.selection_text for widget in self.query(SelectableText)) or "\n".join(
            plain_text(widget) for widget in self.query(Static) if not isinstance(widget, CollapsibleTitle))

    def action_toggle_box(self) -> None:
        self.collapsed = not self.collapsed

    def on_mouse_down(self, event):
        if event.widget is self:
            remember_copy_selection(self)

    def on_click(self, event) -> None:
        if event.widget is not self:
            return
        self.focus(scroll_visible=False)
        if event.chain == 2:
            event.prevent_default()
            event.stop()
            open_copy_menu(self, self.copy_text())


# Keep native Collapsible composition and messages; unify our existing boxes.
Collapsible = ExpandableBox


class ActivateTree(Tree):
    """One click selects a node. A second click on that node (double-click) or Enter opens it."""

    async def _on_click(self, event: Click) -> None:
        async with self.lock:
            meta = event.style.meta
            if "line" not in meta:
                return
            event.prevent_default()
            event.stop()
            line = meta["line"]
            if meta.get("toggle"):
                node = self.get_node_at_line(line)
                if node is not None:
                    self._toggle_node(node)
                return
            self.focus()
            self.cursor_line = line
            node = self.get_node_at_line(line)
            if node is not None:
                if activate_on_second_click(self, event, line):
                    await self._activate_node(node)

    async def action_select_cursor(self) -> None:
        if self.cursor_node is not None:
            await self._activate_node(self.cursor_node)

    async def _activate_node(self, node: TreeNode) -> None:
        data = node.data
        if isinstance(data, dict) and data.get("kind") != "directory":
            uri = data.get("path")
            if isinstance(uri, str):
                preview_fn = getattr(self.app, "_preview_file", None)
                if callable(preview_fn):
                    self.app.run_worker(preview_fn(uri, modal=True), group="file-preview")
                    return
        self.select_node(node)


class SidePanel(Vertical):
    """Right rail for live integration status and the authorized file browser."""

    def compose(self) -> ComposeResult:
        yield Static(tr("ISYCODE  ·  WORKSPACE"), classes="panel-title")
        with Horizontal(id="rail-tabs"):
            yield Button(tr("Overview"), id="show-overview")
            yield Button(tr("Files"), id="show-files")
        with QuietVerticalScroll(id="overview-view"):
            with Vertical(id="rail-card"):
                with Collapsible(title=tr("IsySentinel"), id="rail-sentinel"):
                    yield Static(tr("Reading Workspace Authority and the action journal…"),
                                 id="sentinel-status", classes="rail-copy")
                with Collapsible(title=tr("MCPs"), id="rail-mcp"):
                    yield Static(tr("Tool service status has not been checked."), id="mcp-status", classes="rail-copy")
                with Collapsible(title=tr("LSPs"), id="rail-lsp"):
                    yield Static(tr("Checking installed language servers…"), id="lsp-status", classes="rail-copy")
                    yield Button(tr("Install commands"), id="lsp-install-hint", compact=True)
                    yield Static(tr(""), id="lsp-install-note", classes="rail-copy")
                with Collapsible(title=tr("Skills"), id="rail-skills"):
                    yield Static(tr("ISyCode skill catalog has not been checked."), id="skill-status", classes="rail-copy")
                    yield ActivateTree(tr("ISyCode skills"), id="skills-tree")
                    yield Static(tr(""), id="skill-detail", classes="rail-copy")
                with Collapsible(title=tr("Connections · 4"), id="rail-connections", collapsed=True):
                    with Collapsible(title=tr("ISyCo Gateway"), id="rail-gateway"):
                        yield Static(tr("Gateway status has not been checked."), id="gateway-status", classes="rail-copy")
                    with Collapsible(title=tr("Gateway MCP"), id="rail-gateway-mcp"):
                        yield Static(tr("Tool catalog has not been checked."), id="gateway-mcp-status", classes="rail-copy")
                    with Collapsible(title=tr("Mobile Host"), id="rail-mobile"):
                        yield Static(tr("Not started"), id="mobile-host-status", classes="rail-copy")
                        yield Static(tr("No mobile clients connected."), id="mobile-client-status", classes="rail-copy")
                    with Collapsible(title=tr("Bridge Coordination"), id="rail-bridge"):
                        yield Static(tr("Disabled · No Bridge Handshake"), id="bridge-status", classes="rail-copy")
                with Collapsible(title=tr("Workspace"), id="rail-workspace"):
                    yield Static(tr(""), id="workspace-label", classes="rail-copy")
                    yield Static(tr(""), id="workspace-launch-label", classes="rail-copy")
                    yield Static(tr(""), id="workspace-source-label", classes="rail-copy")
                    yield Static(tr(""), id="workspace-authority-label", classes="rail-copy")
            yield Button(tr("Refresh integrations"), id="refresh-openisy")
            yield Button(tr("No plan pending"), id="review-plan", disabled=True)
        with Vertical(id="files-view"):
            with Horizontal(id="file-controls"):
                yield Button(tr("↑ Up"), id="file-up")
                yield Button(tr("Refresh"), id="file-refresh")
                yield Button(tr("Folders"), id="workspace-folders")
            yield Input(placeholder=tr("Search workspace paths…"), id="file-search")
            yield ActivateTree(tr("Workspace"), id="workspace-tree")
            with Horizontal(id="file-actions"):
                yield Button(tr("Copy path"), id="file-copy-path", disabled=True)
                yield Button(tr("Open preview"), id="file-open-preview", disabled=True)
            with Vertical(id="file-preview-box"):
                yield Static("", id="file-preview-meta", markup=False)
                with VerticalScroll(id="file-preview-scroll"):
                    yield SelectableText(tr("Select a file to preview it."), id="file-preview", classes="rail-copy", markup=False)

    def on_mount(self) -> None:
        for button in self.query(Button):
            button.compact = True
        self.query_one("#show-overview", Button).add_class("rail-lit")


class ToolActivityGroup(ExpandableBox):
    """Consecutive identical operations form one parent with retained branches."""

    def __init__(self, operation: str, leaf: ExpandableBox, label: str):
        self.operation = operation
        self.leaves = [(leaf, label)]
        self._running_leaves: set[int] = {id(leaf)}
        self._spinner_idx = 0
        self._spinner_timer = None
        super().__init__(leaf, title=label + " · Running", collapsed=True, classes="tool-activity")
        self._paint_branches()

    def on_mount(self) -> None:
        self._check_spinner()

    def on_unmount(self) -> None:
        self._stop_spinner()

    def _check_spinner(self) -> None:
        if bool(self._running_leaves):
            if self._spinner_timer is None and self.is_mounted:
                self._spinner_timer = self.set_interval(0.12, self._tick_spinner)
        else:
            self._stop_spinner()

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _tick_spinner(self) -> None:
        if not bool(self._running_leaves):
            self._stop_spinner()
            return
        from isycode.tui_theme import ascii_only
        frames = SPINNER_FRAMES_ASCII if ascii_only() else SPINNER_FRAMES
        self._spinner_idx = (self._spinner_idx + 1) % len(frames)
        frame = frames[self._spinner_idx]
        if len(self.leaves) == 1:
            lbl = self.leaves[0][1]
            base = lbl.split(" · Running")[0] if " · Running" in lbl else lbl
            self.title = f"{base} · {frame} Running"
        else:
            self.title = f"{self.operation} · {len(self.leaves)} calls · {frame}"

    async def add_leaf(self, leaf: ExpandableBox, label: str) -> None:
        if len(self.leaves) == 1:
            self.leaves[0][0].collapsed = True
        self.leaves.append((leaf, label))
        self._running_leaves.add(id(leaf))
        self.title = f"{self.operation} · {len(self.leaves)} calls"
        await self.query_one(self.Contents).mount(leaf)
        self._paint_branches()
        self._check_spinner()

    def _paint_branches(self) -> None:
        for index, (leaf, label) in enumerate(self.leaves):
            prefix = "└─ " if index == len(self.leaves) - 1 else "├─ "
            multiple = len(self.leaves) > 1
            if hasattr(leaf, "title"):
                leaf.title = prefix + label if multiple else label
            elif hasattr(leaf, "border_title"):
                leaf.border_title = Text(prefix + label if multiple else label, style=CYAN)
            if hasattr(leaf, "_title"):
                leaf._title.display = multiple
            if not multiple and hasattr(leaf, "collapsed"):
                leaf.collapsed = False

    def finish_leaf(self, leaf: ExpandableBox, label: str) -> None:
        self._running_leaves.discard(id(leaf))
        self.leaves = [(item, label if item is leaf else old) for item, old in self.leaves]
        self._paint_branches()
        self._check_spinner()
        if not bool(self._running_leaves):
            self._stop_spinner()
            self.title = label if len(self.leaves) == 1 else f"{self.operation} · {len(self.leaves)} calls"


class ThoughtBlock(Collapsible, inherit_bindings=False):
    """A reasoning block: streams live, then collapses to 'thought for Xs'.

    Space cycles the focused view; double-click opens the copy menu,
    native via Textual's Collapsible. The body is passed as a CHILD, not
    via a compose override: Collapsible.compose() builds the internal
    Contents container that '-collapsed' CSS hides — overriding compose
    destroyed it and the block never collapsed.
    """

    can_focus = True
    BINDINGS = [
        Binding("space", "toggle_box", "Expand thinking", show=False),
        Binding("ctrl+a", "select_thought_all", "Select thinking", show=False, priority=True),
        Binding("ctrl+c", "copy_thought_selection", "Copy", show=False, priority=True),
    ]

    def __init__(self, title: str = "thinking...", **kwargs) -> None:
        self._full_text = ""
        self._text_parts: list[str] = []
        self._pending_text_paint = None
        self._base_title = title
        self._expanded = False
        body = SelectableText(Text("", style=MUTED))
        self._body = body
        super().__init__(body, title=title, collapsed=False, **kwargs)
        self._body = body
        self._streaming = True
        self._started_at = _time.monotonic()
        self._elapsed_timer = None

    def on_mount(self) -> None:
        super().on_mount()
        self._started_at = _time.monotonic()
        self._update_elapsed_title()
        self._elapsed_timer = self.set_interval(1, self._update_elapsed_title)
        if self._text_parts:
            self._flush_pending_text()

    def _update_elapsed_title(self) -> None:
        if self._streaming:
            elapsed = _elapsed_label(_time.monotonic() - self._started_at)
            frame = int(_time.monotonic() - self._started_at) % 2
            reduced = getattr(self.app, "_reduced_motion", False)
            glyph = "*" if getattr(self.app, "_ascii_only", False) else ("◇" if reduced or not frame else "◆")
            self._base_title = f"{glyph} {tr('Thinking…')} · {elapsed}"
            self._paint_preview()

    def on_unmount(self) -> None:
        super().on_unmount()
        if self._elapsed_timer is not None:
            self._elapsed_timer.stop()
            self._elapsed_timer = None

    def scroll_visible(self, *args, **kwargs):
        # Collapsible schedules this on its initial expansion. During a live
        # response the chat owns scrolling, including the user's history view.
        if self._streaming or self.collapsed:
            return False
        return super().scroll_visible(*args, **kwargs)

    def set_text(self, text: str) -> None:
        """Thread-safe entry: replace the reasoning body."""
        if self._pending_text_paint is not None:
            self._pending_text_paint.stop()
            self._pending_text_paint = None
        self._text_parts = [text] if text else []
        self._full_text = text
        self._paint_preview()

    def append_text(self, chunk: str) -> None:
        """Buffer a stream fragment and repaint at most once per frame window."""
        if not chunk:
            return
        self._text_parts.append(chunk)
        if self.is_mounted and self._pending_text_paint is None:
            self._pending_text_paint = self.set_timer(0.08, self._flush_pending_text)

    def _flush_pending_text(self) -> None:
        timer = self._pending_text_paint
        self._pending_text_paint = None
        if timer is not None:
            timer.stop()
        self._full_text = "".join(self._text_parts)
        self._paint_preview()
        if self.is_mounted and hasattr(self.parent, "follow_tail"):
            self.parent.follow_tail()

    def _paint_preview(self) -> None:
        if not hasattr(self, "_body"):
            return
        text = Text(self._full_text, style=MUTED)
        width = self._body.content_size.width or max(1, self.content_size.width - 6)
        if self.is_mounted:
            wrap_sample = Text(self._full_text[:max(1, width) * 4], style=MUTED)
            lines = wrap_sample.wrap(self.app.console, max(1, width))
        else:
            lines = self._full_text[:max(1, width) * 4].split("\n")
        more = len(lines) > 2 or self._full_text.count("\n") >= 2 or len(self._full_text) > max(1, width) * 2
        self._preview_more = more
        # Clip the view rather than inserting soft-wrap newlines into its copy source.
        self._body.styles.max_height = 2 if not self._expanded and more else None
        if self.collapsed:
            budget = max(1, self.content_size.width - cell_len(self._base_title) - 9)
            preview = " ".join(self._full_text[:budget * 4].split())
            self.title = self._base_title + ("     " + _fit_cells(preview, budget) if preview else "")
        else:
            self.title = self._base_title
        self._body.set_selectable_content(text, text.plain)
        self.border_subtitle = (Text(tr("Space expand / collapse · double-click copy"), style=MUTED)
                                if more and (self.has_focus or self.has_focus_within) else "")

    def _watch_collapsed(self, collapsed: bool) -> None:
        was_following = self._chat_following_tail()
        if collapsed and (self.has_focus_within or self.has_focus):
            self.focus(scroll_visible=False)
        super()._watch_collapsed(collapsed)
        self._paint_preview()
        if was_following:
            self.call_after_refresh(self._reanchor_chat_tail)


    def _chat_following_tail(self) -> bool:
        # A focus-driven scroll_to_center releases the chat's tail anchor while
        # the block toggles; re-arm it so the streaming answer stays reachable.
        chat = self.parent
        return isinstance(chat, ChatArea) and chat._following_tail()

    def _reanchor_chat_tail(self) -> None:
        chat = self.parent
        if isinstance(chat, ChatArea) and chat.is_mounted:
            chat.resume_tail()

    def action_toggle_box(self) -> None:
        # Cycle through every view: title -> preview -> full -> title.
        if self.collapsed:
            self._expanded = False
            self.collapsed = False
        elif self._expanded or not getattr(self, "_preview_more", False):
            self._expanded = False
            self.collapsed = True
        else:
            self._expanded = True
        self._paint_preview()

    def on_resize(self) -> None:
        self._paint_preview()

    def on_click(self, event) -> None:
        if isinstance(event.widget, SelectableText):
            return
        super().on_click(event)

    def action_select_thought_all(self) -> None:
        self._body.text_select_all()

    def action_copy_thought_selection(self) -> None:
        self._body.action_copy_visible_selection()

    def collapse_to(self, seconds: float) -> None:
        """Collapse with the elapsed-time title."""
        if self._pending_text_paint is not None:
            self._flush_pending_text()
        self._base_title = tr("Thought for {elapsed}", elapsed=_elapsed_label(seconds))
        self._streaming = False
        if self._elapsed_timer is not None:
            self._elapsed_timer.stop()
            self._elapsed_timer = None
        self._expanded = False
        self.collapsed = True
        self._paint_preview()


# Textual < 2 anchors a child (``child.anchor(animate=...)``); Textual 2+ anchors
# the scrollable itself (``container.anchor(True)``) and releases it on user scroll.
_CHILD_ANCHOR = "animate" in inspect.signature(Widget.anchor).parameters


class QuietScrollBar(ScrollBar):
    """Persistent position thumb with quiet arrows and native drag controls."""

    def render(self):
        height = self.size.height
        maximum = max(0, self.window_virtual_size - self.window_size)
        ratio = min(1.0, max(0.0, self.position / maximum)) if maximum else 0.0
        thumb = 1 + round(ratio * max(0, height - 3)) if height >= 3 else 0
        result = Text()
        for index in range(height):
            row = " ▲ " if index == 0 and height >= 3 else (
                " ▼ " if index == height - 1 and height >= 3 else (
                    "━━━" if index == thumb else "   "))
            action = "grab" if index == thumb else ("scroll_up" if index < thumb else "scroll_down")
            result.append(row, style=Style(color="#9aa3ad", meta={"@mouse.down": action}))
            if index < height - 1:
                result.append("\n")
        return result

    def _settle(self):
        self._direction = 0
        self.refresh()


class QuietVerticalScroll(VerticalScroll):
    """Vertical scroller that shows the chat's quiet thumb only when content is taller."""

    @property
    def vertical_scrollbar(self):
        if self._vertical_scrollbar is None:
            bar = QuietScrollBar(vertical=True, name="vertical", thickness=3)
            self._vertical_scrollbar = bar
            bar.display = False
            self.app._start_widget(self, bar)
        return self._vertical_scrollbar


class ChatArea(QuietVerticalScroll):
    """Chat with a layout-aware tail anchor that user scrolling can release."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tail = Static(tr(""), classes="chat-tail")
        self._tail.styles.height = 1

    def compose(self):
        yield self._tail

    def on_mount(self):
        self.resume_tail()

    def mount(self, *widgets, before=None, after=None):
        if before is None and after is None and self._tail.parent is self:
            before = self._tail
        return super().mount(*widgets, before=before, after=after)

    def remove_children(self, selector="*"):
        if selector == "*":
            selector = [child for child in self.children if child is not self._tail]
            self.resume_tail()
        return super().remove_children(selector)

    def pause_tail(self):
        if _CHILD_ANCHOR:
            self._clear_anchor()
        else:
            self.anchor(False)

    def _anchor_tail(self):
        if _CHILD_ANCHOR:
            self._tail.anchor(animate=False)
        else:
            self.anchor(True)

    def _following_tail(self) -> bool:
        if _CHILD_ANCHOR:
            return self._anchored is self._tail
        return bool(self._anchored) and not getattr(self, "_anchor_released", False)

    def resume_tail(self):
        self._anchor_tail()
        self.follow_tail()

    def follow_tail(self):
        # Mount/update changes are measured later, so do not scroll to the old
        # extent here. A queued callback must still respect a user's scroll-up.
        self.call_after_refresh(self._follow_measured_tail)

    def _follow_measured_tail(self):
        if self._following_tail():
            self.scroll_end(animate=False, immediate=True)

    def watch_scroll_y(self, old_value, new_value):
        super().watch_scroll_y(old_value, new_value)
        if _CHILD_ANCHOR and self.is_mounted and new_value >= self.max_scroll_y:
            self._tail.anchor(animate=False)

    def action_scroll_end(self):
        super().action_scroll_end()
        self.resume_tail()


class SelectableText(Static):
    """Focusable chat text with Ctrl+A/Ctrl+C routed through workspace authority."""

    can_focus = True
    BINDINGS = [
        Binding("ctrl+a", "select_visible_all", "Select all", show=False, priority=True),
        Binding("ctrl+c", "copy_visible_selection", "Copy", show=False, priority=True),
    ]

    def __init__(self, content="", *, selection_text: str | None = None, **kwargs) -> None:
        if isinstance(content, str):
            kwargs.setdefault("markup", False)
        super().__init__(content, **kwargs)
        self.selection_text = (selection_text if selection_text is not None else
                               content.plain if isinstance(content, Text) else
                               content if isinstance(content, str) else "")

    def on_mouse_down(self, event):
        remember_copy_selection(self)

    async def _on_click(self, event) -> None:
        event.prevent_default()
        event.stop()
        self.focus(scroll_visible=False)
        if event.chain == 2:
            container = next((parent for parent in self.ancestors if isinstance(parent, (ExpandableBox, CommandOutputCard))), None)
            self.render()
            whole = container.copy_text() if container is not None else self._selection_plain
            open_copy_menu(self, whole)

    def render(self):
        original = static_content(self)
        content = super().render()
        if isinstance(original, RichMarkdown):
            if getattr(self, "_markdown_source", None) is not original:
                self._markdown_source = original
                self._markdown_text = selectable_markdown(original)
            content = self._markdown_text
        self._selection_plain = getattr(content, "plain", str(content))
        return content

    def set_selectable_content(self, content, selection_text: str) -> None:
        self.selection_text = selection_text
        self.update(content)

    def get_selection(self, selection):
        self.render()
        return extract_range(self._selection_plain, selection), "\n"

    def action_select_visible_all(self) -> None:
        self.text_select_all()

    def action_copy_visible_selection(self) -> None:
        selected = exact_selected_text(self.screen)
        if selected:
            self.app.run_worker(
                self.app._request_clipboard_copy(selected, "selection"),
                group="clipboard-user")


class CommandOutputCard(VerticalScroll, inherit_bindings=False):
    """Two visible output rows; Space opens the retained command output."""

    can_focus = True
    BINDINGS = [Binding("space", "toggle_output", "Expand output", show=False)]
    DEFAULT_CSS = """
    CommandOutputCard { height: 4; width: 100%; padding: 0 1; margin: 1 0; border: round #414650; background: #17191f; }
    CommandOutputCard:focus-within { border: round #bb8cff; }
    CommandOutputCard.-expanded { height: 18; }
    CommandOutputCard .command-output-body { height: auto; width: 100%; }
    """

    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command
        self.output = ""
        self.status = "Running"
        self.receipt = ""
        self.output_truncated = False
        self.expanded = False
        self._spinner_idx = 0
        self._spinner_timer = None
        self._body = SelectableText(classes="command-output-body")
        self.border_title = Text(command, style=CYAN)
        self._paint_output()

    def on_mount(self) -> None:
        if self.status == "Running" and self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.12, self._tick_spinner)

    def on_unmount(self) -> None:
        self._stop_spinner()

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _tick_spinner(self) -> None:
        if self.status != "Running":
            self._stop_spinner()
            return
        from isycode.tui_theme import ascii_only
        frames = SPINNER_FRAMES_ASCII if ascii_only() else SPINNER_FRAMES
        self._spinner_idx = (self._spinner_idx + 1) % len(frames)
        self._paint_output()

    def compose(self) -> ComposeResult:
        yield self._body

    def append_output(self, chunk: str) -> None:
        self.output += chunk
        self._paint_output()

    def finish(self, status: str, *, output: str | None = None,
               receipt: str = "", truncated: bool = False) -> None:
        self.status = status
        self._stop_spinner()
        if output is not None:
            self.output = output
        self.receipt = receipt
        self.output_truncated = truncated
        self._paint_output()

    def _paint_output(self) -> None:
        note = " · output limit reached" if self.output_truncated else ""
        from isycode.tui_theme import ascii_only
        frames = SPINNER_FRAMES_ASCII if ascii_only() else SPINNER_FRAMES
        frame = frames[self._spinner_idx]
        spinner_prefix = f"{frame} " if self.status == "Running" else ""
        self.border_subtitle = Text(f"{spinner_prefix}{tr(self.status)}{note} · {tr('Space expand / collapse · double-click copy')}", style=MUTED)
        if self.expanded:
            shown = self.output or "No output."
            if self.receipt:
                shown += f"\n\nReceipt · {self.receipt}"
            if self.output_truncated:
                shown += "\nOutput reached the execution owner's limit; more bytes were not retained."
        else:
            shown = "\n".join(self.output.splitlines()[-2:])
            if not shown:
                shown = f"{frame} Waiting for output…" if self.status == "Running" else "No output."
        self._body.set_selectable_content(
            Text(shown, style=MUTED), shown)

    def copy_text(self) -> str:
        return self.output

    def action_toggle_output(self) -> None:
        self.expanded = not self.expanded
        self.set_class(self.expanded, "-expanded")
        self._paint_output()
        self.scroll_home(animate=False)

    def on_mouse_down(self, event):
        if event.widget is self:
            remember_copy_selection(self)

    def on_click(self, event) -> None:
        if event.widget is not self:
            return
        self.focus()
        if event.chain == 2:
            event.prevent_default()
            event.stop()
            open_copy_menu(self, self.copy_text())
