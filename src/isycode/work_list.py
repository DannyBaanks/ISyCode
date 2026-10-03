"""Same-window conversation board. It lists chats; it does not launch agents."""
from datetime import datetime, timezone
from rich.cells import cell_len
from rich.text import Text
from textual.containers import Vertical, Horizontal
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


class WorkList(Vertical):
    DEFAULT_CSS = """
    WorkList { height: 1fr; display: none; padding: 1 2 0 2; background: #1e1f22; }
    WorkList Horizontal { height: 1; }
    WorkList Button { height: 1; min-height: 1; border: none; background: transparent; color: #8fbc8f; padding: 0 1; }
    WorkList Button:hover, WorkList Button:focus { background: transparent; color: #f4f1ea; text-style: bold; }
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
        yield OptionList(id="work-conversations")
        yield Static("Bridge presence off", id="work-presence", markup=False)

    def show_rows(self, rows, *, heading: str = ""):
        self.query_one("#work-heading", Static).update(heading)
        listing = self.query_one("#work-conversations", OptionList)
        highlight = listing.highlighted
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
                if preview:
                    line.append(f"\n   {preview}", style="#6d7580")
                listing.add_option(Option(line, id=row["id"]))
        if highlight is not None and listing.option_count:
            listing.highlighted = min(highlight, listing.option_count - 1)
