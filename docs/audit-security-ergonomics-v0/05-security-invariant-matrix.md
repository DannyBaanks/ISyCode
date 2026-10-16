# 05 — Security Invariant Matrix

**Commit:** `b76377d` · **Date:** 2026-10-15
Each invariant is mapped to its implementation, evidence, risk, and preservation test.

---

## I-01 · Deny by default

**Statement:** Every action is denied unless an explicit grant or approval allows it.

**Implementation:**
- `workspace_authority.py:45-120` — `WorkspaceAuthority.evaluate()` starts with `allowed=False`
- `action_runtime.py:1869-1908` — `ProductActionGate.authorize()` calls `authority.evaluate()` before any owner execution
- No code path reaches `owner.execute()` without passing through `authorize()`

**Evidence:**
- 51/84 catalog actions are `approval_required=True` (`action_catalog.py`)
- 20 ApprovalScreen subclasses for approval flows
- `WorkspaceAuthority` has no method that returns `allowed=True` without checking grants or approvals

**Risk:** A refactor could introduce a bypass path (e.g., a new owner that calls `execute()` directly).

**Preservation test:** `tests/security/test_authority_deny_by_default.py` — assert that a fresh `WorkspaceAuthority` denies every catalog action.

---

## I-02 · No unsandboxed fallback

**Statement:** If a sandbox/owner is unavailable, the action is denied — never executed unsandboxed.

**Implementation:**
- `tui_app_authority.py:219,224` — honest copy repeated in unavailable case
- `action_runtime.py:1909-1915` — if `owner` is `None`, return `ActionOutcome(reason="no execution owner")`

**Evidence:**
- `ChatSessionOwner` failure in `_startup_workspace` (`tui.py:732-735`) sets `_chat_session_owner = None`; subsequent chat actions return "Chat unavailable — session owner failed to initialize"
- No code path constructs an owner outside the approved list

**Risk:** A new owner type could be registered without sandbox enforcement.

**Preservation test:** `tests/security/test_no_unsandboxed_fallback.py` — assert that removing all owners results in deny for all actions.

---

## I-03 · Refuse-first modal focus

**Statement:** Every approval modal focuses the "Refuse" button by default, not "Approve".

**Implementation:**
- `tui_screens_approval.py:109-112` — `on_mount` sets `self.query_one("#refuse", Button).focus()`
- All 20 ApprovalScreen subclasses inherit this behavior

**Evidence:**
- `DECISION_CSS:32` — refuse button uses `variant="error"` (though CSS collapses it to look like warning/primary — F-08)
- No subclass overrides `on_mount` to focus approve

**Risk:** A new approval screen could override `on_mount` and focus approve.

**Preservation test:** `tests/security/test_refuse_first_focus.py` — mount each ApprovalScreen subclass, assert `query_one("#refuse").has_focus`.

---

## I-04 · One-use digest-bound approvals

**Statement:** Approvals are single-use, bound to a specific request+result digest, and expire after TTL.

**Implementation:**
- `approvals.py:45-80` — `ActionApprovalStore` stores `(request_digest, result_digest, expires_at)`
- `approvals.py:81-95` — `consume()` removes the approval after use; returns `None` if already consumed
- `approvals.py:96-100` — `is_expired()` checks TTL (1-120 seconds)

**Evidence:**
- `ActionApprovalStore` is in-memory only (no persistence) — corrected from earlier assumption
- `WorkspaceAuthority.evaluate()` calls `approvals.consume()` on match

**Risk:** A refactor could make approvals reusable (e.g., caching the result).

**Preservation test:** `tests/security/test_one_use_approvals.py` — approve an action, execute it, attempt to execute again → deny.

---

## I-05 · Hash-chained audit journal

**Statement:** Every decision and receipt is appended to a hash-chained journal; tampering breaks the chain.

**Implementation:**
- `action_audit.py:73-132` — `ActionAuditJournal` with `record_decision()` and `record_receipt()`
- `action_audit.py:133-160` — `verify()` walks the chain, checks each record's `prev_hash`
- `action_audit.py:446-448` — writes use `LOCK_EX` (exclusive lock)

**Evidence:**
- Journal files: `actions-{sha256(workspace_root)[:32]}.jsonl` under `state_root()`
- Segment sealing: `action_audit.py:161-180` — `seal_segment()` appends a seal record with chain hash

**Risk:** Reader does not hold `LOCK_SH` (F-03) — concurrent verify can produce false JOURNAL_INVALID. Also, no code path re-verifies after startup.

**Preservation test:** `tests/security/test_journal_hash_chain.py` — append 10 records, tamper with record 5, assert `verify()` detects break.

---

## I-06 · Effect classification before authority

**Statement:** Every action is classified (read/write/exec/secret/network) before authority evaluation.

**Implementation:**
- `action_runtime.py:1869-1908` — `effect_policy.stamp(request)` runs before `authority.evaluate()`
- `effect_policy.py` — classification rules per action ID

**Evidence:**
- 84 catalog actions each have an `effect` field (`action_catalog.py`)
- `ActionRequest` includes `effect` field stamped by `effect_policy`

**Risk:** A new action could bypass classification (e.g., hardcoded effect).

**Preservation test:** `tests/security/test_effect_classification.py` — for each catalog action, assert `request.effect` matches the catalog definition.

---

## I-07 · Scope sentences say what is NOT granted

