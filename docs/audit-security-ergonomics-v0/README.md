# ISyCode — Security Without Friction

## Architectural Audit & Remediation Design — V0

**Date:** 2026-10-15
**Commit:** `b76377d` (main)
**Mode:** RESEARCH / AUDIT / DESIGN — implementation not authorized
**Scope:** TUI layer, async lifecycle, state persistence, menu dispatch, security ergonomics, performance, external comparison

---

## Files

| File | Contents |
|---|---|
| `01-executive-summary.md` | Diagnosis, strengths, defects, hypotheses |
| `02-current-architecture.md` | Component map, dependency graph, authority/execution flows |
| `03-verified-findings.md` | Reproducible findings with ID, severity, evidence, root cause |
| `04-hypotheses.md` | Unproven hypotheses and falsification experiments |
| `05-security-invariant-matrix.md` | Invariant → implementation → evidence → risk → preservation test |
| `06-remediation-alternatives.md` | Alternatives A (minimal), B (incremental), C (modular restructure) |
| `07-migration-sequence.md` | Recommended phased migration |
| `08-acceptance-matrix.md` | Functional, security, performance, UX, regression tests |
| `09-stop-rollback-conditions.md` | Conditions that mandate stopping a migration |
| `10-open-questions.md` | Decisions requiring human validation |

---

## Methodology

All findings were verified against the repository at commit `b76377d` on 2026-10-15.
Line numbers are exact as of that commit. Counts were produced by grep/wc/AST
inspection, not estimated. Performance measurements were run on the developer
machine (Ubuntu 24.04, Python 3.12, Textual 8.2.8) with isolated temp state
directories — no real user state was touched.

External comparisons cite open-source repositories (Codex CLI, OpenCode) and
official documentation (Claude Code). Claude Code internals are marked LIMITED
EVIDENCE (closed source).
