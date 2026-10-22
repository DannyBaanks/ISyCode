"""Explicit content copying and exact logical-range extraction.

UI choices still execute through the application's ClipboardOwner path.
"""
from __future__ import annotations

from time import monotonic
from rich.cells import cell_len
from rich.text import Text
from rich.syntax import Syntax
from textual.containers import VerticalScroll
from textual.widgets import Static, TextArea
from isycode.localization import tr
from isycode.tui_dialog import Dialog, DialogAction


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
        cells = 0
        for index, char in enumerate(line):
            size = 8 - cells % 8 if char == "\t" else 1
            if offset.x < expanded + size:
                return sum(map(len, lines[:y])) + index + (1 if end and offset.x > expanded else 0)
            expanded += size
            cells += size if char == "\t" else cell_len(char)
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


def selectable_markdown(markdown):
    """Render logical styled lines, allowing native selection before soft wrapping.

    Rich's pre-wrapped Markdown segments have no Textual source offsets. Keep
    formatting as Text, code whitespace intact, and let Textual wrap it once.
    """
    result = Text()
    list_depth = 0
    ordered = []
    heading = False
    in_table = False
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
            result.append("  " * max(0, list_depth - 1) + prefix)
            if count is not None:
                ordered[-1] += 1
        elif kind == "heading_open":
            heading = True
        elif kind == "heading_close":
            heading = False
            result.append("\n\n")
        elif kind == "inline":
            styles = ["bold" if heading else ""]
            for child in token.children or []:
                if child.type in {"strong_open", "em_open", "s_open"}:
                    styles.append({"strong_open": "bold", "em_open": "italic", "s_open": "strike"}[child.type])
                elif child.type in {"strong_close", "em_close", "s_close"}:
                    if len(styles) > 1:
                        styles.pop()
                elif child.type in {"softbreak", "hardbreak"}:
                    result.append("\n")
                elif child.type == "image":
                    result.append(child.content)
                elif child.type in {"text", "code_inline"}:
                    result.append(child.content, style=" ".join(style for style in styles if style))
        elif kind == "paragraph_close":
            result.append("\n" if list_depth else "\n\n")
        elif kind in {"fence", "code_block"}:
            # No Syntax padding/line numbers, rstrip or tab normalization.
            highlighted = Syntax(token.content, (token.info.split() or ["text"])[0],
                                 theme="monokai", background_color="default").highlight(token.content)
            result.append_text(highlighted if highlighted.plain == token.content else Text(token.content))
            result.append("\n")
        elif kind == "blockquote_open":
            result.append("› ")
        elif kind == "hr":
            result.append("────────\n")
        elif kind == "table_open":
            in_table = True
        elif kind in {"td_close", "th_close"} and in_table:
            result.append("  |  ")
        elif kind == "tr_close":
            result.append("\n")
        elif kind == "table_close":
            in_table = False
            result.append("\n")
    return result


class CopyMenuScreen(Dialog):
    """Selection or whole box, never a silent fallback."""

    dialog_title = "Copy text"
    dialog_width = "narrow"
    dialog_default_action = "copy-selection"

    def __init__(self, selected: str, whole: str):
        super().__init__()
        self.selected = selected
        self.whole = whole

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
            DialogAction("copy-whole", tr("Copy whole box"),
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


def remember_copy_selection(widget):
    """Capture before Textual clears a marked range on a stationary mouse-up.

    Keep it only for the same widget's double-click sequence, never as a
    fallback for a later zero-selection copy.
    """
    now = monotonic()
    screen = widget.screen
    if screen.selections:
        widget._copy_selection_snapshot = (now, dict(screen.selections))
    elif now - getattr(widget, "_copy_selection_snapshot", (0, {}))[0] > 0.6:
        widget._copy_selection_snapshot = (0, {})


def open_copy_menu(widget, whole: str, selected: str | None = None, *, restore=None):
    app = widget.app
    screen = widget.screen
    selections = dict(screen.selections)
    timestamp, remembered = getattr(widget, "_copy_selection_snapshot", (0, {}))
    if not selections and monotonic() - timestamp <= 0.6:
        selections = remembered
    widget._copy_selection_snapshot = (0, {})
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

    async def _on_mouse_down(self, event):
        if self.read_only:
            now = monotonic()
            if self.selected_text:
                self._copy_area_snapshot = (now, self.selection, self.selected_text)
            elif now - getattr(self, "_copy_area_snapshot", (0, None, ""))[0] > 0.6:
                self._copy_area_snapshot = (0, None, "")
        await super()._on_mouse_down(event)

    async def _on_click(self, event):
        if self.read_only and event.chain == 2:
            event.prevent_default()
            event.stop()
            timestamp, selection, selected = getattr(self, "_copy_area_snapshot", (0, None, ""))
            if monotonic() - timestamp > 0.6:
                selection, selected = self.selection, self.selected_text
            def restore():
                if selection is not None:
                    self.selection = selection
            self._copy_area_snapshot = (0, None, "")
            open_copy_menu(self, self.text, selected, restore=restore)
        else:
            await super()._on_click(event)
