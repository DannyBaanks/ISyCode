"""Semantic terminal-bell rhythms, without subprocesses or downloaded audio."""
PATTERNS = {
    "done": (0.0,),
    "approval": (0.0, 0.22),
    "question": (0.0, 0.16, 0.48),
    "warning": (0.0, 0.4),
    "error": (0.0, 0.12, 0.24),
    "info": (0.0,),
}
