"""Stable operation colors, independent from execution status."""
from isycode.tui_theme import TEXT, MUTED

# An operation's identity is distinct from permission and outcome colors.
COLORS = {
    "workspace_list": TEXT, "workspace_read": TEXT,
    "workspace_search": TEXT, "workspace_grep": TEXT,
    "workspace_write": TEXT, "workspace_edit": TEXT,
    "workspace_run": TEXT, "workspace_delete": TEXT,
    "workspace_move": TEXT, "delegate_task": TEXT,
    "update_tasks": MUTED, "git_status": TEXT, "git_diff": TEXT,
    "webfetch": TEXT, "git_commit": TEXT,
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
