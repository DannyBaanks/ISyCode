"""Stable operation colors, independent from execution status."""
from isycode.tui_theme import MUTED, CYAN, GREEN, YELLOW, RED

# An operation's identity is distinct from permission and outcome colors.
COLORS = {
    "workspace_list": CYAN, "workspace_read": CYAN,
    "workspace_search": CYAN, "workspace_grep": CYAN,
    "workspace_write": GREEN, "workspace_edit": GREEN,
    "workspace_run": YELLOW, "workspace_delete": RED,
    "workspace_move": "#c792ea", "delegate_task": "#c792ea",
    "update_tasks": MUTED, "git_status": "#82aaff", "git_diff": "#82aaff",
    "webfetch": CYAN, "git_commit": "#82aaff",
}


def operation_color(label: str) -> str | None:
    return next((color for name, color in COLORS.items() if name in label), None)


ICONS = {
    "workspace_list": "▸", "workspace_read": "▤",
    "workspace_search": "⌕", "workspace_grep": "⌕",
    "workspace_write": "✎", "workspace_edit": "✎",
    "workspace_run": "›", "workspace_delete": "×",
    "workspace_move": "↔", "delegate_task": "◇",
    "update_tasks": "▣", "git_status": "↳", "git_diff": "↳",
    "git_commit": "↳", "webfetch": "↔", "update_session_title": "▤",
}

ASCII_TAGS = {
    "workspace_list": "[ls]", "workspace_read": "[rd]",
    "workspace_search": "[sr]", "workspace_grep": "[gr]",
    "workspace_write": "[wr]", "workspace_edit": "[ed]",
    "workspace_run": "[$]", "workspace_delete": "[rm]",
    "workspace_move": "[mv]", "delegate_task": "[ag]",
    "update_tasks": "[tk]", "git_status": "[gs]", "git_diff": "[gd]",
    "git_commit": "[gc]", "webfetch": "[web]", "update_session_title": "[ti]",
}


def operation_icon(label: str, *, ascii_only: bool = False) -> str:
    """Stable per-operation icon; ASCII tag in ASCII-only mode."""
    table = ASCII_TAGS if ascii_only else ICONS
    return next((icon for name, icon in table.items() if name in label), "◇" if not ascii_only else "[op]")
