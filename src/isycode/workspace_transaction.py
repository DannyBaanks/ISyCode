"""Reviewed, all-or-rollback edit packs.

One pack is one immutable manifest, one Authority/Sentinel decision, one
approval, one effect-ledger reservation and one operation receipt. It is not
N independent ``workspace_write`` calls: every preimage is backed up before
the first mutation, and an interrupted pack is reconciled before anything
else can write.

The guarantee is deliberately narrow. ``ALLOW`` means every file was applied
and its receipt was journaled. ``ERROR`` with ``rolled_back`` means every
applied file was restored and verified. ``NOT_VERIFIABLE`` means the state is
uncertain or a receipt was lost; the effect is never repeated blindly. There
is no universal atomic visibility or compare-and-swap against non-cooperating
external writers.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from isycode.action_runtime import (
    MAX_PACK_OPERATIONS, MAX_PACK_TOTAL_BYTES, TRANSACTION_ACTION,
    ActionOutcome, ActionReceipt, ProductActionGate,
    edit_pack_manifest_sha256, edit_pack_scope_id,
)
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.effect_ledger import CrashInjected, EffectCost, EffectLedger, LedgerDenied
from isycode.effect_fs import apply_file, digest, read_file
from isycode.security import ActionRequest
from isycode.turn_control import OperationError, OperationJournal, OperationRecord
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WritePreview, WorkspaceWriteOwner

EDIT_PACK_TOOL_NAME = "workspace_edit_pack"
EDIT_PACK_TOOL = {"type": "function", "function": {
    "name": EDIT_PACK_TOOL_NAME,
    "description": (
        "Propose one all-or-rollback pack of 1-8 text edits in one workspace folder. "
        "Each edit needs path and either content (full replacement) or old_text+new_text "
        "(exact-fragment edit, optional replace_all). expected_sha256 optionally binds the "
        "file you read; use 'absent' when creating a file. Parent folders must already exist. "
        "The user reviews every diff together and gives one approval. If any file cannot be "
        "applied, applied files are rolled back; an uncertain result is reported explicitly."
    ),
    "parameters": {"type": "object", "properties": {
        "edits": {"type": "array", "minItems": 1, "maxItems": MAX_PACK_OPERATIONS,
                  "items": {"type": "object", "properties": {
                      "path": {"type": "string", "description": "Workspace-relative file path."},
                      "content": {"type": "string", "description": "Complete new file content."},
                      "old_text": {"type": "string", "description": "Exact current fragment."},
                      "new_text": {"type": "string", "description": "Replacement fragment."},
                      "replace_all": {"type": "boolean", "description": "Replace every occurrence."},
                      "expected_sha256": {"type": "string",
                                          "description": "SHA-256 of the file you read, or 'absent'."},
                  }, "required": ["path"], "additionalProperties": False}},
    }, "required": ["edits"], "additionalProperties": False},
}}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _operation_id(request: ActionRequest) -> str:
    return _sha(TRANSACTION_ACTION.encode("ascii") + b"\0" + request.digest.encode("ascii"))


def _operation_params(preview: WritePreview) -> dict[str, Any]:
    params = preview.request.parameters
    return {
        "path": preview.path,
        "before_sha256": params["before_sha256"],
        "after_sha256": params["after_sha256"],
        "size": params["size"],
        "diff_sha256": params["diff_sha256"],
        "new_folders": list(params["new_folders"]),
    }


def _before(params: Mapping[str, Any]) -> str | None:
    value = params["before_sha256"]
    return None if value == "absent" else value


@dataclass(frozen=True)
class EditPackPreview:
    """The exact manifest the person reviews; apply re-derives it before writing."""

    request: ActionRequest
    operations: tuple[WritePreview, ...]
    inputs: tuple[dict[str, Any], ...]
    before_modes: tuple[int | None, ...]
    scope_id: str
    manifest_sha256: str
    nonce: str

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(operation.path for operation in self.operations)

    @property
    def diff(self) -> str:
        return "\n".join(operation.diff for operation in self.operations)

    @property
    def operation_id(self) -> str:
        return _operation_id(self.request)


class WorkspaceTransactionOwner:
    """Apply one reviewed edit pack through Authority, Sentinel and the ledger."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.writer = WorkspaceWriteOwner(root, authority, approvals)
        self.gate = ProductActionGate(self.root, authority, owner_id="workspace_transaction")

    # ── manifest ─────────────────────────────────────────────────

    def preview(self, edits: list[Mapping[str, Any]], *, nonce: str | None = None) -> EditPackPreview:
        """Read-only construction of the manifest; no folders or files are changed."""
        nonce = secrets.token_hex(8) if nonce is None else nonce
        if not isinstance(nonce, str) or re.fullmatch(r"[0-9a-f]{16}", nonce) is None:
            raise ValueError("edit pack nonce must be 16 lowercase hex characters")
        if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_PACK_OPERATIONS:
            raise ValueError(f"an edit pack needs 1-{MAX_PACK_OPERATIONS} edits")
        previews: list[WritePreview] = []
        inputs: list[dict[str, Any]] = []
        seen: set[str] = set()
        total_bytes = 0
        allowed = {"path", "content", "old_text", "new_text", "replace_all", "expected_sha256"}
        for edit in edits:
            if not isinstance(edit, Mapping) or not set(edit) <= allowed:
                raise ValueError("each edit has unsupported or malformed fields")
            path = edit.get("path")
            content = edit.get("content")
            old_text = edit.get("old_text")
            new_text = edit.get("new_text")
            replace_all = edit.get("replace_all", False)
            expected = edit.get("expected_sha256")
            if not isinstance(path, str) or not isinstance(replace_all, bool):
                raise ValueError("path must be text and replace_all must be a boolean")
            if expected is not None:
                valid_digest = (isinstance(expected, str) and
                                (expected == "absent" or
                                 (len(expected) == 64
                                  and all(c in "0123456789abcdef" for c in expected))))
                if not valid_digest:
                    raise ValueError("expected_sha256 must be a lowercase SHA-256 or 'absent'")
            has_content = content is not None
            has_fragment = old_text is not None or new_text is not None
            if has_content == has_fragment:
                raise ValueError("use either content or old_text+new_text, not both")
            if has_content:
                if not isinstance(content, str):
                    raise ValueError("content must be text")
                operation = self.writer.preview(path, content)
            else:
                if not isinstance(old_text, str) or not isinstance(new_text, str):
                    raise ValueError("old_text and new_text must both be text")
                operation = self.writer.preview_edit(path, old_text, new_text, replace_all)
            params = operation.request.parameters
            if params["new_folders"]:
                raise ValueError("edit packs do not create parent folders; create them first")
            if expected is not None and expected != params["before_sha256"]:
                raise ValueError(f"{operation.path} changed since you read it; review it again")
            folded = operation.path.casefold()
            if folded in seen:
                raise ValueError("an edit pack cannot contain the same path twice")
            seen.add(folded)
            total_bytes += params["size"]
            if total_bytes > MAX_PACK_TOTAL_BYTES:
                raise ValueError(f"edit pack exceeds the {MAX_PACK_TOTAL_BYTES // 1024} KiB total limit")
            previews.append(operation)
            inputs.append(dict(edit))
        operations = tuple(previews)
        manifest = [_operation_params(operation) for operation in operations]
        manifest_sha256 = edit_pack_manifest_sha256(manifest)
        paths = [operation.path for operation in operations]
        scope_id = edit_pack_scope_id(self.root, paths)
        parameters = {"scope_id": scope_id, "operations": manifest,
                      "manifest_sha256": manifest_sha256, "nonce": nonce}
        request = ActionRequest("workspace.files.transaction", self.root, str(self.root),
                                parameters, execution_owner="workspace_transaction")
        before_modes = []
        for operation in operations:
            current = read_file(self.root, operation.path)
            if digest(current) != _before(operation.request.parameters):
                raise ValueError(f"{operation.path} changed while the pack was being prepared")
            before_modes.append(None if current is None else current[1])
        return EditPackPreview(request, operations, tuple(inputs), tuple(before_modes),
                               scope_id, manifest_sha256, nonce)

    # ── outcome serialization ────────────────────────────────────

    @staticmethod
    def _outcome_json(outcome: ActionOutcome) -> str:
        receipt = outcome.receipt
        payload = {
            "text": outcome.text, "decision": outcome.decision, "reason": outcome.reason,
            "receipt": None if receipt is None else {
                "receipt_id": receipt.receipt_id, "action_id": receipt.action_id,
                "request_digest": receipt.request_digest, "decision": receipt.decision,
                "outcome": receipt.outcome, "result_digest": receipt.result_digest,
            },
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _recorded_outcome(record: OperationRecord) -> ActionOutcome:
        try:
            data = json.loads(record.result)
            saved = data.get("receipt")
            receipt = None
            if saved is not None:
                receipt = ActionReceipt(saved["receipt_id"], saved["action_id"],
                                        saved["request_digest"], saved["decision"],
                                        saved["outcome"], saved["result_digest"])
            return ActionOutcome(str(data["text"]), str(data["decision"]), receipt,
                                 str(data["reason"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OperationError("stored edit pack outcome is unreadable") from exc

    @staticmethod
    def _rolled_back(detail: str = "") -> ActionOutcome:
        reason = "every applied file was restored to its verified preimage"
        if detail:
            reason += f"; {detail[:180]}"
        return ActionOutcome("Edit pack rolled back; no partial pack was kept.",
                             "ERROR", None, reason)

    @staticmethod
    def _uncertain(detail: str) -> ActionOutcome:
        return ActionOutcome("Edit pack is NOT_VERIFIABLE; do not retry it blindly.",
                             "NOT_VERIFIABLE", None, detail[:300])

    def _operations(self) -> OperationJournal:
        return OperationJournal(self.root)

    def _ledger(self) -> EffectLedger:
        return EffectLedger(self.root)

    # ── recovery ─────────────────────────────────────────────────

    def _tree_state(self, preview: EditPackPreview) -> str:
        """Classify an IDLE tree as all-target, all-preimage or mixed/unknown."""
        target = preimage = True
        for operation, before_mode in zip(preview.operations, preview.before_modes):
            params = operation.request.parameters
            try:
                current = read_file(self.root, operation.path)
            except OSError:
                return "unknown"
            current_digest = digest(current)
            current_mode = None if current is None else current[1]
            after_mode = 0o644 if before_mode is None else before_mode
            if not (current_digest == params["after_sha256"] and current_mode == after_mode):
                target = False
            if not (current_digest == _before(params) and current_mode == before_mode):
                preimage = False
        if target:
            return "target"
        if preimage:
            return "preimage"
        return "unknown"

    def _recover(self, preview: EditPackPreview, record: OperationRecord,
                 ledger_status: str, operations: OperationJournal) -> ActionOutcome:
        """Finish an already-claimed operation; never start its effect again."""
        if record.phase == "receipt":
            return self._recorded_outcome(record)
        state = ledger_status
        if state == "IDLE":
            tree = self._tree_state(preview)
            state = "COMMITTED" if tree == "target" else "ROLLED_BACK" if tree == "preimage" else "UNCERTAIN"
        if state == "ROLLED_BACK":
            outcome = self._rolled_back("recovered an interrupted edit pack")
            if record.phase == "effected":
                operations.mark_receipt(record.operation_id, result=self._outcome_json(outcome),
                                        applied=record.applied, refused=record.refused)
                return outcome
            return self._uncertain("an interrupted edit pack was rolled back, but its earlier "
                                   "state was already uncertain; inspect the action journal")
        if state == "COMMITTED":
            detail = ("edit pack files are committed, but the final action/operation receipt "
                      "was lost; inspect files and the action journal instead of retrying")
            if record.phase != "uncertain":
                operations.mark_uncertain(record.operation_id, detail)
            return self._uncertain(detail)
        detail = ("edit pack recovery is UNCERTAIN: at least one file matches neither its "
                  "preimage nor its target, or rollback could not be verified")
        if record.phase != "uncertain":
            operations.mark_uncertain(record.operation_id, detail)
        return self._uncertain(detail)

    # ── authorization and application ────────────────────────────

    def _authorize(self, request: ActionRequest, approval: ActionApproval | None) -> str | None:
        try:
            authority, decision = self.gate.authorize(
                request, approvals=self.approvals, approval=approval)
        except Exception:
            return "authorization evaluation failed"
        if authority.allowed and decision.allowed:
            return None
        if not authority.allowed:
            return authority.reason[:300]
        return "; ".join(f"{item.name}: {item.reason}" for item in decision.checks
                         if not item.passed)[:300]

    @staticmethod
    def _checkpoint(crash_at: str | None, step: str) -> None:
        if crash_at == step:
            raise CrashInjected(step)

    def apply(self, preview: EditPackPreview, approval: ActionApproval | None,
              *, crash_at: str | None = None) -> ActionOutcome:
        if not isinstance(preview, EditPackPreview):
            return ActionOutcome("Edit pack denied.", "DENY", None, "preview has the wrong type")
        operations = self._operations()
        book = self._ledger()
        operation_id = preview.operation_id
        try:
            with book.exclusive():
                record = operations.lookup(operation_id)
                if record is not None and record.phase == "receipt":
                    return self._recorded_outcome(record)
                try:
                    ledger_status = book.reconcile()
                except LedgerDenied:
                    ledger_status = "UNCERTAIN"
                if record is not None:
                    return self._recover(preview, record, ledger_status, operations)
                if ledger_status == "UNCERTAIN":
                    return self._uncertain("a previous workspace effect is uncertain; no new pack started")
                try:
                    fresh = self.preview(list(preview.inputs), nonce=preview.nonce)
                except (OSError, ValueError) as exc:
                    return ActionOutcome("Edit pack denied.", "DENY", None,
                                         f"files changed since review: {str(exc)[:200]}")
                if fresh.request.digest != preview.request.digest:
                    return ActionOutcome("Edit pack denied.", "DENY", None,
                                         "the manifest changed since it was reviewed; review it again")
                paths = preview.paths
                current_states = []
                churn = 0
                for operation in preview.operations:
                    params = operation.request.parameters
                    current = read_file(self.root, operation.path)
                    if digest(current) != _before(params):
                        return ActionOutcome("Edit pack denied.", "DENY", None,
                                             f"preimage changed for {operation.path}; nothing was written")
                    current_states.append(current)
                    churn += (0 if current is None else len(current[0])) + params["size"]
                reservation = book.reserve(EffectCost(paths, 0, churn))
                self._checkpoint(crash_at, "after-reserve")
                denied = self._authorize(preview.request, approval)
                if denied is not None:
                    book.abort(reservation)
                    return ActionOutcome("Edit pack denied.", "DENY", None, denied)
                started = False
                turn = None
                try:
                    plan = []
                    for operation, current in zip(preview.operations, current_states):
                        params = operation.request.parameters
                        if current is not None:
                            book.backup_file(reservation, operation.path, current[0])
                        before_mode = None if current is None else current[1]
                        after_mode = 0o644 if before_mode is None else before_mode
                        plan.append({
                            "path": operation.path,
                            "kind": "add" if current is None else "modify",
                            "preimage": _before(params), "target": params["after_sha256"],
                            "churn": (0 if current is None else len(current[0])) + params["size"],
                            "preimage_mode": before_mode, "target_mode": after_mode,
                            "typed": True, "mode_checked": True,
                        })
                    turn = self.writer._turn_capture(
                        *(Path(operation.request.target) for operation in preview.operations))
                    self._checkpoint(crash_at, "after-backup")
                    book.store_plan(reservation, plan)
                    self._checkpoint(crash_at, "after-plan")
                    record, claimed = operations.claim_effect(
                        operation_id, kind="promote", applied=list(paths), refused=[])
                    self._checkpoint(crash_at, "after-operation-claim")
                    if not claimed:
                        book.abort(reservation)
                        if record.phase == "receipt":
                            return self._recorded_outcome(record)
                        return self._recover(preview, record, book.reconcile(), operations)
                    for index, (operation, current) in enumerate(zip(preview.operations, current_states)):
                        params = operation.request.parameters
                        self._checkpoint(crash_at, f"before-apply:{index}")
                        started = True
                        book.mark_applying(reservation, operation.path)
                        self._checkpoint(crash_at, f"after-mark-applying:{index}")
                        payload = operation.content.encode("utf-8")
                        if _sha(payload) != params["after_sha256"]:
                            raise ValueError("reviewed payload does not match the manifest")
                        apply_file(self.root, operation.path, payload,
                                   expected=_before(params),
                                   expected_mode=None if current is None else current[1],
                                   mode=0o644 if current is None else current[1],
                                   create_parents=False)
                        self._checkpoint(crash_at, f"after-apply:{index}")
                        written = read_file(self.root, operation.path)
                        if digest(written) != params["after_sha256"]:
                            raise ValueError("written content does not match the manifest")
                        book.mark_applied(reservation, operation.path)
                        self.writer._turn_note(turn, self.root, Path(operation.request.target),
                                               params["after_sha256"])
                        self._checkpoint(crash_at, f"after-mark-applied:{index}")
                    self._checkpoint(crash_at, "before-commit")
                    book.commit(reservation, applied_paths=paths, deletes=0, churn_bytes=churn)
                    self._checkpoint(crash_at, "after-ledger-commit")
                except CrashInjected:
                    raise
                except (OSError, ValueError, LedgerDenied, OperationError) as exc:
                    if not started:
                        try:
                            book.abort(reservation)
                        except LedgerDenied:
                            pass
                        return ActionOutcome("Edit pack denied before any file changed.",
                                             "DENY", None,
                                             f"durable preparation failed: {str(exc)[:220]}")
                    try:
                        settled = book.reconcile()
                    except LedgerDenied:
                        settled = "UNCERTAIN"
                    if settled == "ROLLED_BACK":
                        outcome = self._rolled_back(str(exc))
                        operations.mark_receipt(operation_id, result=self._outcome_json(outcome),
                                                applied=list(paths), refused=[])
                        return outcome
                    if settled == "COMMITTED":
                        detail = ("the pack committed while an error was being handled, but its "
                                  "receipt was not completed; inspect instead of retrying")
                        operations.mark_uncertain(operation_id, detail)
                        return self._uncertain(detail)
                    detail = f"rollback could not be verified after {type(exc).__name__}: {str(exc)[:180]}"
                    operations.mark_uncertain(operation_id, detail)
                    return self._uncertain(detail)
                result = json.dumps({
                    "scope_id": preview.scope_id, "manifest_sha256": preview.manifest_sha256,
                    "operations": [{"path": operation.path,
                                    "after_sha256": operation.request.parameters["after_sha256"]}
                                   for operation in preview.operations],
                }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                receipt = ActionReceipt("rcpt_txn_" + operation_id, TRANSACTION_ACTION,
                                        preview.request.digest, "ALLOW", "SUCCESS", _sha(result.encode()))
                if not self.gate.persist_receipt(preview.request, receipt):
                    detail = "edit pack committed, but its action receipt could not be journaled"
                    operations.mark_uncertain(operation_id, detail)
                    return self._uncertain(detail)
                self._checkpoint(crash_at, "after-action-receipt")
                outcome = ActionOutcome(f"Applied edit pack · {len(paths)} file(s)", "ALLOW",
                                        receipt, "all files applied and verified; manifest committed")
                operations.mark_receipt(operation_id, result=self._outcome_json(outcome),
                                        applied=list(paths), refused=[])
                self._checkpoint(crash_at, "after-operation-receipt")
                return outcome
        except CrashInjected:
            raise
        except OperationError as exc:
            return self._uncertain(f"operation journal is unavailable: {str(exc)[:220]}")
        except LedgerDenied as exc:
            if exc.effect_state == "uncertain":
                return self._uncertain(str(exc))
            return ActionOutcome("Edit pack denied.", "DENY", None, str(exc)[:300])
        except OSError as exc:
            return self._uncertain(f"edit pack filesystem state could not be verified: {str(exc)[:220]}")


__all__ = ["EDIT_PACK_TOOL", "EDIT_PACK_TOOL_NAME", "EditPackPreview",
           "WorkspaceTransactionOwner"]
