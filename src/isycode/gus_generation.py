"""GUS generations (ADR 0013, MK5d): ISyCode runs the gates, the model never reports them.

A generation is what GUS committed on its ``gus/*`` branch since the commit the
branch started at. It moves PREPARED → VALIDATED → PROBED → SEALED, or ends
REJECTED with its evidence:

- V validate: the working tree is clean, something was committed, no changed
  path (or rename source) is L0, the diff is complete, and the L0 fingerprint
  is the one taken when the branch was created.
- T test: the tests of the touched files, run in the command sandbox. A
  change no test covers does not pass.
- A authority: the coverage auditor, m15 closure and L0 manifest tests, run in
  the command sandbox.
- L lint: ``ruff check src --select F821,F811,E9`` in the sandbox, as in CI; when
  the sandbox has no ruff, a compile check of the changed files, and it says so.
- S seal: SHA-256 over the range, the paths, the diff and every gate's evidence.

Commands run through the caller's ``runner`` (the command owner in the TUI), so
the sandbox, staging and journal apply. If the sandbox Python cannot run the
tests, T and A are NOT_RUN and nothing is sealed. Activating a sealed generation
is Danny's merge of the branch (ADR 0013, L2); the generation and its evidence
stay in ISyCode's private state, never in the repository.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Awaitable, Callable

from isycode.gus_l0 import touches_l0

Runner = Callable[[tuple[str, ...]], Awaitable[tuple[int | None, str]]]

PYTEST = ("python3", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider")
PROBE = ("python3", "-B", "-c", "import pytest, rich, textual")
AUTHORITY_TESTS = ("tests/test_action_coverage.py", "tests/test_m15_closure.py", "tests/test_gus_l0.py")
LINT = ("python3", "-B", "-m", "ruff", "check", "--no-cache", "src", "--select", "F821,F811,E9")
MAX_EVIDENCE_CHARS = 4_000


@dataclass(frozen=True)
class GateResult:
    gate: str
    status: str            # PASS, FAIL or NOT_RUN
    detail: str
    evidence_sha256: str = ""
    output: str = ""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _paths(changes: list[dict]) -> list[str]:
    named = []
    for change in changes:
        for key in ("path", "from"):
            if isinstance(change.get(key), str):
                named.append(change[key])
    return named


def targeted_tests(root: Path, changes: list[dict]) -> list[str]:
    """Tests of the touched files: changed tests, and tests/test_<module>*.py for changed modules."""
    found = set()
    for change in changes:
        path = change.get("path")
        if not isinstance(path, str) or change.get("status") == "D" or not path.endswith(".py"):
            continue
        if path.startswith("tests/") and (root / path).is_file():
            found.add(path)
        elif path.startswith("src/isycode/"):
            stem = Path(path).stem
            found.update(item.relative_to(root).as_posix()
                         for item in (root / "tests").glob(f"test_{stem}*.py") if item.is_file())
    return sorted(found)


def validate(changes_result: dict, recorded: dict | None, l0_digest: str) -> GateResult:
    """Gate V, from the git range result and the record taken when the branch was created."""
    problems = []
    if recorded is None:
        problems.append("the branch was not created by /gus branch, so its start is unknown")
    if not changes_result.get("clean"):
        problems.append("uncommitted changes are not part of a generation; commit them first")
    changes = changes_result.get("changes") or []
    if not changes:
        problems.append("nothing was committed since the branch started")
    if changes_result.get("truncated"):
        problems.append("the diff is too large to review")
    touched = sorted({path for path in _paths(changes) if touches_l0(path)})
    if touched:
        problems.append("L0 paths changed: " + ", ".join(touched[:8]))
    if recorded is not None and recorded.get("l0") != l0_digest:
        problems.append("the L0 fingerprint changed since the branch started")
    if problems:
        return GateResult("V", "FAIL", "; ".join(problems))
    return GateResult("V", "PASS", f"{len(changes)} changed paths, none in L0; L0 fingerprint unchanged",
                      _sha(json.dumps(changes, sort_keys=True) + l0_digest))


async def _command_gate(gate: str, argv: tuple[str, ...], runner: Runner, what: str) -> GateResult:
    exit_code, output = await runner(argv)
    tail = output[-MAX_EVIDENCE_CHARS:]
    evidence = _sha(json.dumps([list(argv), exit_code, output]))
    if exit_code == 0:
        return GateResult(gate, "PASS", f"{what} passed", evidence, tail)
    return GateResult(gate, "FAIL", f"{what} failed (exit {exit_code})", evidence, tail)


async def probe_gates(root: Path, changes: list[dict], runner: Runner) -> list[GateResult]:
    """Gates T, A and L. They run only when the sandbox Python can run the tests."""
    exit_code, output = await runner(PROBE)
    if exit_code != 0:
        reason = "the sandbox Python cannot import pytest, rich and textual"
        return [GateResult(gate, "NOT_RUN", reason, _sha(output), output[-MAX_EVIDENCE_CHARS:])
                for gate in ("T", "A", "L")]
    results = []
    tests = targeted_tests(root, changes)
    if tests:
        results.append(await _command_gate("T", PYTEST + tuple(tests), runner,
                                           f"{len(tests)} test files of the touched code"))
    else:
        results.append(GateResult("T", "FAIL", "no test covers the changed code; add one"))
    results.append(await _command_gate("A", PYTEST + AUTHORITY_TESTS, runner,
                                       "coverage auditor, m15 closure and L0 manifest tests"))
    exit_code, output = await runner(LINT)
    if exit_code is not None and exit_code != 0 and "No module named ruff" in output:
        changed = tuple(path for path in _paths(changes) if path.endswith(".py")
                        and (root / path).is_file())
        if changed:
            lint = await _command_gate("L", ("python3", "-B", "-m", "py_compile") + changed, runner,
                                       "compile check (ruff is not installed in the sandbox)")
        else:
            lint = GateResult("L", "PASS", "no Python files changed; ruff is not installed in the sandbox")
    else:
        evidence = _sha(json.dumps([list(LINT), exit_code, output]))
        lint = GateResult("L", "PASS" if exit_code == 0 else "FAIL",
                          "ruff check passed" if exit_code == 0 else f"ruff check failed (exit {exit_code})",
                          evidence, output[-MAX_EVIDENCE_CHARS:])
    results.append(lint)
    return results


def seal(record: dict) -> str:
    """SHA-256 over the range, paths, diff and the V/T/A/L evidence (S carries the result)."""
    material = {key: record[key] for key in ("branch", "base", "head", "changes", "diff_sha256")}
    material["gates"] = [[gate["gate"], gate["status"], gate["evidence_sha256"]]
                         for gate in record["gates"] if gate["gate"] != "S"]
    return _sha(json.dumps(material, sort_keys=True))


async def build_generation(root: Path, branch: str, changes_result: dict, recorded: dict | None,
                           l0_digest: str, runner: Runner) -> dict:
    """Run every gate in order and return the generation record (sealed or rejected)."""
    record = {
        "id": f"gen_{int(time.time() * 1000):013d}_{secrets.token_hex(4)}",
        "branch": branch, "base": changes_result.get("base", ""),
        "head": changes_result.get("head", ""), "changes": changes_result.get("changes") or [],
        "diff_sha256": _sha(changes_result.get("diff", "")), "states": ["PREPARED"],
        "gates": [], "state": "PREPARED", "seal": "", "created_at": time.time(),
    }
    gate = validate(changes_result, recorded, l0_digest)
    record["gates"].append(asdict(gate))
    if gate.status != "PASS":
        record["state"] = "REJECTED"
        record["states"].append("REJECTED")
        return record
    record["states"].append("VALIDATED")
    probed = await probe_gates(root, record["changes"], runner)
    record["gates"].extend(asdict(item) for item in probed)
    if any(item.status != "PASS" for item in probed):
        record["state"] = "REJECTED"
        record["states"].append("REJECTED")
        return record
    record["states"].append("PROBED")
    record["seal"] = seal(record)
    record["gates"].append(asdict(GateResult("S", "PASS", "sealed", record["seal"])))
    record["state"] = "SEALED"
    record["states"].append("SEALED")
    return record


__all__ = ["AUTHORITY_TESTS", "GateResult", "LINT", "PROBE", "PYTEST", "build_generation",
           "probe_gates", "seal", "targeted_tests", "validate"]
