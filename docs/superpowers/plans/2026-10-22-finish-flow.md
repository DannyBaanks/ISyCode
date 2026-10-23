# Finish Flow implementation

Goal: complete the existing ADR 0010 and MF implementation from
`b515b44849415b6a977f17e2ec3baf7bfec58424` without changing Classic/Security contracts.
User authorized completing the previously reviewed missing work on 2026-10-22.
Execution: native, in `codex/finish-flow-mode`, preserving the original checkout.

- [x] Establish the existing Flow baseline (34 tests passed).
- [x] Add failing tests for three-mode onboarding and Settings, per-chat-turn
  recovery, restart/undo and storage-failure refusal; implement those paths.
- [x] Reproduce and fix lost cancellation recovery, staged human work being
  attributed to Flow, later chmod being overwritten and session trust surviving
  a switch. Keep explicit permissions, owner execution and receipts.
- [x] Add real Flow sandbox checks for shell, secrets, host environment,
  symlinks/hardlinks, external writes and network. Mask external hardlink reads
  in Flow while retaining the Classic masking contract.
- [x] Add translations and keyboard/size coverage for en/es/zh at 80×24,
  100×30 and 140×40; inspect rendered screenshots.
- [x] Teach the gate validator the seven GF cases and regenerate M15 coverage.
- [ ] Run final regression, record SHA-bound evidence and prepare review.

Independent acceptance remains necessary for GF; do not approve the gate on
behalf of the reviewer or declare native platforms that were not measured.
