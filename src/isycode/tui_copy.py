"""Explicit content copying and exact logical-range extraction.

UI choices still execute through the application's ClipboardOwner path.
"""
from __future__ import annotations

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from rich.syntax import Syntax
from textual.containers import VerticalScroll
from textual.widgets import Static, TextArea
from isycode.localization import tr
from isycode.tui_dialog import Dialog, DialogAction
from isycode.tui_theme import CYAN, MUTED


def extract_range(text, selection):
    """Textual Content offsets refer to logical rows, with tabs expanded to 8 cells."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return ""

    def position(offset, *, end):
        if offset is None:
            return len(text) if end else 0
        y = max(0, offset.y)
        if y >= len(lines):
            return len(text)
        line = lines[y].rstrip("\r\n")
        expanded = 0
        for index, char in enumerate(line):
            size = 8 - expanded % 8 if char == "\t" else cell_len(char)
            if offset.x < expanded + size:
                return sum(map(len, lines[:y])) + index + (1 if end and offset.x > expanded else 0)
            expanded += size
        return sum(map(len, lines[:y])) + len(line)

    start = position(selection.start, end=False)
    end = position(selection.end, end=True)
    return text[start:end]


def exact_selected_text(screen):
    """Keep selected newline/whitespace; Screen.get_selected_text strips trailing LF."""
    parts = []
    for widget, selection in screen.selections.items():
        if widget.is_attached and (result := widget.get_selection(selection)) is not None:
            parts.append(result[0])
    return "\n".join(parts)


_BOX_UNICODE = {"h": "─", "v": "│", "tl": "┌", "tm": "┬", "tr": "┐",
                "ml": "├", "mm": "┼", "mr": "┤", "bl": "└", "bm": "┴", "br": "┘"}
_BOX_ASCII = {"h": "-", "v": "|", "tl": "+", "tm": "+", "tr": "+",
              "ml": "+", "mm": "+", "mr": "+", "bl": "+", "bm": "+", "br": "+"}
_WRAP_CONSOLE = None
_MIN_CELL = 6


def _wrap_console():
    global _WRAP_CONSOLE
    if _WRAP_CONSOLE is None:
        from rich.console import Console
        _WRAP_CONSOLE = Console(width=10_000, color_system=None, legacy_windows=False,
                                force_terminal=False, no_color=True)
    return _WRAP_CONSOLE


def _append_inline(target: Text, token, heading: bool) -> None:
    styles = [f"bold {CYAN}" if heading else ""]
    link_href = None
    for child in token.children or []:
        if child.type in {"strong_open", "em_open", "s_open"}:
            styles.append({"strong_open": "bold", "em_open": "italic", "s_open": "strike"}[child.type])
        elif child.type in {"strong_close", "em_close", "s_close"}:
            if len(styles) > 1:
                styles.pop()
        elif child.type == "link_open":
            link_href = child.attrGet("href")
        elif child.type == "link_close":
            link_href = None
        elif child.type in {"softbreak", "hardbreak"}:
            target.append("\n")
        elif child.type == "image":
            target.append(child.content)
        elif child.type in {"text", "code_inline"}:
            inline_styles = [style for style in styles if style]
            if child.type == "code_inline":
                inline_styles.append(CYAN)
            if link_href:
                real_href = (
                    "file://" + link_href[10:]
                    if link_href.lower().startswith("isyfile://")
                    else link_href
                )
                base = Style.parse(" ".join(inline_styles)) if inline_styles else Style.null()
                link_style = base + Style(
                    color=CYAN,
                    underline=True,
                    link=real_href,
                    meta={"isy_link": real_href},
                )
                target.append(child.content, style=link_style)
            else:
                target.append(child.content, style=" ".join(inline_styles))


def _column_widths(natural: list[int], room: int) -> list[int]:
    """Fit columns into ``room`` cells: narrow columns keep their width, wide ones share the rest."""
    if sum(natural) <= room:
        return list(natural)
    widths = [0] * len(natural)
    pending = sorted(range(len(natural)), key=lambda index: natural[index])
    left = room
    while pending:
        share = left // len(pending)
        index = pending[0]
        if natural[index] <= share:
            widths[index] = natural[index]
            left -= natural[index]
            pending.pop(0)
            continue
        for position, index in enumerate(pending):
            widths[index] = share + (1 if position < left - share * len(pending) else 0)
        break
    return widths


def _table_as_records(rows, header) -> Text:
    """Too narrow for a box: one ``header: value`` line per cell, rows split by a blank line."""
    result = Text()
    names = header or []
    for row_index, (is_header, cells, _aligns) in enumerate(rows):
        if is_header:
            continue
        for index, cell in enumerate(cells):
            if index < len(names) and names[index].plain.strip():
                name = names[index].copy()
                name.stylize("bold")
                result.append_text(name)
                result.append(": ")
            result.append_text(cell)
            result.append("\n")
        if row_index < len(rows) - 1:
            result.append("\n")
    return result


def render_table_box(rows, width: int | None = None, *, ascii: bool = False) -> Text:
    """Draw parsed Markdown table rows as an aligned box no wider than ``width`` cells.

    ``rows`` holds ``(is_header, [Text], [align])``. Widths come from terminal
    cells (CJK and emoji count as 2); a cell too long for its column wraps on
    words inside the column rather than breaking the border.
    """
    rows = [row for row in rows if row[1]]
    if not rows:
        return Text()
    columns = max(len(cells) for _header, cells, _aligns in rows)
    rows = [(is_header, cells + [Text()] * (columns - len(cells)), aligns + [None] * (columns - len(aligns)))
            for is_header, cells, aligns in rows]
    header = next((cells for is_header, cells, _aligns in rows if is_header), None)
    natural = [max(1, *(cell.cell_len for _h, cells, _a in rows for cell in [cells[index]]))
               for index in range(columns)]
    overhead = 3 * columns + 1
    room = None if not width else width - overhead
    if room is not None and room < min(sum(natural), _MIN_CELL * columns):
        return _table_as_records(rows, header)
    widths = natural if room is None else _column_widths(natural, room)
    box = _BOX_ASCII if ascii else _BOX_UNICODE
    border = MUTED

    def rule(left, middle, right):
        line = Text(left + middle.join(box["h"] * (size + 2) for size in widths) + right, style=border)
        line.append("\n")
        return line

    console = _wrap_console()
    result = Text()
    result.append_text(rule(box["tl"], box["tm"], box["tr"]))
    for row_index, (is_header, cells, aligns) in enumerate(rows):
        wrapped = []
        for index, cell in enumerate(cells):
            text = cell.copy()
            if is_header:
                text.stylize("bold")
            lines = text.wrap(console, widths[index], overflow="fold", no_wrap=False) if text.plain else [Text()]
            lines = [line for line in lines if line.plain.strip()]
            wrapped.append(lines or [Text()])
        for line_index in range(max(len(lines) for lines in wrapped)):
            result.append(box["v"], style=border)
            for index, lines in enumerate(wrapped):
                piece = lines[line_index].copy() if line_index < len(lines) else Text()
                piece.rstrip()
                piece.align(aligns[index] or "left", widths[index])
                result.append(" ")
                result.append_text(piece)
                result.append(" ")
                result.append(box["v"], style=border)
            result.append("\n")
        if is_header and row_index < len(rows) - 1:
            result.append_text(rule(box["ml"], box["mm"], box["mr"]))
    result.append_text(rule(box["bl"], box["bm"], box["br"]))
    return result


def _cell_align(token) -> str | None:
    style = token.attrGet("style") or ""
    for align in ("left", "center", "right"):
        if f"text-align:{align}" in style.replace(" ", ""):
            return align
    return None


def selectable_markdown(markdown, width: int | None = None):
    """Render logical styled lines, allowing native selection before soft wrapping.

    Rich's pre-wrapped Markdown segments have no Textual source offsets. Keep
    formatting as Text, code whitespace intact, and let Textual wrap it once.
    Tables and rules are the exception: they need the content ``width`` to be
    drawn as aligned boxes that never soft-wrap through their borders.
    """
    from isycode.tui_theme import ascii_only

    ascii = ascii_only()
    result = Text()
    list_depth = 0
    ordered = []
    heading = False
    table_rows = None
    row = None
    cell = None
    for token in markdown.parsed:
        kind = token.type
        if kind in {"bullet_list_open", "ordered_list_open"}:
            list_depth += 1
            ordered.append(int(token.attrGet("start") or 1) if kind == "ordered_list_open" else None)
        elif kind in {"bullet_list_close", "ordered_list_close"}:
            list_depth = max(0, list_depth - 1)
            ordered.pop()
            if not list_depth:
                result.append("\n")
        elif kind == "list_item_open":
            count = ordered[-1] if ordered else None
            prefix = f"{count}. " if count is not None else "• "
            result.append("  " * max(0, list_depth - 1) + prefix, style=CYAN)
            if count is not None:
                ordered[-1] += 1
        elif kind == "heading_open":
            heading = True
        elif kind == "heading_close":
            heading = False
            result.append("\n\n")
        elif kind == "inline":
            _append_inline(cell if cell is not None else result, token, heading)
        elif kind == "paragraph_close":
            result.append("\n" if list_depth else "\n\n")
        elif kind in {"fence", "code_block"}:
            # No Syntax padding/line numbers, rstrip or tab normalization.
            highlighted = Syntax(token.content, (token.info.split() or ["text"])[0],
                                 theme="monokai", background_color="default").highlight(token.content)
            result.append_text(highlighted if highlighted.plain == token.content else Text(token.content))
            result.append("\n")
        elif kind == "blockquote_open":
            result.append("› ", style=MUTED)
        elif kind == "hr":
            size = max(8, (width or 0) - 1) if width else 8
            result.append(("-" if ascii else "─") * size + "\n", style=MUTED)
        elif kind == "table_open":
            table_rows = []
        elif kind == "tr_open" and table_rows is not None:
            row = (False, [], [])
        elif kind in {"th_open", "td_open"} and row is not None:
            if kind == "th_open":
                row = (True, row[1], row[2])
            cell = Text()
            row[2].append(_cell_align(token))
        elif kind in {"th_close", "td_close"} and row is not None:
            row[1].append(cell if cell is not None else Text())
            cell = None
        elif kind == "tr_close" and row is not None:
            table_rows.append(row)
            row = None
        elif kind == "table_close" and table_rows is not None:
            result.append_text(render_table_box(table_rows, width, ascii=ascii))
            result.append("\n")
            table_rows = None
    return result


class CopyMenuScreen(Dialog):
    """Selection or whole box, never a silent fallback."""

    dialog_title = "Copy text"
    dialog_width = "narrow"

    def __init__(self, selected: str, whole: str):
        super().__init__()
        self.selected = selected
        self.whole = whole
        self.dialog_default_action = "copy-selection" if selected else "copy-whole"

    def dialog_note(self) -> str:
        return tr("Only the selected characters are copied. Whole-box copy is a separate choice.")

    def compose_body(self):
        with VerticalScroll(id="copy-preview", classes="isy-dialog-preview"):
            yield Static(Text(self.selected) if self.selected else tr("No text selected."),
                         markup=False, classes="isy-dialog-copy")

    def dialog_actions(self):
        return (
            DialogAction("copy-selection", tr("Copy selection"), "primary",
                         focused=bool(self.selected), disabled=not self.selected),
            DialogAction("copy-whole", tr("Copy whole"),
                         focused=not self.selected, disabled=not self.whole),
            DialogAction("copy-cancel", tr("Cancel")),
        )

    def dismiss_action(self, action_id: str) -> None:
        if action_id == "copy-selection" and self.selected:
            self.dismiss((self.selected, "selection"))
        elif action_id == "copy-whole" and self.whole:
            self.dismiss((self.whole, "content_box"))
        else:
            self.dismiss(None)


def _owned_selections(widget, selections):
    """Keep only ranges owned by this text widget or one of its descendants."""
    return {
        item: selection
        for item, selection in selections.items()
        if item is widget or widget in item.ancestors
    }


def remember_copy_selection(widget):
    """Capture before Textual clears a marked range on a stationary mouse-up.

    Keep it only for the same widget's double-click sequence, never as a
    fallback for a later zero-selection copy. The sequence is counted in
    presses, not seconds: a loaded machine can take longer than any grace
    period between the two clicks, and Textual already decides from the
    input times what counts as a double-click. The press that captured the
    range and the next one keep it; any press after that drops it.
    """
    screen = widget.screen
    if screen.selections:
        widget._copy_selection_snapshot = (0, _owned_selections(widget, screen.selections))
        return
    presses, kept = getattr(widget, "_copy_selection_snapshot", (2, {}))
    widget._copy_selection_snapshot = (1, kept) if presses == 0 and kept else (2, {})


def open_copy_menu(widget, whole: str, selected: str | None = None, *, restore=None,
                   remembered: bool = True):
    """``remembered=False`` (the keyboard) never uses a range kept from a double-click."""
    app = widget.app
    screen = widget.screen
    selections = _owned_selections(widget, screen.selections)
    presses, kept = getattr(widget, "_copy_selection_snapshot", (2, {}))
    if not selections and remembered and presses <= 1:
        selections = _owned_selections(widget, kept)
    widget._copy_selection_snapshot = (2, {})
    focused = screen.focused
    if selected is None:
        selected = "\n".join(result[0] for item, selection in selections.items()
                             if item.is_attached and (result := item.get_selection(selection)) is not None)

    def finish(choice):
        if screen.is_mounted:
            screen.selections = selections
            if focused is not None and focused.is_attached:
                focused.focus(scroll_visible=False)
            if restore is not None and widget.is_attached:
                restore()
        if choice:
            app.run_worker(app._request_clipboard_copy(*choice), group="clipboard-user")

    app.push_screen(CopyMenuScreen(selected, whole), finish)


class CopyTextArea(TextArea):
    """Readonly previews use the same explicit copy menu; editable fields keep typing."""

    # The press that starts a double-click clears the marked range before the
    # second click arrives. Keep the range by click sequence, not by clock: a
    # loaded machine can take longer than any grace period between the events,
    # while Textual already decides from the input times what counts as a chain.
    async def _on_mouse_down(self, event):
        if self.read_only:
            self._copy_area_pressed = (self.selection, self.selected_text) if self.selected_text else None
        await super()._on_mouse_down(event)

    async def _on_click(self, event):
        if not self.read_only:
            await super()._on_click(event)
            return
        if event.chain == 1:
            # Only the press that began this chain may carry a range forward.
            self._copy_area_snapshot = getattr(self, "_copy_area_pressed", None)
        if event.chain != 2:
            await super()._on_click(event)
            return
        event.prevent_default()
        event.stop()
        snapshot = getattr(self, "_copy_area_snapshot", None)
        selection, selected = snapshot or (self.selection, self.selected_text)
        self._copy_area_snapshot = None
        def restore():
            self.selection = selection
        open_copy_menu(self, self.text, selected, restore=restore)
