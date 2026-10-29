# 01 — Executive Summary

**Date:** 2026-10-15 · **Commit:** `b76377d` · **Status:** evidence complete, implementation not authorized

## Diagnosis

ISyCode's security architecture is genuinely strong — stronger than any
consumer TUI we compared against. The combination of deny-by-default grants,
per-workspace authority, hash-chained audit journal, one-use digest-bound
approvals, and refuse-first modal focus has no equivalent in Codex CLI,
Claude Code, or OpenCode. These properties should be preserved at all costs.

The friction the user experiences does NOT come from the security checks
themselves. Our measurements show Sentinel evaluation costs ~2.0 ms per
action — 20% of a full authorize call. The dominant cost is journal
persistence (~7.9 ms, 80%). More importantly, the *perceived* friction comes
from three structural problems that are orthogonal to security:

1. **No readiness state machine.** The UI is interactive before any subsystem
   is loaded. Seven background tasks fire during startup with no explicit
   readiness signal. Tests must poll with `pilot.pause()` loops (632 call
   sites). Late startup work writes to the audit journal after tests capture
   baselines, causing flaky assertions. Two rail placeholders actively lie to
   the user ("Starting local mobile host…" when the host is never started;
   "None configured" for MCP while the catalog is still loading).

2. **Monolithic TUI with cyclic mixin coupling.** `tui.py` is 3,541 lines with
   118 methods. Nine mixins add 8,444 more. Seven bidirectional coupling pairs
   exist between mixins, plus a directed cycle through six of nine. Cross-mixin
   attribute access is pervasive (MenuMixin reads 68 external `self.*` names).
   This makes every feature change a cross-cutting concern and every test a
   timing gamble.

3. **Dispersed state with no single resolver.** 42 environment variables are
   read across 105 sites. State lives in `ISYCODE_STATE_HOME`, `XDG_STATE_HOME`,
   `XDG_CONFIG_HOME`, `~/.local/state/isycode/`, `.isycode/` inside workspaces,
   `UserDefaultsStore`, `WorkspaceTrust`, `ActionApprovalStore`, and
   module-level singletons. Four tests must monkeypatch `HOME` to avoid
   touching the real user. Two state roots can disagree (split-brain between
   `state_root()` and explicit `state_directory` parameters).

## Strengths (preserve these)

| Strength | Evidence |
|---|---|
| Deny-by-default with explicit effect classification | `action_runtime.py:1869-1908` — every action classified before authority evaluation |
| Hash-chained audit journal with segment sealing | `action_audit.py:73-132` — LOCK_EX writes, O_NOFOLLOW reads, chain verification |
| One-use digest-bound approvals | `approvals.py` — consumed on use, TTL 1-120s, bound to request+result digests |
| Refuse-first modal focus | `tui_screens_approval.py:109-112` — inherited by all 20 ApprovalScreen subclasses |
| No unsandboxed fallback | `tui_app_authority.py:219,224` — honest copy repeated in unavailable case |
| Decline is remembered | `workspace_trust.py:109-110` — saying "no" is not a punishment |
| Scope sentences that say what is NOT granted | `ContextAccessScreen:145-146` — "This does not allow edits, commands, secrets, or any other file." |
| Anti-drift refusal as guarantee | `WriteApprovalScreen:263` — "If the file changes before it is applied, the change is refused." |

## Defects (verified)

| ID | Severity | Summary |
|---|---|---|
| F-01 | HIGH | No readiness state machine; UI interactive before subsystems load |
| F-02 | HIGH | 7 fire-and-forget startup tasks; 5 can exit the app on uncaught exception |
| F-03 | HIGH | Journal verify-under-write race: 30% JOURNAL_INVALID rate under concurrent write |
| F-04 | MEDIUM | Late startup journal writes pollute test baselines |
| F-05 | MEDIUM | 7 bidirectional mixin coupling pairs + 6-mixin directed cycle |
| F-06 | MEDIUM | Two rail placeholders lie to the user during loading |
| F-07 | MEDIUM | DENY and operational errors are visually indistinguishable |
| F-08 | MEDIUM | Only 3/7 approval model elements are structural; OWNER and DURATION routinely missing |
| F-09 | LOW | Stringly-typed menu dispatch (118 MENU_DISPATCH entries, 24 mode strings) |
| F-10 | LOW | Dispersed state: 42 env vars, no single path resolver |
| F-11 | LOW | Startup ordering inconsistency: vault key invisible to QuickStart probe |
| F-12 | LOW | Dead/duplicated code in MemoryConfirmScreen |

## Hypotheses (unproven)

| ID | Hypothesis | Status |
|---|---|---|
| H1 | Startup async causes test flakiness | STRONGLY SUPPORTED — but not yet falsified under explicit readiness |
| H2 | Security dominates latency | REFUTED — Sentinel is 20% of authorize; journal write is 80% |
| H3 | Dispersed state causes interference | SUPPORTED — env fallbacks to real HOME, split-brain roots |
| H4 | Multiple inheritance causes coupling | SUPPORTED — 7 cyclic pairs verified |
| H5 | Stringly-typed menus cause errors | SUPPORTED — 118 string entries, unknown kinds silently blocked |

## Key measurement

```
Authorization latency (500 iterations, isolated temp state):
  authority.evaluate (preview):     1.919 ms/op
  sentinel.evaluate (no journal):   2.027 ms/op   (20.4% of full)
  full gate.authorize (w/ journal): 9.921 ms/op
  journal write cost (diff):        7.894 ms/op   (79.6% of full)

Startup latency (3 cold runs):
  mount + first pause:              946-1029 ms

Journal verify under concurrent write (200 attempts):
  PASS:              140  (70%)
  JOURNAL_INVALID:    60  (30%)
```

## Bottom line

The question is not "how do we simplify ISyCode?" — the security model is
the product's differentiator and should not be weakened. The question is
"how do we reduce accidental complexity without reducing security guarantees?"
The three structural problems (readiness, coupling, state) are all fixable
without touching Authority, Sentinel, Owners, Grants, or the Journal.