**Statement:** Approval modals must explicitly state what is NOT granted, not just what is.

**Implementation:**
- `tui_screens_approval.py:145-146` — `ContextAccessScreen` body includes "This does not allow edits, commands, secrets, or any other file."
- `tui_screens_approval.py:263` — `WriteApprovalScreen` body includes "If the file changes before it is applied, the change is refused."

**Evidence:**
- Only 2 of 20 ApprovalScreen subclasses have explicit "not granted" language (F-08)

**Risk:** Most approval screens omit "not granted" language; user may overestimate scope.

**Preservation test:** `tests/security/test_scope_negation.py` — mount each ApprovalScreen, assert body contains "not" or "does not" or "refuses".

---

## I-08 · Decline is remembered

**Statement:** Saying "no" to an approval is stored and respected in future sessions.

**Implementation:**
- `workspace_trust.py:109-110` — `WorkspaceTrust.record_decline()` stores decline with timestamp
- `workspace_authority.py:121-140` — `evaluate()` checks `trust.is_declined()` before granting

**Evidence:**
- `WorkspaceTrust` records are per-workspace (hash of workspace root)
- Decline has no expiry (permanent until user manually clears)

**Risk:** A refactor could ignore declines (e.g., treating them as dismissals).

**Preservation test:** `tests/security/test_decline_remembered.py` — decline an approval, restart app, assert same action is still denied.

---

## I-09 · Anti-drift refusal

**Statement:** If a file changes between approval and execution, the write is refused.

**Implementation:**
- `tui_screens_approval.py:263` — `WriteApprovalScreen` body: "If the file changes before it is applied, the change is refused."
- `action_runtime.py:1916-1925` — before `owner.execute()`, re-reads file, compares digest to approved digest

**Evidence:**
- `WriteApprovalScreen` stores `file_digest` at approval time
- `ProductActionGate.authorize()` checks `file_digest` matches current file content

**Risk:** A refactor could skip the digest check (e.g., trusting the approval).

**Preservation test:** `tests/security/test_anti_drift.py` — approve write, modify file, execute → deny.

---

## I-10 · DENY is never converted to ALLOW by UI failures

**Statement:** If the UI fails to render an approval modal (or any security-relevant screen), the action is denied — never silently allowed.

**Implementation:**
- `tui_app_authority.py:219,224` — if modal fails to mount, return `ActionOutcome(reason="approval modal failed")`
- `action_runtime.py:1909-1915` — if `owner` is `None`, deny

**Evidence:**
- No code path converts a modal failure to `allowed=True`

**Risk:** A refactor could catch modal exceptions and proceed with a default (e.g., auto-approve).

**Preservation test:** `tests/security/test_deny_on_ui_failure.py` — mock modal mount to raise, assert action is denied.

---

## I-11 · No implicit permissions from visual state

**Statement:** Visual state (e.g., a rail indicator showing "connected") does not grant permissions.

**Implementation:**
- All permissions flow through `WorkspaceAuthority.evaluate()` — visual state is display-only
- Rail indicators (`tui_app_rail.py`) read from `WorkspaceAuthority` / `Sentinel` but never write

**Evidence:**
- No code path where a rail click or visual toggle changes `allowed` without going through `authorize()`

**Risk:** A refactor could couple visual state to permissions (e.g., "if rail shows connected, skip sandbox check").

**Preservation test:** `tests/security/test_visual_state_no_permissions.py` — click every rail element, assert no action is executed without `authorize()`.

---

## I-12 · Workspace boundaries are not weakened

**Statement:** Actions are scoped to a workspace root; cross-workspace access requires explicit grants.

**Implementation:**
- `action_runtime.py:1870-1875` — `ActionRequest` includes `workspace_root`
- `workspace_authority.py:45-120` — grants are keyed by workspace root hash
- `approvals.py` — approvals are bound to workspace root

**Evidence:**
- `WorkspaceAuthority` has no method to evaluate an action for a different workspace root
- `ActionAuditJournal` is per-workspace (`actions-{sha256(root)[:32]}.jsonl`)

**Risk:** A refactor could weaken workspace scoping (e.g., sharing grants across workspaces).

**Preservation test:** `tests/security/test_workspace_boundaries.py` — create two workspaces, grant access in A, assert B still denies.

---

## Summary

| ID | Invariant | Risk Level | Preservation Test Exists? |
|---|---|---|---|
| I-01 | Deny by default | CRITICAL | Yes |
| I-02 | No unsandboxed fallback | CRITICAL | Yes |
| I-03 | Refuse-first modal focus | HIGH | Yes |
| I-04 | One-use digest-bound approvals | CRITICAL | Yes |
| I-05 | Hash-chained audit journal | CRITICAL | Yes (but reader race F-03) |
| I-06 | Effect classification before authority | HIGH | Yes |
| I-07 | Scope sentences say what is NOT granted | MEDIUM | Partial (2/20 screens) |
| I-08 | Decline is remembered | HIGH | Yes |
| I-09 | Anti-drift refusal | HIGH | Yes |
| I-10 | DENY never converted to ALLOW by UI failures | CRITICAL | Yes |
| I-11 | No implicit permissions from visual state | HIGH | Yes |
| I-12 | Workspace boundaries not weakened | CRITICAL | Yes |

**Critical invariants (I-01, I-02, I-04, I-05, I-10, I-12) must be preserved in all remediation alternatives.**
