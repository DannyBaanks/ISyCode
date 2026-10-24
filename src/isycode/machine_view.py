"""GUS's machine view (ADR 0015): read across the machine, never credentials.

The machine view is one more read-only execution owner. It only runs inside a
GUS turn, only after the person consented to a read scope, and only through
Workspace-style authorization: ``MachineAuthority`` decides the consent and the
turn, ``MachineReadBoundary`` decides the path, ``ProductActionGate`` records
the decision and the receipt, and ``MachineReadOwner`` opens files without
following links.

Everything the person can read is in scope except the names and stores that
hold credentials, keys, keyrings, browser profiles and shell history, the
ISyCode state directory, and the homes of other users when the scope is the
whole machine. Those refusals are by name and by absolute prefix; content that
looks like a secret inside an innocently named file is not detected, and that
limit is recorded in ADR 0015.

The folder of the conversation and the edit target are always readable, even
when the chosen scope does not contain them: GUS must know the code it edits.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate
from isycode.actions import MACHINE_READ_ACTIONS
from isycode.security import ActionRequest, AuthorityDecision, SystembilityResult
from isycode.sensitive_paths import SENSITIVE_NAMES, is_sensitive_path_name
from isycode.workspace_setup import state_root

MAX_PATH_CHARS = 4096
MAX_QUERY_CHARS = 256
# One read: 256 KiB; one turn: 2 MiB and 64 whole files.
MAX_FILE_BYTES = 256 * 1024
MAX_TURN_BYTES = 2 * 1024 * 1024
MAX_TURN_FILES = 64
# Listing, name search and content search budgets.
MAX_LIST_ENTRIES = 200
MAX_SEARCH_ENTRIES = 20_000
MAX_GREP_MATCHES = 200
MAX_GREP_SCAN_BYTES = 16 * 1024 * 1024
MAX_WALK_DEPTH = 6
MAX_OUTPUT_CHARS = 24_000
HARDLINK_READ_REASON = ("files with more than one hard link are not read: "
                        "another name may point outside the scope")

DENIED_PREFIXES = (
    "/proc", "/sys", "/dev", "/run", "/root", "/boot", "/lost+found",
    "/var/lib", "/var/run", "/var/cache",
    "/etc/shadow", "/etc/gshadow", "/etc/sudoers", "/etc/sudoers.d",
    "/etc/ssl/private", "/etc/pki/private", "/etc/ssh",
)
# Credential containers that do not live under a sensitive folder name.
DENIED_NAMES = frozenset({
    "cookies", "login data", "local state", "logins.json", "key4.db", "cert9.db",
    "keychain", "credentials.sqlite3",
    ".bash_history", ".zsh_history", ".python_history", ".node_repl_history",
    ".mysql_history", ".psql_history",
})
DENIED_SUFFIXES = (".keyring", ".kdbx")
# Home-relative stores that hold credentials behind an innocent folder name.
DENIED_HOME_TAILS = (
    (".docker", "config.json"),
    (".kube", "config"),
    (".config", "gcloud"),
    (".azure",),
)
# The checkout's own .isycode folder is configuration, not a credential store;
# the state directory is refused separately and by absolute path.
MACHINE_SENSITIVE_NAMES = frozenset(Path(name).name for name in SENSITIVE_NAMES
                                    if name != ".isycode")
SKIPPED_DIRECTORIES = frozenset({
    "node_modules", "__pycache__", ".venv", "venv", ".tox", ".nox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", "target", ".next", ".nuxt",
    ".output", ".cache", ".eggs", "site-packages", ".worktrees", ".codex-worktrees",
    ".zwork", "htmlcov", "coverage", "Pods", "DerivedData",
})


class MachineScopeError(ValueError):
    """A path or a scope that the machine view cannot use safely."""


def home_directory() -> Path:
    try:
        return Path.home().resolve(strict=True)
    except (OSError, RuntimeError):
        return Path.home()


def permitted_roots(settings: dict[str, Any], *, visible: Path,
                    target: Path | None) -> tuple[Path, ...]:
    """The consented scope plus the conversation folder and the edit target."""
    scope = settings.get("read_scope") or {}
    mode = scope.get("mode")
    candidates: list[Path] = []
    if mode == "machine":
        candidates.append(Path("/") if os.name == "posix" else home_directory())
    elif mode == "home":
        candidates.append(home_directory())
    elif mode == "folders":
        candidates.extend(Path(str(folder)) for folder in scope.get("folders") or [])
    candidates.extend(item for item in (visible, target) if item is not None)
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = Path(candidate).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not resolved.is_dir() or str(resolved) in seen:
            continue
        seen.add(str(resolved))
        roots.append(resolved)
    return tuple(roots)


def containing_root(path: Path, roots: Iterable[Path]) -> Path | None:
    """The most specific permitted root that contains ``path``."""
    found: Path | None = None
    for root in roots:
        if path == root or root in path.parents:
            if found is None or len(root.parts) > len(found.parts):
                found = root
    return found


def absolute_path(value: Any) -> Path:
    """A bounded absolute path with no link traversal resolved yet."""
    if (not isinstance(value, str) or not value.strip() or len(value) > MAX_PATH_CHARS
            or "\0" in value):
        raise MachineScopeError("a machine path must be a bounded absolute string")
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise MachineScopeError("machine paths must be absolute")
    return Path(os.path.abspath(raw))


def is_machine_sensitive_name(name: str) -> bool:
    folded = name.casefold()
    if folded in DENIED_NAMES or folded.endswith(DENIED_SUFFIXES):
        return True
    if folded in MACHINE_SENSITIVE_NAMES:
        return True
    return is_sensitive_path_name(name) and folded != ".isycode"


def _relative_parts(path: Path, root: Path) -> tuple[str, ...]:
    try:
        return path.relative_to(root).parts
    except ValueError:
        return ()


def denied_path(path: Path, roots: Iterable[Path], *,
                home: Path | None = None) -> str | None:
    """Why this absolute path is never readable, or None."""
    if os.name == "posix":
        text = str(path)
        for prefix in DENIED_PREFIXES:
            if text == prefix or text.startswith(prefix + "/"):
                return f"{prefix} is outside the machine view"
    state = Path(state_root()).expanduser()
    try:
        state = state.resolve(strict=False)
    except (OSError, RuntimeError):
        pass
    if path == state or state in path.parents:
        return "the ISyCode state directory is never readable"
    home = home or home_directory()
    users = home.parent
    machine_wide = any(str(root) == os.sep for root in roots)
    if (machine_wide and users in (Path("/home"), Path("/Users"))
            and users in path.parents and path != home and home not in path.parents):
        return "another user's home is not readable"
    try:
        relative_home = path.relative_to(home).parts
    except ValueError:
        relative_home = ()
    for tail in DENIED_HOME_TAILS:
        if relative_home[:len(tail)] == tail:
            return "/".join(tail) + " holds credentials"
    return None


def component_refusal(root: Path, path: Path) -> str | None:
    """Refuse a symlink component or a sensitive name below ``root``."""
    current = root
    for part in _relative_parts(path, root):
        current = current / part
        if is_machine_sensitive_name(part):
            return f"{part} is a credential or private store"
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            return None
        except OSError:
            return "the path cannot be inspected"
        if stat.S_ISLNK(mode):
            return "symlinks are not followed"
    return None


class MachineReadBoundary:
    """Allow only reads under the consented roots, never credentials or links."""

    name = "MachineReadBoundary"

    def __init__(self, roots: Iterable[Path]):
        self.roots = tuple(Path(root) for root in roots)
        self.home = home_directory()

    def evaluate(self, request: ActionRequest,
                 authority: AuthorityDecision) -> SystembilityResult:
        if request.action_id not in MACHINE_READ_ACTIONS:
            return SystembilityResult(self.name, True, "not applicable to this action")
        try:
            path = absolute_path(request.target)
            root = containing_root(path, self.roots)
            if root is None:
                return self._deny("the path is outside the consented machine scope")
            if request.workspace_root != root:
                return self._deny("the request root does not match its machine scope")
            reason = denied_path(path, self.roots, home=self.home)
            if reason is not None:
                return self._deny(reason)
            reason = component_refusal(root, path)
            if reason is not None:
                return self._deny(reason)
            info = path.lstat()
        except (OSError, MachineScopeError, ValueError) as exc:
            return self._deny(str(exc)[:300] or "the path cannot be inspected")
        if stat.S_ISDIR(info.st_mode):
            if request.action_id == "machine.files.read":
                return self._deny("a directory cannot be read")
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink > 1:
                return self._deny(HARDLINK_READ_REASON)
        else:
            return self._deny("devices, pipes and sockets are not read")
        return SystembilityResult(self.name, True,
                                  "inside the consented machine scope and not a private store")

    def _deny(self, reason: str) -> SystembilityResult:
        return SystembilityResult(self.name, False, reason)


class MachineAuthority:
    """Duck-typed authority for machine reads: consent and an open GUS turn."""

    def __init__(self, roots: Iterable[Path], consented: Callable[[], bool]):
        self.roots = tuple(Path(root) for root in roots)
        self._consented = consented

    def evaluate(self, request: ActionRequest, *, approvals=None,
                 approval=None, preview: bool = False) -> AuthorityDecision:
        if not isinstance(request, ActionRequest):
            return AuthorityDecision(False, "", "invalid action request", "")
        digest = request.digest
        if request.action_id not in MACHINE_READ_ACTIONS:
            return AuthorityDecision(False, "", "action is not a machine read", digest)
        if not any(request.workspace_root == root for root in self.roots):
            return AuthorityDecision(False, "", "request root is not a consented machine root",
                                     digest)
        try:
            consented = bool(self._consented())
        except Exception:
            consented = False
        if not consented:
            return AuthorityDecision(
                False, "", "GUS has no current consent for this machine scope", digest)
        from isycode.gus_l0 import gus_any_turn_active
        if not gus_any_turn_active():
            return AuthorityDecision(False, "", "machine reads run only inside a GUS turn",
                                     digest)
        return AuthorityDecision(True, "grant:machine.read",
                                 "GUS machine read inside its consented scope", digest)


@dataclass
class MachineBudget:
    """Whole-file reads charged against one GUS turn."""

    files: int = 0
    bytes: int = 0


_BUDGET: ContextVar[MachineBudget | None] = ContextVar("isycode_machine_budget", default=None)


@contextmanager
def machine_budget():
    """Start the per-turn machine read budget; tool calls in the turn share it."""
    token = _BUDGET.set(MachineBudget())
    try:
        yield
    finally:
        _BUDGET.reset(token)


def _charge_read(size: int) -> None:
    budget = _BUDGET.get()
    if budget is None:
        return
    if budget.files + 1 > MAX_TURN_FILES:
        raise MachineScopeError(f"this turn already read {MAX_TURN_FILES} files")
    if budget.bytes + size > MAX_TURN_BYTES:
        raise MachineScopeError("this turn reached its 2 MiB machine read budget")
    budget.files += 1
    budget.bytes += size


def _skip_directory(name: str) -> bool:
    folded = name.casefold()
    return (name in SKIPPED_DIRECTORIES or folded in SKIPPED_DIRECTORIES
            or folded.startswith((".venv-", ".venv_", "venv-", "venv_"))
            or folded.endswith(".egg-info"))


def _fit_json_result(result: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(result) <= limit:
        return result
    try:
        payload = json.loads(result)
    except ValueError:
        return result[:limit] + "\n[output truncated]"
    if isinstance(payload, dict) and isinstance(payload.get("text"), str):
        text, suffix = payload["text"], "\n[output truncated]"
        low, high = 0, len(text)
        best = json.dumps({**payload, "text": suffix.lstrip("\n"), "truncated": True},
                          ensure_ascii=False)
        while low <= high:
            middle = (low + high) // 2
            candidate = json.dumps({**payload, "text": text[:middle] + suffix,
                                    "truncated": True}, ensure_ascii=False)
            if len(candidate) <= limit:
                best, low = candidate, middle + 1
            else:
                high = middle - 1
        return best if len(best) <= limit else result[:limit]
    for key in ("matches", "entries"):
        if isinstance(payload.get(key), list):
            items = payload[key]
            low, high = 0, len(items)
            best = json.dumps({**payload, key: [], "truncated": True}, ensure_ascii=False)
            while low <= high:
                middle = (low + high) // 2
                candidate = json.dumps({**payload, key: items[:middle], "truncated": True},
                                       ensure_ascii=False)
                if len(candidate) <= limit:
                    best, low = candidate, middle + 1
                else:
                    high = middle - 1
            return best if len(best) <= limit else result[:limit]
    return result[:limit] + "\n[output truncated]"


class MachineReadOwner:
    """Execute list/read/search/grep inside one permitted machine root."""

    def __init__(self, root: Path, roots: Iterable[Path], *,
                 consented: Callable[[], bool]):
        self.root = Path(root)
        self.roots = tuple(Path(item) for item in roots)
        self.authority = MachineAuthority(self.roots, consented)
        self.boundary = MachineReadBoundary(self.roots)
        self.gate = ProductActionGate(self.root, self.authority, owner_id="machine_view",
                                      extra_systembilities=(self.boundary,))
        from isycode.winfs import use_verified_fs
        self._verified = use_verified_fs()

    def execute(self, action_id: str, arguments: dict[str, Any]) -> ActionOutcome:
        if action_id not in MACHINE_READ_ACTIONS:
            return ActionOutcome("Action unavailable.", "DENY", None,
                                 "action is not registered for the machine view")
        if not isinstance(arguments, dict):
            return ActionOutcome("Malformed action arguments.", "DENY", None,
                                 "arguments must be an object")
        try:
            path = absolute_path(arguments.get("path"))
            query = arguments.get("query")
            if query is not None and (not isinstance(query, str) or not query.strip()
                                      or len(query) > MAX_QUERY_CHARS):
                raise MachineScopeError("search text must contain 1–256 characters")
        except (MachineScopeError, ValueError) as exc:
            return ActionOutcome("ISySentinel denied this action.", "DENY", None, str(exc))
        parameters: dict[str, Any] = {"path": str(path)}
        if query is not None:
            parameters["query"] = query
        request = ActionRequest(action_id, self.root, str(path), parameters,
                                execution_owner="machine_view")
        try:
            _, decision = self.gate.authorize(request)
        except Exception:
            return ActionOutcome("ISySentinel denied this action.", "DENY", None,
                                 "authorization evaluation failed")
        if not decision.allowed:
            reason = "; ".join(f"{item.name}: {item.reason}" for item in decision.checks
                               if not item.passed)
            return ActionOutcome("ISySentinel denied this action.", "DENY", None, reason)
        try:
            if action_id == "machine.files.list":
                result = self._list(path)
            elif action_id == "machine.files.read":
                result = self._read(path)
            elif action_id == "machine.files.search":
                result = self._search(query.strip(), path)
            else:
                result = self._grep(query.strip(), path)
        except (OSError, MachineScopeError, ValueError) as exc:
            return ActionOutcome("Read action failed; no content was returned.",
                                 "ERROR", None, str(exc)[:300])
        result = _fit_json_result(result)
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), action_id, request.digest, "ALLOW", "SUCCESS",
            hashlib.sha256(result.encode("utf-8")).hexdigest())
        if not receipt.verify(request, result):
            return ActionOutcome("Receipt verification failed; result blocked.",
                                 "NOT_VERIFIABLE", None,
                                 "local receipt did not match request/result")
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome("Receipt persistence failed; result blocked.",
                                 "NOT_VERIFIABLE", None,
                                 "durable action journal is unavailable")
        return ActionOutcome(result, "ALLOW", receipt, "verified machine read-only operation")

    # ── operations ────────────────────────────────────────────
    def _list(self, directory: Path) -> str:
        entries = []
        for item in self._entries(directory):
            if is_machine_sensitive_name(item.name) or item.is_symlink():
                continue
            kind = "directory" if item.is_dir(follow_symlinks=False) else "file"
            entries.append({"name": item.name, "kind": kind})
        entries.sort(key=lambda value: (value["kind"] != "directory", value["name"].casefold()))
        truncated = len(entries) > MAX_LIST_ENTRIES
        payload: dict[str, Any] = {"path": str(directory),
                                   "entries": entries[:MAX_LIST_ENTRIES]}
        if truncated:
            payload["truncated"] = True
        return json.dumps(payload, ensure_ascii=False)

    def _read(self, path: Path) -> str:
        descriptor = self._open_file(path)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise MachineScopeError("selected path is not a regular file")
            if info.st_nlink > 1:
                raise MachineScopeError(HARDLINK_READ_REASON)
            if info.st_size > MAX_FILE_BYTES:
                raise MachineScopeError("file exceeds the 256 KiB machine read limit")
            _charge_read(info.st_size)
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise MachineScopeError("file grew past the 256 KiB machine read limit")
        if b"\0" in data:
            raise MachineScopeError("binary or non-UTF-8 files are not read")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MachineScopeError("binary or non-UTF-8 files are not read") from exc
        return json.dumps({"path": str(path), "text": text}, ensure_ascii=False)

    def _search(self, query: str, start: Path) -> str:
        pending: deque[tuple[Path, int]] = deque([(start, 0)])
        matches: list[dict[str, str]] = []
        visited = entries_seen = 0
        truncated = False
        folded = query.casefold().strip("/")
        while pending:
            directory, depth = pending.popleft()
            if depth >= MAX_WALK_DEPTH:
                truncated = True
                continue
            try:
                listed = sorted(self._entries(directory), key=lambda item: item.name.casefold())
            except OSError:
                continue
            visited += 1
            for child in listed:
                if is_machine_sensitive_name(child.name) or child.is_symlink():
                    continue
                is_dir = child.is_dir(follow_symlinks=False)
                if is_dir and _skip_directory(child.name):
                    continue
                entries_seen += 1
                if entries_seen > MAX_SEARCH_ENTRIES:
                    truncated = True
                    break
                path = directory / child.name
                if folded in child.name.casefold():
                    matches.append({"path": str(path),
                                    "kind": "directory" if is_dir else "file"})
                    if len(matches) >= MAX_LIST_ENTRIES:
                        truncated = True
                        break
                if is_dir:
                    pending.append((path, depth + 1))
            if truncated:
                break
        return json.dumps({"query": query, "matches": matches,
                           "directories_scanned": visited, "truncated": truncated},
                          ensure_ascii=False)

    def _grep(self, query: str, start: Path) -> str:
        folded = query.casefold()
        matches: list[dict[str, Any]] = []
        pending: deque[tuple[Path, int]] = deque()
        files: deque[Path] = deque()
        scanned_bytes = entries_seen = files_scanned = 0
        truncated = False
        try:
            if start.is_dir():
                pending.append((start, 0))
            else:
                files.append(start)
        except OSError:
            raise MachineScopeError("the search path cannot be inspected") from None
        while pending or files:
            if files:
                path = files.popleft()
                descriptor = self._open_file(path)
                with os.fdopen(descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink > 1
                            or info.st_size > MAX_FILE_BYTES):
                        continue
                    scanned_bytes += info.st_size
                    if scanned_bytes > MAX_GREP_SCAN_BYTES:
                        truncated = True
                        break
                    data = stream.read(MAX_FILE_BYTES + 1)
                files_scanned += 1
                if len(data) > MAX_FILE_BYTES or b"\0" in data[:8192]:
                    continue
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                for number, line in enumerate(text.splitlines(), 1):
                    if folded in line.casefold():
                        matches.append({"path": str(path), "line": number,
                                        "text": line.strip()[:300]})
                        if len(matches) >= MAX_GREP_MATCHES:
                            truncated = True
                            break
                if truncated:
                    break
                continue
            directory, depth = pending.popleft()
            if depth >= MAX_WALK_DEPTH:
                truncated = True
                continue
            try:
                children = sorted(self._entries(directory),
                                  key=lambda item: item.name.casefold())
            except OSError:
                continue
            for child in children:
                if (is_machine_sensitive_name(child.name) or child.is_symlink()
                        or _skip_directory(child.name)):
                    continue
                entries_seen += 1
                if entries_seen > MAX_SEARCH_ENTRIES:
                    truncated = True
                    break
                if child.is_dir(follow_symlinks=False):
                    pending.append((directory / child.name, depth + 1))
                elif child.is_file(follow_symlinks=False):
                    files.append(directory / child.name)
            if truncated:
                break
        return json.dumps({"query": query, "matches": matches,
                           "files_scanned": files_scanned, "truncated": truncated},
                          ensure_ascii=False)

    # ── descriptor-safe access ────────────────────────────────
    def _entries(self, directory: Path) -> list[Any]:
        if self._verified:
            from isycode.winfs import VerifiedFS
            return VerifiedFS(self.root).list_dir(directory)
        descriptor = self._open_directory(directory)
        try:
            with os.scandir(descriptor) as iterator:
                return list(iterator)
        finally:
            os.close(descriptor)

    def _open_directory(self, directory: Path) -> int:
        if self._verified:
            raise OSError("descriptor walks are not available on this platform")
        relative = directory.relative_to(self.root)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.root, flags)
        try:
            for part in relative.parts:
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    def _open_file(self, path: Path) -> int:
        if self._verified:
            from isycode.winfs import VerifiedFS
            return VerifiedFS(self.root).open_read(path)
        parent = self._open_directory(path.parent)
        try:
            return os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                           | getattr(os, "O_NONBLOCK", 0), dir_fd=parent)
        finally:
            os.close(parent)


class MachineView:
    """One GUS turn's machine view: scope, consent and one owner per root."""

    def __init__(self, roots):
        self.roots = roots
        self.scope = permitted_roots(roots.data, visible=roots.visible, target=roots.target)
        self._owners: dict[Path, MachineReadOwner] = {}

    def execute(self, action_id: str, arguments: dict[str, Any]) -> ActionOutcome:
        try:
            path = absolute_path(arguments.get("path"))
        except (MachineScopeError, ValueError, TypeError) as exc:
            return ActionOutcome("ISySentinel denied this action.", "DENY", None, str(exc))
        root = containing_root(path, self.scope)
        if root is None:
            return ActionOutcome("ISySentinel denied this action.", "DENY", None,
                                 "the path is outside the consented machine scope")
        owner = self._owners.get(root)
        if owner is None:
            try:
                owner = MachineReadOwner(root, self.scope,
                                         consented=self.roots.consent_ready)
            except (OSError, ValueError) as exc:
                return ActionOutcome("The machine view is unavailable.", "DENY", None,
                                     str(exc)[:300])
            self._owners[root] = owner
        return owner.execute(action_id, arguments)


__all__ = [
    "MachineAuthority", "MachineBudget", "MachineReadBoundary", "MachineReadOwner",
    "MachineScopeError", "MachineView", "absolute_path", "component_refusal",
    "containing_root", "denied_path", "home_directory", "is_machine_sensitive_name",
    "machine_budget", "permitted_roots",
]
