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
