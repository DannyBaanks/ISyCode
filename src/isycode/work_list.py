"""Same-window conversation board. It lists chats; it does not launch agents."""
from datetime import datetime, timezone
from rich.cells import cell_len
from rich.text import Text
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.message import Message
from rich.style import Style
from textual.binding import Binding
from textual.widgets import Button, OptionList, Static
from isycode.tui_widgets import activate_on_second_click
from isycode.localization import tr
from textual.widgets.option_list import Option


def clock_label(value: str | None) -> str:
    parsed = _stamp(value)
    return parsed.strftime("%H:%M") if parsed is not None else ""


def age_label(value: str | float | None, *, now: datetime | None = None) -> str:
    parsed = _stamp(value)
    if parsed is None and isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, timezone.utc).astimezone()
    if parsed is None:
        return ""
    current = now or datetime.now(parsed.tzinfo)
    seconds = int((current - parsed).total_seconds())
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _stamp(value: str | float | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def fit_heading(path: str, tail: str, width: int) -> str:
    """Keep the workspace path and the counts on one line."""
    gap = "    "
    full = f"{path}{gap}{tail}"
    if width < 1 or cell_len(full) <= width:
        return full
    if cell_len(tail) >= width:
        return tail
    budget = width - cell_len(tail) - cell_len(gap)
    if budget < 4:
        return tail
    shown = path
    while shown and cell_len(shown) > budget:
        shown = shown[1:]
    if shown != path:
        shown = "…" + shown
        while cell_len(shown) > budget and len(shown) > 1:
            shown = "…" + shown[2:]
    return f"{shown}{gap}{tail}"


# Session states, dash-style. The symbol identifies the state; the section
# title and the detail panel name it, so it still reads without color.
STATUS_ORDER = ("generating", "background", "waiting", "idle")
STATUS_LABELS = {"generating": "Working", "background": "Background",
                 "waiting": "Needs input", "idle": "Idle"}
_STATUS_GLYPHS = {"generating": ("●", "*"), "background": ("◐", "~"),
                  "waiting": ("◆", "?"), "idle": ("○", "-")}
_STATUS_COLORS = {"generating": "#77d8b0", "background": "#7fb3d5",
                  "waiting": "#e5c07b", "idle": "#6d7580"}


def status_glyph(status: str) -> str:
    from isycode.tui_theme import ascii_only
    pair = _STATUS_GLYPHS.get(status, _STATUS_GLYPHS["idle"])
    return pair[1] if ascii_only() else pair[0]


def context_badge(chars: int | None, limit: int | None) -> tuple[str, int | None]:
    """A local estimate (~4 chars/token) of the saved transcript, as a list badge."""
    if type(chars) is not int or chars <= 0:
        return "", None
    tokens = (chars + 3) // 4
    shown = f"{tokens / 1_000_000:.1f}M" if tokens >= 1_000_000 else f"{tokens // 1000}k" if tokens >= 1000 else str(tokens)
    if type(limit) is not int or limit <= 0:
        return f"~{shown}", None
    percent = min(100, round(tokens * 100 / limit))
    return f"~{percent}%", percent


def _percent_color(percent: int | None) -> str:
    if percent is None:
        return "#6d7580"
    return "#77d8b0" if percent < 60 else "#e5c07b" if percent < 85 else "#e06c75"


def preview_line(text: str | None) -> str:
    if not isinstance(text, str):
        return ""
    clean = " ".join(text.replace("\x1b", "").split())
    return clean[:72]


class SessionOptionList(OptionList):
    """First click previews; a subsequent click on that row opens it."""
    BINDINGS = [Binding("ctrl+d", "delete_session", "Delete session", show=False)]

    class DeleteRequested(Message):
        def __init__(self, session_id):
            super().__init__()
            self.session_id = session_id

    _preview_click_id = None

    async def _on_click(self, event):
        event.stop()
        event.prevent_default()
        index = event.style.meta.get("option")
        if index is None or not 0 <= index < self.option_count:
            return
        option = self.get_option_at_index(index)
        if option.disabled:
            return
        if event.style.meta.get("delete_session") == option.id:
            self._preview_click_id = None
            self.post_message(self.DeleteRequested(option.id))
            return
        self.focus()
        self.highlighted = index
        if self._preview_click_id == option.id:
            self._preview_click_id = None
            self.action_select()
        else:
            self._preview_click_id = option.id

    def action_delete_session(self):
        if self.highlighted is None:
            return
        option = self.get_option_at_index(self.highlighted)
        if option.disabled or option.id in {None, "memory", "child"}:
            return
        self._preview_click_id = None
        self.post_message(self.DeleteRequested(option.id))

    def action_cursor_down(self):
        self._preview_click_id = None
        super().action_cursor_down()

    def action_cursor_up(self):
        self._preview_click_id = None
        super().action_cursor_up()


class SessionMessageScreen(ModalScreen):
    CSS = """
    SessionMessageScreen { align: center middle; background: #000000 58%; }
    #session-message-card { width: 90%; max-width: 110; height: 90%; padding: 0 1; border: solid #718291; background: #000000; }
    #session-message-scroll { height: 1fr; margin: 1 0; }
    #session-message-content { height: auto; }
    """
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, message):
        super().__init__()
        self.message = message

    def compose(self):
        with Vertical(id="session-message-card", classes="isy-dialog"):
            yield Static(Text(tr("Session · full last message"), style="bold #edf1f5"), classes="isy-dialog-title")
            with VerticalScroll(id="session-message-scroll", classes="isy-dialog-body"):
                yield Static(Text(self.message), id="session-message-content")
            yield Button(tr("Close · Esc"), id="session-message-close")

    def on_mount(self):
        self.query_one("#session-message-scroll").focus()

    def action_close(self):
        self.dismiss()

    def on_button_pressed(self, event):
        if event.button.id == "session-message-close":
            self.dismiss()


