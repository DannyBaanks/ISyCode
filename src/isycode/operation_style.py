"""Stable operation colors, independent from execution status."""
COLORS = {
    "workspace_list": "#8fb8e8", "workspace_read": "#77d8b0",
    "workspace_search": "#e9c778", "workspace_grep": "#e9c778",
    "workspace_write": "#c7a5e8", "workspace_edit": "#c7a5e8",
    "workspace_run": "#f0a878", "workspace_delete": "#f08080",
    "workspace_move": "#e8a5c2", "delegate_task": "#74cbd3",
    "update_tasks": "#c7b8d4", "git_status": "#8fb8e8", "git_diff": "#8fb8e8",
    "webfetch": "#74cbd3",
    "git_commit": "#8fb8e8",
}


def operation_color(label: str) -> str | None:
    return next((color for name, color in COLORS.items() if name in label), None)


ICONS = {
    "workspace_list": "📂", "workspace_read": "📄",
    "workspace_search": "🔍", "workspace_grep": "🔍",
    "workspace_write": "✏️", "workspace_edit": "✏️",
    "workspace_run": "⚙️", "workspace_delete": "🗑",
    "workspace_move": "📦", "delegate_task": "🤖",
    "update_tasks": "🗒", "git_status": "⑂", "git_diff": "⑂",
    "git_commit": "⑂", "webfetch": "🌐", "update_session_title": "🏷",
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
    return next((icon for name, icon in table.items() if name in label), "•" if not ascii_only else "[·]")
