"""Same-window conversation board. It lists chats; it does not launch agents."""
from datetime import datetime, timezone
from rich.cells import cell_len
from rich.text import Text
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.binding import Binding
from textual.widgets import Button, OptionList, Static
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


def preview_line(text: str | None) -> str:
    if not isinstance(text, str):
        return ""
    clean = " ".join(text.replace("\x1b", "").split())
    return clean[:72]


class SessionOptionList(OptionList):
    """First click previews; a subsequent click on that row opens it."""
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
        self.focus()
        self.highlighted = index
        if self._preview_click_id == option.id:
            self._preview_click_id = None
            self.action_select()
        else:
            self._preview_click_id = option.id

    def action_cursor_down(self):
        self._preview_click_id = None
        super().action_cursor_down()

    def action_cursor_up(self):
        self._preview_click_id = None
        super().action_cursor_up()


class SessionMessageScreen(ModalScreen):
    CSS = """
    SessionMessageScreen { align: center middle; background: #000000 58%; }
    #session-message-card { width: 90%; max-width: 110; height: 80%; padding: 1 2; border: round #514d5a; background: #242529; }
    #session-message-scroll { height: 1fr; margin: 1 0; }
    #session-message-content { height: auto; }
    """
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, message):
        super().__init__()
        self.message = message

    def compose(self):
        with Vertical(id="session-message-card"):
            yield Static(Text("Session · full last message", style="bold #d7a9ff"))
            with VerticalScroll(id="session-message-scroll"):
                yield Static(Text(self.message), id="session-message-content")
            yield Button("Close · Esc", id="session-message-close")

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

    def on_click(self, event):
        self.focus()

    def action_expand_message(self):
        message = getattr(self, "full_message", "")
        if message:
            self.app.push_screen(SessionMessageScreen(message))


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
    #work-conversations { height: 1fr; border: none; background: transparent; padding: 0; }
    #work-conversations > .option-list--option-highlighted { background: #2a2b30; color: #f4f1ea; }
    #work-presence { height: 1; color: #6d7580; }
    """

    def compose(self):
        yield Static("", id="work-heading", markup=False)
        with Horizontal():
            yield Button("+ New conversation", id="work-new")
            yield Button("Refresh", id="work-refresh")
            yield Button("Bridge presence…", id="work-bridge")
            yield Button("Hide", id="work-hide")
        with Horizontal(id="work-filters"):
            yield Button("All", id="work-filter-all")
            yield Button("Working", id="work-filter-generating")
            yield Button("Needs input", id="work-filter-waiting")
            yield Button("Idle", id="work-filter-idle")
        with Horizontal(id="work-body"):
            yield SessionOptionList(id="work-conversations")
            yield SessionDetails("Select a conversation to inspect it.", id="work-details", markup=False)
        yield Static("Bridge presence off", id="work-presence", markup=False)

    def on_resize(self):
        if not self.is_mounted:
            return
        self.query_one("#work-details").display = self.content_size.width >= 85
        if getattr(self, "_selected_row", None):
            self.call_after_refresh(self._render_detail, self._selected_row)
        compact = self.content_size.width < 62
        self.query_one("#work-new", Button).label = "+ New" if compact else "+ New conversation"
        self.query_one("#work-bridge", Button).label = "Bridge" if compact else "Bridge presence…"

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
        grouped: dict[str, list] = {"generating": [], "waiting": [], "idle": []}
        for row in rows:
            grouped.get(row.get("status"), grouped["idle"]).append(row)
        titles = (("generating", "Working"), ("waiting", "Waiting"), ("idle", "Idle"))
        for key, title in titles:
            items = grouped[key]
            if not items:
                continue
            listing.add_option(Option(Text(f"{title}  {len(items)}", style="bold #9aa3ad"),
                                      id=f"section-{key}", disabled=True))
            for row in items:
                age = row.get("age") or ""
                line = Text()
                line.append("◇ ", style="#8fbc8f")
                line.append(row.get("title") or "Untitled", style="bold #f4f1ea" if row.get("current") else "")
                line.append(f"  ·  {row.get('workspace') or ''}", style="#9aa3ad")
                if age:
                    line.append(f"    {age}", style="#6d7580")
                preview = row.get("preview") or ""

                listing.add_option(Option(line, id=row["id"]))
        if highlight is not None and listing.option_count:
            listing.highlighted = min(highlight, listing.option_count - 1)

    def on_option_list_option_highlighted(self, event):
        if event.option_list.id != "work-conversations":
            return
        row = next((item for item in getattr(self, "_rows", []) if item["id"] == event.option.id), None)
        if row is None:
            return
        self._selected_row = row
        self._render_detail(row)

    def _render_detail(self, row):
        detail = Text(style="#e0e0e0")
        detail.append(row.get("title") or "Untitled", style="bold #d7a9ff")
        status = row.get("status", "idle")
        detail.append("\n" + {"generating": "Working", "waiting": "Needs input", "idle": "Idle"}.get(status, status), style="#77d8b0")
        detail.append("\n\nWorkspace\n", style="#9aa3ad")
        detail.append(str(row.get("workspace") or "Unknown"), style="#e0e0e0")
        detail.append("\n\nUpdated\n", style="#9aa3ad")
        detail.append(str(row.get("age") or "Unknown"))

        if row.get("model"):
            from isycode.model_presentation import model_display_name
            detail.append("\n\nModel\n", style="#9aa3ad")
            detail.append(model_display_name(row["model"]), style="#77d8b0")
            from isycode.providers import PRESETS
            provider = row.get("provider") or ""
            detail.append(" · " + PRESETS.get(provider, {}).get("label", provider or "Unknown provider"), style="#d7a9ff")
        panel = self.query_one("#work-details", SessionDetails)
        panel.full_message = str(row.get("detail") or row.get("preview") or "")
        width = max(3, panel.content_size.width)
        overhead = len(detail.wrap(self.app.console, width)) + 5
        budget = max(1, panel.content_size.height - overhead)
        detail.append("\n\nLast message\n", style="#9aa3ad")
        detail.append(quoted_preview(panel.full_message or "No message preview", self.app.console, width, budget))
        detail.append("\nEnter / Space: full message", style="#77d8b0")
        panel.update(detail)

    def on_button_pressed(self, event):
        if event.button.id and event.button.id.startswith("work-filter-"):
            event.stop()
            self._filter = event.button.id.removeprefix("work-filter-")
            self.show_rows(self._rows, heading=self._heading)