class SessionDetails(Static):
    can_focus = True
    BINDINGS = [Binding("enter,space", "expand_message", "Full message", show=False)]

    class Resized(Message):
        """The preview must use the detail panel's completed layout."""

    def on_resize(self):
        self.post_message(self.Resized())

    def on_click(self, event):
        # prevent_default skips Widget._on_click, which would select all the
        # preview text on a double-click instead of leaving the open in place.
        event.prevent_default()
        event.stop()
        self.focus()
        if activate_on_second_click(self, event, "message"):
            self.action_expand_message()

    def action_expand_message(self):
        message = getattr(self, "full_message", "")
        loader = getattr(self, "full_message_loader", None)
        if message and callable(loader):
            # The list keeps a capped preview; read the whole message on demand.
            self.run_worker(self._expand_loaded(loader, message), group="session-message")
        elif message:
            self.app.push_screen(SessionMessageScreen(message))

    async def _expand_loaded(self, loader, fallback):
        import asyncio
        try:
            message = await asyncio.to_thread(loader)
        except (OSError, ValueError, RuntimeError):
            message = None
        self.app.push_screen(SessionMessageScreen(message or fallback))


def quoted_preview(text, console, width, max_lines):
    width, max_lines = max(3, width), max(1, max_lines)
    lines = Text("“" + " ".join(text.split()) + "”").wrap(console, width, overflow="fold")
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1].truncate(width - 2, overflow="crop")
        lines[-1].append("…”")
    return Text("\n").join(lines)


