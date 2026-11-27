"""Read-only resident queries and host-owned structural recording.

The reader never writes files. The recorder is intentionally a separate host
component: an external model cannot obtain a write/exec tool through this API.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .store import append_jsonl, latest_by_id, read_jsonl, resident_root, utc_now


EXCLUDED_DIRS = {".git", ".venv", ".venv_linux", "__pycache__", ".pytest_cache", ".isyvm", ".isycode-ide"}
MAP_FILES = {"self_map.jsonl", "decisions.jsonl", "changes.jsonl", "constraints.jsonl"}
QUERY_CATEGORIES = {
    "architecture", "component", "contract", "constraint", "protected",
    "decision", "change", "verification", "plan", "unknown", "general",
}


def _relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _role(path: str) -> tuple[str, str]:
    if path.startswith("contracts/"):
        return "contract", "contract"
    if path.startswith("tests/"):
        filename = path.rsplit("/", 1)[-1]
        if filename.startswith("test_") or filename == "conftest.py":
            return "test", "test"
        return "test_documentation", "project"
    if path == "core/agent/run.py":
        return "agent_loop", "agent_loop"
    if path == "core/policy.py":
        return "authorization", "protected"
    if path == "core/runtime/base.py":
        return "runtime_boundary", "runtime"
    if path.startswith("core/runtime/"):
        return "runtime", "runtime"
    if path.startswith("core/agent/providers/"):
        return "provider", "provider"
    if path == "core/plan.py":
        return "plan", "plan"
    if path.startswith("core/resident/"):
        return "resident", "resident"
    if path.startswith("core/"):
        return "core", "core"
    if path.startswith(("engine/", "isyvm/", "isycode_ide/")):
        return "entrypoint", "entrypoint"
    if path.startswith("sandbox/"):
        return "best_effort_runtime", "runtime"
    if path.startswith("bridge/"):
        return "bridge_reader", "bridge"
    return "project_file", "project"


def _modification_policy(path: str) -> dict[str, Any]:
    if path == "core/runtime/base.py":
        return {
            "modify": "restricted",
            "protected_rules": [
                "path traversal protection",
                "symlink protection",
                "workspace boundary",
            ],
        }
    if path == "core/policy.py":
        return {
            "modify": "restricted",
            "protected_rules": ["policy must fail closed", "do not bypass runtime availability"],
        }
    if path == "core/agent/run.py":
        return {"modify": "allowed", "review": ["provider tool-call protocol", "tool_call_id order"]}
    if path.startswith("tests/") or path.startswith("contracts/"):
        return {"modify": "allowed", "review": ["keep evidence aligned with implementation"]}
    return {"modify": "allowed"}


def _record(record_type: str, record_id: str, source: str, **fields: Any) -> dict:
    return {
        "type": record_type,
        "id": record_id,
        "timestamp": utc_now(),
        "source": source,
        **fields,
    }


class ResidentRecorder:
    """Host-owned writer for semantic resident records."""

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.root = resident_root(self.project_root)

    def record(self, filename: str, record: dict | Iterable[dict]) -> None:
        records = [record] if isinstance(record, dict) else record
        append_jsonl(self.root / filename, records)

    def ensure_config(self) -> None:
        config_path = self.root / "config.json"
        if config_path.exists():
            return
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({
            "enabled": False,
            "provider": "ollama",
            "model": "qwen2.5:1.5b",
            "context_limit": 4096,
        }, indent=2) + "\n", encoding="utf-8")

    def session_start(self, session_id: str, objective: str = "") -> None:
        self.root.joinpath("sessions").mkdir(parents=True, exist_ok=True)
        self.record(
            f"sessions/{session_id}.jsonl",
            _record("session", f"session:{session_id}:start", "agent", session_id=session_id, event="started", objective=objective),
        )

    def session_event(self, session_id: str, event: str, **fields: Any) -> None:
        self.record(
            f"sessions/{session_id}.jsonl",
            _record("session", f"session:{session_id}:{uuid.uuid4().hex[:12]}", "agent", session_id=session_id, event=event, **fields),
        )

    def change(self, path: str, operation: str, session_id: str = "", verification: str = "pending") -> None:
        self.record(
            "changes.jsonl",
            _record("change", f"change:{uuid.uuid4().hex}", "agent", path=path, operation=operation, session=session_id, verification=verification),
        )

    def verification(self, target: str, status: str, evidence: Iterable[str] = ()) -> None:
        self.record(
            "changes.jsonl",
            _record("verification", f"verification:{uuid.uuid4().hex}", "agent", target=target, status=status, evidence=list(evidence)),
        )


class ResidentReader:
    """Read-only structural knowledge interface exposed to the coder."""

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.root = resident_root(self.project_root)

    def _records(self, filename: str) -> list[dict]:
        return read_jsonl(self.root / filename)

    def config(self) -> dict:
        path = self.root / "config.json"
        defaults = {"enabled": False, "provider": "ollama", "model": "qwen2.5:1.5b", "context_limit": 4096}
        if not path.is_file():
            return defaults
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return {**defaults, **value} if isinstance(value, dict) else {**defaults, "status": "unknown"}
        except json.JSONDecodeError:
            return {**defaults, "status": "unknown", "reason": "malformed resident config"}

    def context_pack(self) -> dict:
        records = self.map_records()
        changes = self._records("changes.jsonl")
        return {
            "current": {
                "components": len(records),
                "protected": [r.get("path") for r in records if r.get("modify") == "restricted"],
            },
            "recent": changes[-5:],
            "important": {
                "constraints": self._records("constraints.jsonl"),
                "decisions": self._records("decisions.jsonl"),
            },
            "on_demand": "resident.query(intent) for focused guidance",
        }

    def status(self) -> dict:
        components = latest_by_id(self._records("self_map.jsonl"))
        constraints = self._records("constraints.jsonl")
        changes = self._records("changes.jsonl")
        protected = [r for r in components.values() if r.get("status") == "protected" or r.get("protected_rules")]
        pending = [
            r for r in changes
            if r.get("verification") == "pending" and r.get("operation") != "added"
        ]
        return {
            "components": len(components),
            "contracts": sum(1 for r in components.values() if r.get("type") == "contract"),
            "constraints": len(constraints),
            "protected": len(protected),
            "recent_changes": len(changes[-5:]),
            "pending_verification": len(pending),
            "state_root": str(self.root),
        }

    def map_records(self) -> list[dict]:
        return list(latest_by_id(self._records("self_map.jsonl")).values())

    def _keywords(self, intent: str) -> set[str]:
        words = set(re.findall(r"[A-Za-z0-9_./-]+", intent.lower()))
        return {word for word in words if len(word) > 2}

    def query(self, intent: str, provider: Optional[Callable[[dict], dict]] = None, category: str = "general") -> dict:
        if category not in QUERY_CATEGORIES:
            return {
                "status": "unknown", "category": category, "intent": intent,
                "relevant": [], "guidance": [], "unknowns": [{"reason": "unsupported query category"}],
                "protected": [], "sources": [], "warnings": [],
            }
        records = self.map_records()
        keywords = self._keywords(intent)
        relevant = []
        for record in records:
            haystack = " ".join(str(record.get(key, "")) for key in ("path", "role", "content", "modify"))
            if not keywords or any(keyword in haystack.lower() for keyword in keywords):
                relevant.append(record)

        if not relevant and not keywords:
            relevant = [r for r in records if r.get("role") in {"agent_loop", "authorization", "runtime_boundary"}]
        relevant = relevant[:20]
        protected = [r for r in records if r.get("modify") == "restricted" or r.get("status") == "protected"]
        contracts = [r for r in records if r.get("type") == "contract"]
        tests = [r for r in records if r.get("type") == "test" or r.get("role") == "test"]
        relevant_roles = {r.get("role") for r in relevant}
        related_tests = []
        for test in tests:
            test_path = str(test.get("path", ""))
            if (
                "runtime_boundary" in relevant_roles and "runtime_boundary" in test_path
                or "agent_loop" in relevant_roles and "agent" in test_path
                or "provider" in relevant_roles and "provider" in test_path
                or "authorization" in relevant_roles and ("agent" in test_path or "policy" in test_path)
            ):
                related_tests.append(test)
        constraints = self._records("constraints.jsonl")
        decisions = self._records("decisions.jsonl")
        warnings = [
            "Resident guidance is structural context, not implementation authority.",
            "Unknown facts remain unknown until evidence is recorded.",
        ]
        guidance = {
            "category": category,
            "intent": intent,
            "relevant": relevant,
            "reuse": [r for r in relevant if r.get("modify") == "allowed"][:10],
            "protected": protected,
            "contracts": contracts[:20],
            "tests": (related_tests if relevant else [])[:20],
            "constraints": constraints,
            "decisions": decisions,
            "warnings": warnings,
            "status": "verified" if relevant else "unknown",
            "evidence": [r.get("evidence", []) for r in relevant if r.get("evidence")],
        }
        if provider is not None:
            try:
                model_guidance = provider(guidance)
                if isinstance(model_guidance, dict):
                    guidance["model_guidance"] = model_guidance
            except Exception as exc:
                guidance["warnings"].append(f"resident provider unavailable: {exc}")
                guidance["model_status"] = "unknown"
        return guidance

    def verify(self) -> dict:
        failures = []
        for filename in MAP_FILES:
            for record in self._records(filename):
                if not isinstance(record, dict) or not record.get("type") or record.get("status") == "unknown":
                    failures.append({"file": filename, "reason": "record missing type"})
        return {"status": "ok" if not failures else "fail", "files": sorted(MAP_FILES), "failures": failures}


class SelfScanner:
    """Deterministic self-scan; the optional model is not required per file."""

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.recorder = ResidentRecorder(self.project_root)
        self.reader = ResidentReader(self.project_root)

    def _files(self) -> list[Path]:
        files = []
        for path in self.project_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.project_root)
            if any(part in EXCLUDED_DIRS for part in relative.parts):
                continue
            if relative.parts and relative.parts[0] in {".isyvm", ".isycode-ide"}:
                continue
            if path.suffix.lower() in {".py", ".iesy", ".md", ".txt", ".cmd"}:
                files.append(path)
        return sorted(files)

    def _directories(self) -> list[Path]:
        directories = []
        for path in self.project_root.rglob("*"):
            if not path.is_dir() or path == self.project_root:
                continue
            relative = path.relative_to(self.project_root)
            if any(part in EXCLUDED_DIRS for part in relative.parts):
                continue
            directories.append(path)
        return sorted(directories)

    def scan(self) -> dict:
        old = latest_by_id(self.reader._records("self_map.jsonl"))
        self.recorder.ensure_config()
        current: dict[str, dict] = {}
        for path in self._files():
            relative = _relative(self.project_root, path)
            role, category = _role(relative)
            status = "protected" if relative in {"core/policy.py", "core/runtime/base.py"} else "active"
            record = _record(
                category if category in {"contract", "capability", "test", "provider", "runtime", "plan", "entrypoint"} else "component",
                f"component:{relative}",
                "self_scan",
                path=relative,
                role=role,
                status=status,
                content_hash=_sha256(path),
                **_modification_policy(relative),
            )
            if category == "contract":
                record["type"] = "contract"
            current[record["id"]] = record

        for path in self._directories():
            relative = _relative(self.project_root, path)
            current[f"directory:{relative}"] = _record(
                "component", f"directory:{relative}", "self_scan",
                path=relative, role="directory", status="active", modify="allowed",
            )
            if (path / "execute.py").is_file():
                current[f"capability:{relative}"] = _record(
                    "capability", f"capability:{relative}", "self_scan",
                    path=relative, role="capability", status="active",
                    entry="execute.py", evidence=[relative + "/execute.py"], modify="allowed",
                )

        added = [key for key in current if key not in old]
        modified = [key for key in current if key in old and current[key].get("content_hash") != old[key].get("content_hash")]
        removed = [key for key in old if key not in current]
        self.recorder.record("self_map.jsonl", current.values())

        files_added = [current[key].get("path") for key in added if current[key].get("role") != "directory"]
        files_modified = [current[key].get("path") for key in modified if current[key].get("role") != "directory"]
        files_deleted = [old[key].get("path") for key in removed if old[key].get("role") != "directory"]
        directories_added = [current[key].get("path") for key in added if current[key].get("role") == "directory"]
        directories_deleted = [old[key].get("path") for key in removed if old[key].get("role") == "directory"]
        protected_paths = {"core/policy.py", "core/runtime/base.py"}
        protected_touches = sorted({
            path for path in files_added + files_modified + files_deleted
            if path in protected_paths
        })
        contracts_detected = sorted(
            record.get("path") for record in current.values() if record.get("type") == "contract"
        )
        tests_detected = sorted(
            record.get("path") for record in current.values() if record.get("role") == "test"
        )

        for key in added:
            self.recorder.record("changes.jsonl", _record("change", f"change:{uuid.uuid4().hex}", "self_scan", path=current[key].get("path"), operation="added", verification="pending"))
        for key in modified:
            self.recorder.record("changes.jsonl", _record("change", f"change:{uuid.uuid4().hex}", "self_scan", path=current[key].get("path"), operation="modified", verification="pending"))
        for key in removed:
            self.recorder.record("changes.jsonl", _record("change", f"change:{uuid.uuid4().hex}", "self_scan", path=old[key].get("path"), operation="deleted", verification="pending"))

        self._seed_knowledge()
        unknowns = [
            record.get("path") for record in current.values()
            if record.get("type") == "unknown"
        ]
        return {
            "status": "ok",
            "files_added": files_added,
            "files_modified": files_modified,
            "files_deleted": files_deleted,
            "directories_added": directories_added,
            "directories_deleted": directories_deleted,
            "unknowns": unknowns,
            "violations": [],
            "protected_touches": protected_touches,
            "tests_detected": tests_detected,
            "contracts_detected": contracts_detected,
            "summary": f"{len(files_added)} added, {len(files_modified)} modified, {len(files_deleted)} deleted",
            "components": len(current),
            "added": len(added),
            "modified": len(modified),
            "deleted": len(removed),
        }

    def _seed_knowledge(self) -> None:
        existing_constraints = self.reader._records("constraints.jsonl")
        if not existing_constraints:
            constraints = [
                _record("constraint", "constraint:runtime-boundary", "self_scan", target="core/runtime/base.py", rule="workspace boundary must remain enforced", evidence=["tests/test_runtime_boundary.py"]),
                _record("constraint", "constraint:resident-read-only", "self_scan", target="core/resident", rule="resident reader has no write, exec, shell, git, or network tools", evidence=["core/resident/service.py"]),
                _record("constraint", "constraint:layer-a", "self_scan", target="core/runtime", rule="Layer A is best-effort local runtime, not a security boundary", evidence=["sandbox/interp.py", "README.md"]),
            ]
            append_jsonl(self.recorder.root / "constraints.jsonl", constraints)
        if not self.reader._records("decisions.jsonl"):
            append_jsonl(self.recorder.root / "decisions.jsonl", [
                _record("decision", "decision:claude-external-loop", "self_scan", content="Claude Code remains an external agent loop", evidence=["core/agent/providers/claude.py", "README.md"]),
                _record("decision", "decision:layer-b-unavailable", "self_scan", content="Unavailable runtimes fail explicitly", evidence=["core/agent/run.py", "tests/test_agent_protocol.py"]),
            ])
