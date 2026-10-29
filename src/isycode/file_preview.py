from pathlib import Path
from textual.app import ComposeResult
from isycode.localization import tr
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea
from isycode.tui_copy import CopyTextArea
from isycode.tui_screens_approval import DECISION_CSS


def guess_syntax_language(path: str | Path | None, code: str | None = None) -> str | None:
    """Map file extension or contents to Textual's supported tree-sitter syntax languages."""
    if path:
        p = Path(path)
        name = p.name.lower()
        ext = p.suffix.lower()

        name_mapping = {
            "dockerfile": "bash",
            "containerfile": "bash",
            "procfile": "bash",
            ".gitattributes": "bash",
            ".gitignore": "bash",
            ".gitmodules": "bash",
            ".gitconfig": "bash",
            ".dockerignore": "bash",
            "compose.yaml": "yaml",
            "compose.yml": "yaml",
            "cargo.lock": "toml",
            "poetry.lock": "toml",
        }
        if name in name_mapping:
            return name_mapping[name]
        if (name.startswith(".env") or name.startswith("dockerfile")
                or name.endswith(".dockerfile") or name.startswith("containerfile")
                or name.endswith(".containerfile")):
            return "bash"

        ext_mapping = {
            ".py": "python",
            ".pyi": "python",
            ".pyw": "python",
            ".json": "json",
            ".jsonl": "json",
            ".geojson": "json",
            ".topojson": "json",
            ".md": "markdown",
            ".markdown": "markdown",
            ".mdown": "markdown",
            ".mkdn": "markdown",
            ".sh": "bash",
            ".bash": "bash",
            ".zsh": "bash",
            ".ksh": "bash",
            ".csh": "bash",
            ".fish": "bash",
            ".ps1": "bash",
            ".gitattributes": "bash",
            ".gitignore": "bash",
            ".gitmodules": "bash",
            ".dockerignore": "bash",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".clang-format": "yaml",
            ".clang-tidy": "yaml",
            ".toml": "toml",
            ".js": "javascript",
            ".jsx": "javascript",
            ".mjs": "javascript",
            ".cjs": "javascript",
            ".ts": "javascript",
            ".tsx": "javascript",
            ".html": "html",
            ".htm": "html",
            ".xhtml": "html",
            ".svg": "xml",
            ".xml": "xml",
            ".plist": "xml",
            ".xaml": "xml",
            ".xib": "xml",
            ".storyboard": "xml",
            ".csproj": "xml",
            ".props": "xml",
            ".targets": "xml",
            ".css": "css",
            ".tcss": "css",
            ".scss": "css",
            ".sass": "css",
            ".less": "css",
            ".rs": "rust",
            ".go": "go",
            ".sql": "sql",
            ".java": "java",
            ".c": "java",
            ".h": "java",
            ".cpp": "java",
            ".hpp": "java",
            ".cc": "java",
            ".cxx": "java",
            ".cs": "java",
            ".kt": "java",
            ".kts": "java",
            ".scala": "java",
            ".regex": "regex",
        }
        if ext in ext_mapping:
            return ext_mapping[ext]

    if code:
        stripped = code.strip()
        first_line = stripped.split("\n", 1)[0].lower()
        if first_line.startswith("#!"):
            if any(s in first_line for s in ("python", "py")):
                return "python"
            if any(s in first_line for s in ("node", "deno", "bun", "js")):
                return "javascript"
            if any(s in first_line for s in ("bash", "sh", "zsh", "dash")):
                return "bash"
        if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
            return "json"
        if stripped.startswith("<?xml") or stripped.startswith("<!doctype html") or stripped.startswith("<html"):
            return "html"
        if stripped.startswith("---") and "\n" in stripped:
            return "yaml"

    return None


class FilePreviewScreen(ModalScreen[None]):
    CSS = DECISION_CSS + '''
    FilePreviewScreen { align: center middle; background: #000000 58%; }
    #preview-card { width: 110; max-width: 96%; height: 90%; }
    #preview-heading { height: auto; max-height: 4; }
    #preview-text { height: 1fr; background: #000000; border: none; }
    #preview-text .text-area--gutter { background: #000000; color: #718291; }
    #preview-text .text-area--selection { background: #002c36; }
    '''
    BINDINGS = [Binding('escape', 'close', 'Close')]

    def __init__(self, path: str | Path, text: str):
        super().__init__()
        self.path = path
        self.text = text

    def compose(self) -> ComposeResult:
        lang = guess_syntax_language(self.path, self.text)
        clean_path = str(self.path).removeprefix("file://")
        with Vertical(id='preview-card', classes='isy-dialog'):
            yield Static(clean_path, id='preview-heading', classes='isy-dialog-title', markup=False)
            yield CopyTextArea(
                self.text,
                language=lang,
                theme="monokai",
                read_only=True,
                id='preview-text',
                show_line_numbers=True,
            )
            with Horizontal(id='preview-actions', classes='isy-dialog-actions'):
                yield Button(tr('Copy path'), id='preview-copy-path')
                yield Button(tr('Copy selection'), id='preview-copy', disabled=True)
                yield Button(tr('Copy whole file'), id='preview-copy-whole')
                yield Button(tr('Close'), id='preview-close')
            yield Static(tr('Read-only · select with mouse or Ctrl+A; Ctrl+C copies'),
                         classes='isy-dialog-hint', markup=False)

    def on_text_area_selection_changed(self, event):
        self.query_one('#preview-copy', Button).disabled = not event.text_area.selected_text

    def on_mount(self):
        self.query_one(TextArea).focus()

    async def on_button_pressed(self, event):
        event.stop()
        clean_path = str(self.path).removeprefix("file://")
        if event.button.id == 'preview-copy-path':
            self.app.run_worker(self.app._request_clipboard_copy(clean_path, 'file_path'), group='clipboard-user')
        elif event.button.id == 'preview-copy':
            editor = self.query_one(TextArea)
            if editor.selected_text:
                self.app.run_worker(self.app._request_clipboard_copy(editor.selected_text, 'selection'), group='clipboard-user')
        elif event.button.id == 'preview-copy-whole':
            self.app.run_worker(self.app._request_clipboard_copy(self.text, 'content_box'), group='clipboard-user')
        else:
            self.dismiss(None)

    def action_close(self):
        self.dismiss(None)