class WorkList(Vertical):
    DEFAULT_CSS = """
    WorkList { height: 1fr; display: none; padding: 1 2 0 2; background: #1e1f22; }
    WorkList Horizontal { height: 1; }
    WorkList Button { width: auto; min-width: 0; height: 1; min-height: 1; border: none; border-top: none; border-bottom: none; background: transparent; background-tint: transparent; color: #77d8b0; padding: 0 1; margin: 0; }
    WorkList Button:hover, WorkList Button:focus, WorkList Button.-active { border: none; border-top: none; border-bottom: none; tint: transparent; background-tint: transparent; background: #30303c; color: #f4f1ea; text-style: bold; }
    #work-body { height: 1fr; }
    #work-details { width: 35%; height: 1fr; border-left: solid #514d5a; padding: 0 2; overflow-y: auto; }
    #work-conversations { width: 1fr; }
    #work-heading { height: 1; color: #9aa3ad; }
    #work-filters { margin-top: 1; }

    #work-conversations { height: 1fr; border: none; background: transparent; padding: 0; }
    #work-conversations > .option-list--option-highlighted { background: #2a2b30; color: #f4f1ea; }
    #work-presence { height: 1; color: #6d7580; overflow-x: hidden; text-overflow: ellipsis; }
    """

    def compose(self):
        yield Static(tr(""), id="work-heading", markup=False)
        with Horizontal():
            yield Button(tr("+ New conversation"), id="work-new")
            yield Button(tr("Refresh"), id="work-refresh")
            yield Button(tr("Bridge presence…"), id="work-bridge")
            yield Button(tr("Hide"), id="work-hide")
        with Horizontal(id="work-filters"):
            yield Button(tr("All"), id="work-filter-all", classes="filter-on")
            yield Button(tr("Working"), id="work-filter-generating")
            yield Button(tr("Background"), id="work-filter-background")
            yield Button(tr("Needs input"), id="work-filter-waiting")
            yield Button(tr("Idle"), id="work-filter-idle")
        with Horizontal(id="work-body"):
            listing = SessionOptionList(id="work-conversations")
            listing.tooltip = tr("↑/↓ select · Enter or double-click open · Ctrl+D delete selected conversation")
            yield listing
            yield SessionDetails(tr("Select a conversation to inspect it."), id="work-details", markup=False)
        yield Static(tr("Bridge presence off"), id="work-presence", markup=False)

    def on_resize(self):
        if not self.is_mounted:
            return
        self.query_one("#work-details").display = self.content_size.width >= 85
        if getattr(self, "_selected_row", None):
            self.call_after_refresh(self._refresh_selected_detail)
        if hasattr(self, "_rows"):
            self.call_after_refresh(self._refresh_rows)
        compact = self.content_size.width < 62
        self.query_one("#work-new", Button).label = tr("+ New") if compact else tr("+ New conversation")
        self.query_one("#work-bridge", Button).label = tr("Bridge") if compact else tr("Bridge presence…")
        paint = getattr(self.app, "_paint_bridge_presence", None)
        if callable(paint):
            self.call_after_refresh(paint)

    def _refresh_rows(self):
        self.show_rows(self._rows, heading=self._heading)

    def show_rows(self, rows, *, heading: str = ""):
        self._rows = list(rows)
        self._heading = heading
        selected_filter = getattr(self, "_filter", "all")
        rows = [row for row in self._rows if selected_filter == "all" or row.get("status", "idle") == selected_filter]
        self.query_one("#work-heading", Static).update(heading)
        listing = self.query_one("#work-conversations", OptionList)
        highlight = listing.highlighted
        if listing._preview_click_id not in {row["id"] for row in rows}:
            listing._preview_click_id = None
        listing.clear_options()
        grouped: dict[str, list] = {key: [] for key in STATUS_ORDER}
        for row in rows:
            grouped.get(row.get("status"), grouped["idle"]).append(row)
        width = max(8, listing.content_size.width - 2)
        # The last-message line costs a row per conversation; a short list
        # (80x24 leaves about three rows) keeps one line each and the detail
        # panel carries the message.
        previews = listing.content_size.height >= self.PREVIEW_MIN_HEIGHT
        for key in STATUS_ORDER:
            items = grouped[key]
            if not items:
                continue
            listing.add_option(Option(Text(f"{tr(STATUS_LABELS[key])}  {len(items)}", style="bold #9aa3ad"),
                                      id=f"section-{key}", disabled=True))
            for row in items:
                listing.add_option(Option(self._row_text(row, key, width, previews), id=row["id"]))
        if highlight is not None and listing.option_count:
            listing.highlighted = min(highlight, listing.option_count - 1)

    PREVIEW_MIN_HEIGHT = 8

    @staticmethod
    def _row_text(row, status, width, previews=True):
        """Line 1: state · model · title … context · age [×]. Line 2: last message."""
        line = Text()
        line.append(status_glyph(status) + " ", style=_STATUS_COLORS.get(status, "#6d7580"))
        if row.get("session_kind") == "iterative":
            line.append("↻ Iterative · ", style="#77d8b0")
        if row.get("model"):
            from isycode.model_presentation import model_display_name
            line.append(model_display_name(row["model"]) + " · ", style="bold #77d8b0")
        line.append(row.get("title") or "Untitled", style="bold #f4f1ea" if row.get("current") else "")
        tail = Text()
        if row.get("context"):
            tail.append(f"  {row['context']}", style=_percent_color(row.get("context_percent")))
        if row.get("age"):
            tail.append(f"  {row['age']}", style="#6d7580")
        deletable = row["id"] not in {"memory", "child"}
        right = width - (4 if deletable else 0)
        line.truncate(max(4, right - cell_len(tail.plain)), overflow="ellipsis")
        line.append(" " * max(1, right - cell_len(line.plain) - cell_len(tail.plain)))
        line.append_text(tail)
        if deletable:
            line.append(" [×]", style=Style(color="#f87171", bold=True, meta={"delete_session": row["id"]}))
        preview = row.get("preview") if previews else ""
        if preview:
            second = Text("  ")
            who = {"user": "you: ", "assistant": "ai: "}.get(row.get("last_role") or "", "")
            if who:
                second.append(who, style="#9aa3ad")
            second.append(preview, style="#6d7580")
            second.truncate(width, overflow="ellipsis")
            line.append("\n")
            line.append_text(second)
        return line

    def on_option_list_option_highlighted(self, event):
        if event.option_list.id != "work-conversations":
            return
        row = next((item for item in getattr(self, "_rows", []) if item["id"] == event.option.id), None)
        if row is None:
            return
        self._selected_row = row
        self._render_detail(row)

    def _refresh_selected_detail(self):
        row = getattr(self, "_selected_row", None)
        if row is not None:
            self._render_detail(row)

    def on_session_details_resized(self, event):
        event.stop()
        self._refresh_selected_detail()

    def _render_detail(self, row):
        detail = Text(style="#e0e0e0")
        detail.append(row.get("title") or "Untitled", style="bold #d7a9ff")
        status = row.get("status", "idle")
        detail.append("\n" + status_glyph(status) + " " + tr(STATUS_LABELS.get(status, status)),
                      style=_STATUS_COLORS.get(status, "#77d8b0"))
        detail.append("\n\nWorkspace\n", style="#9aa3ad")
        detail.append(str(row.get("workspace") or "Unknown"), style="#e0e0e0")
        detail.append("\n\nUpdated\n", style="#9aa3ad")
        detail.append(str(row.get("age") or "Unknown"))
        if row.get("messages") is not None:
            detail.append("\n\nMessages\n", style="#9aa3ad")
            detail.append(str(row["messages"]))
        if row.get("context"):
            detail.append("\n\nContext (estimate)\n", style="#9aa3ad")
            detail.append(str(row["context"]) + (" of window" if row.get("context_percent") is not None else " tokens"),
                          style=_percent_color(row.get("context_percent")))

        if row.get("model"):
            from isycode.model_presentation import model_display_name
            detail.append("\n\nModel\n", style="#9aa3ad")
            detail.append(model_display_name(row["model"]), style="#77d8b0")
            from isycode.providers import PRESETS
            provider = row.get("provider") or ""
            detail.append(" · " + PRESETS.get(provider, {}).get("label", provider or "Unknown provider"), style="#d7a9ff")
        panel = self.query_one("#work-details", SessionDetails)
        panel.full_message = str(row.get("detail") or row.get("preview") or "")
        panel.full_message_loader = row.get("load_detail")
        width = max(3, panel.content_size.width)
        overhead = len(detail.wrap(self.app.console, width)) + 5
        budget = max(1, panel.content_size.height - overhead)
        detail.append("\n\nLast message\n", style="#9aa3ad")
        detail.append(quoted_preview(panel.full_message or "No message preview", self.app.console, width, budget))
        detail.append("\nEnter / Space / double-click: full message", style="#77d8b0")
        panel.update(detail)

    def on_button_pressed(self, event):
        if event.button.id and event.button.id.startswith("work-filter-"):
            event.stop()
            self._filter = event.button.id.removeprefix("work-filter-")
            self._paint_filter_active()
            self.show_rows(self._rows, heading=self._heading)

    def _paint_filter_active(self):
        active = getattr(self, "_filter", "all")
        for button_id, name in (
            ("work-filter-all", "all"),
            ("work-filter-generating", "generating"),
            ("work-filter-background", "background"),
            ("work-filter-waiting", "waiting"),
            ("work-filter-idle", "idle"),
        ):
            try:
                button = self.query_one(f"#{button_id}", Button)
            except Exception:
                continue
            if name == active:
                button.add_class("filter-on")
            else:
                button.remove_class("filter-on")
