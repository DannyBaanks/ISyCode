"""Shared multi-harness memory (`isymem`) integration for ISyCode sessions.

Discovers the user's shared ``isymem`` bank (``ISYMEM_DIR``, workspace
``docs/agent/memory``, or ``~/.config/isyco-memory/memory``), extracts compact L0
index + matching project hub lines for prompt continuity, and runs ``isymem`` CLI
subcommands safely for ``/isymem``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

MAX_INDEX_CHARS = 2200
MAX_HUB_CHARS = 1400
MAX_TOTAL_CHARS = 3800
ISYMEM_TOOL_NAME = "isymem"
ISYMEM_READ_ACTIONS = frozenset({"projects", "list", "card", "recall", "search", "show", "history", "doctor"})
ISYMEM_WRITE_ACTIONS = frozenset({"add", "close", "save"})
ISYMEM_TOOL = {
    "type": "function",
    "function": {
        "name": ISYMEM_TOOL_NAME,
        "description": (
            "Primary shared multi-harness memory tool (`isymem`). Query projects, rules, "
            "open fails/todos, recall by topic, show a slug, or record new facts/todos/rules."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["projects", "list", "card", "recall", "search", "show", "add", "close", "save"],
                    "description": "Operation to run on the shared isymem bank.",
                },
                "target": {
                    "type": "string",
                    "description": "Project name (card/add), query text (recall/search), slug (show/save), or anchor id (close).",
                },
                "kind": {
                    "type": "string",
                    "enum": ["fail", "todo", "rule", "state", "idea", "project", "feedback", "user", "reference"],
                    "description": "Anchor kind for add (fail/todo/rule/state/idea) or memory type for save.",
                },
                "text": {
                    "type": "string",
                    "description": "One-line fact for add, closing note for close, or body/description for save.",
                },
                "title": {
                    "type": "string",
                    "description": "Short title (--name) when saving a new full memory with action=save.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional project hub to attach when using action=save.",
                },
            },
            "required": ["action"],
        },
    },
}
_ANCHOR_RE = re.compile(r"^- @(?:fail|todo|rule|state|idea)#", re.IGNORECASE)
_HUB_LINK_RE = re.compile(r"\((hub-[a-z0-9_-]+\.md)\)")
_TOKEN_RE = re.compile(r"[a-z0-9_-]{3,}", re.IGNORECASE)


def resolve_isymem_dir(workspace_root: Path | str | None = None) -> Path | None:
    """Locate the active shared ``isymem`` directory, or None when unavailable.

    Inside pytest runs, only an explicit ``ISYMEM_DIR`` override is loaded so
    unrelated tests stay hermetically isolated from the host memory bank.
    """
    override = os.environ.get("ISYMEM_DIR", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if (candidate / "MEMORY.md").is_file() or candidate.is_dir():
            return candidate.resolve()
        return None
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    candidates: list[Path] = []
    if workspace_root is not None:
        ws = Path(workspace_root)
        candidates.append(ws / "docs" / "agent" / "memory")
    home = Path.home()
    candidates.append(home / ".config" / "isyco-memory" / "memory")
    for path in candidates:
        try:
            if (path / "MEMORY.md").is_file():
                return path.resolve()
        except OSError:
            continue
    return None


def isymem_executable() -> str | None:
    """Return the ``isymem`` CLI path on PATH or ~/.local/bin."""
    found = shutil.which("isymem")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "isymem"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return None


def _clip_text(text: str, limit: int) -> str:
    raw = text.strip()
    if len(raw) <= limit:
        return raw
    clipped = raw[:limit]
    nl = clipped.rfind("\n")
    if nl > limit // 2:
        clipped = clipped[:nl]
    return clipped.rstrip() + "\n…[truncated]"


def _matching_hubs(index_text: str, mem_dir: Path, workspace_root: Path | None, query: str) -> list[str]:
    """Return up to two relevant hub excerpts matched by workspace name or prompt words."""
    terms = set(_TOKEN_RE.findall(query.casefold()))
    if workspace_root is not None:
        terms.update(_TOKEN_RE.findall(Path(workspace_root).name.casefold()))
    if not terms:
        return []
    candidates: list[tuple[int, str, Path]] = []
    for line in index_text.splitlines():
        match = _HUB_LINK_RE.search(line)
        if not match:
            continue
        hub_file = mem_dir / match.group(1)
        if not hub_file.is_file():
            continue
        line_terms = set(_TOKEN_RE.findall(line.casefold()))
        stem_terms = set(_TOKEN_RE.findall(hub_file.stem.casefold()))
        score = len(terms & (line_terms | stem_terms))
        if score > 0:
            candidates.append((score, hub_file.stem, hub_file))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    snippets: list[str] = []
    for _, _, hub_path in candidates[:2]:
        try:
            raw = hub_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Keep title + open anchors + first concise lines
        lines = [ln for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("---")]
        highlights = [ln for ln in lines if ln.startswith("#") or _ANCHOR_RE.match(ln)]
        excerpt = "\n".join(highlights[:12] if highlights else lines[:12])
        if excerpt:
            snippets.append(f"### {hub_path.name}\n{excerpt}")
    return snippets


def load_isymem_context(
    workspace_root: Path | str | None = None,
    *,
    query: str = "",
    max_chars: int = MAX_TOTAL_CHARS,
) -> str:
    """Load concise shared ``isymem`` index + matching hubs for an ISyCode session."""
    mem_dir = resolve_isymem_dir(workspace_root)
    if mem_dir is None:
        return ""
    index_path = mem_dir / "MEMORY.md"
    try:
        index_raw = index_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not index_raw:
        return ""
    ws_path = Path(workspace_root) if workspace_root is not None else None
    hubs = _matching_hubs(index_raw, mem_dir, ws_path, query)
    index_clip = _clip_text(index_raw, MAX_INDEX_CHARS)
    hub_block = _clip_text("\n\n".join(hubs), MAX_HUB_CHARS) if hubs else ""
    cli = isymem_executable() or "isymem"
    header = (
        f"Shared Multi-Harness Memory (`isymem` primary memory across TUIs): {mem_dir}\n"
        f"CLI (`{cli}`): `isymem <project>`, `isymem <project> --open`, `isymem recall \"<topic>\"`, "
        "`isymem show <slug>`, `isymem add <project> --fail|--todo|--rule|--state|--idea \"<fact>\"`, "
        "`isymem close <id> --note \"...\"`, `isymem save <slug> ...`. Never store secrets/tokens.\n"
        f"\n{index_clip}"
    )
    if hub_block:
        header += f"\n\nRelevant hubs:\n{hub_block}"
    return _clip_text(header, max_chars)


def _run_tokens(tokens: list[str], *, workspace_root: Path | str, timeout_s: float = 10.0) -> tuple[int, str]:
    """Execute ``isymem`` with an explicit argument vector."""
    exe = isymem_executable()
    if not exe:
        return 1, "isymem CLI was not found on PATH or ~/.local/bin/isymem."
    try:
        proc = subprocess.run(
            [exe, *tokens],
            cwd=str(workspace_root),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"isymem error: {exc}"
    output = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    combined = "\n".join(part for part in (output, err) if part)
    return proc.returncode, combined or "(no output)"


def run_isymem_cli(
    raw_args: str,
    *,
    workspace_root: Path | str,
    timeout_s: float = 10.0,
) -> tuple[int, str]:
    """Run an ``isymem`` CLI query safely for the ``/isymem`` slash command."""
    try:
        tokens = shlex.split(raw_args.strip()) if raw_args.strip() else ["projects"]
    except ValueError as exc:
        return 2, f"Invalid arguments: {exc}"
    return _run_tokens(tokens, workspace_root=workspace_root, timeout_s=timeout_s)


def _contains_secret_text(value: str) -> bool:
    try:
        from isycode.workspace_memory import contains_secret
        if contains_secret(value):
            return True
    except Exception:
        pass
    return bool(re.search(r"(?:sk-|nvapi-|gh[pousr]_|github_pat_|AKIA)[A-Za-z0-9_\-]{12,}", value))


def _build_isymem_tokens(arguments: dict) -> list[str]:
    action = str(arguments.get("action") or "").strip().lower()
    target = str(arguments.get("target") or "").strip()
    kind = str(arguments.get("kind") or "").strip().lower()
    text = str(arguments.get("text") or "").strip()
    title = str(arguments.get("title") or "").strip()
    project = str(arguments.get("project") or "").strip()
    if action in {"projects", "doctor", "history"}:
        return [action, target] if (action == "history" and target) else [action]
    if action == "list":
        return ["list", "--compact", "--limit", "30"]
    if action == "card":
        if not target:
            raise ValueError("card requires target=<project>")
        return [target, "--open"]
    if action in {"recall", "search", "show"}:
        if not target:
            raise ValueError(f"{action} requires target")
        return [action, target]
    if action == "add":
        if not target or not text:
            raise ValueError("add requires target=<project> and text")
        flag = f"--{kind}" if kind in {"fail", "todo", "rule", "state", "idea"} else "--state"
        return ["add", target, flag, text]
    if action == "close":
        if not target:
            raise ValueError("close requires target=<anchor-id>")
        return ["close", target, *(["--note", text] if text else [])]
    if action == "save":
        if not target or not text:
            raise ValueError("save requires target=<slug> and text")
        mem_type = kind if kind in {"project", "feedback", "user", "reference"} else "project"
        desc = text.splitlines()[0][:140]
        tokens = ["save", target, "--name", title or target, "--desc", desc, "--type", mem_type, "--body", text]
        if project:
            tokens.extend(["--project", project])
        return tokens
    raise ValueError(f"unsupported isymem action: {action!r}")


def execute_isymem_tool(arguments: object, *, workspace_root: Path | str) -> str:
    """Validate and run an ``isymem`` tool call from an assistant (JSON string output)."""
    if isinstance(arguments, str):
        try:
            payload = json.loads(arguments or "{}")
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"invalid JSON arguments: {exc}"})
    elif isinstance(arguments, dict):
        payload = arguments
    else:
        return json.dumps({"error": "arguments must be a JSON object"})
    if resolve_isymem_dir(workspace_root) is None:
        return json.dumps({"error": "no shared isymem memory directory configured"})
    try:
        tokens = _build_isymem_tokens(payload)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    action = str(payload.get("action") or "").strip().lower()
    if action in ISYMEM_WRITE_ACTIONS:
        combined = "\n".join(str(payload.get(k) or "") for k in ("target", "title", "text", "project"))
        if _contains_secret_text(combined):
            return json.dumps({"error": "secrets or tokens cannot be stored in shared isymem memory"})
    rc, output = _run_tokens(tokens, workspace_root=workspace_root)
    return json.dumps({"ok": rc == 0, "exit_code": rc, "action": action, "output": output[:3500]}, ensure_ascii=False)
