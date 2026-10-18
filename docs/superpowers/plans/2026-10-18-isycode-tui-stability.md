# ISyCode TUI Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Status:** Approved for direct execution by the user on 2026-10-18, including the three reported chat/OAuth fixes below. Gmail Hive remains deferred.

**Goal:** Resolve demonstrated TUI reliability risks, preserve completed chat turns across later responses, make the signed-in ChatGPT model selector usable, and make the official OAuth link actionable, while preserving security gates and truthful evidence.

**Architecture:** Establish a clean baseline first. Diagnose the Sentinel journal startup worker and prior test flake without assuming a product defect. Reproduce the reported multi-turn overwrite and OAuth UX issues with offline TUI tests, fix only their owning flows, then profile synthetic content and reasoning streams without a live provider and optimize only if measurement shows material UI cost.

**Tech Stack:** Python 3.10/3.12, pytest, Textual 8.2.8, GitHub Actions Linux and Windows jobs; no new runtime dependencies.

**Spec:** [ISyCode Stability and Gmail Hive design spec](../specs/2026-10-18-isycode-stability-and-gmail-hive-design.md), approved 2026-10-18.

## Global Constraints

- Stability ships before Gmail Hive; this plan does not implement Gmail OAuth or remote polling.
- ChatGPT subscription changes are limited to the existing provider's post-login model selection and login-link presentation. Do not use the user's live account in automated tests, add credential storage, broaden OAuth scopes, or send a real sign-in request.
- Change production code only when a reproducible failure or profile supports the change.
- Preserve all prior user and assistant messages, full streamed/reasoning text, selectable content, cancellation behavior, and Authority/ISySentinel/one-use approval checks.
- Never select a ChatGPT model silently; keep `auto` until the user explicitly chooses an available model.
- Do not weaken assertions, rewrite historical evidence, manufacture gate approvals, or mark a gate complete without fresh proof.
- Refresh roadmap audit metadata only after a real re-audit; this work does not complete the roadmap audit.
- Record exact command, environment, result, and changed artifact hash in the result report.

## Review Focus

1. **Consecutive chat turns:** a completed assistant widget must never be reused as the next turn's streaming widget; prior user/assistant/tool output remains intact. Separate actual replacement from expected scroll-offscreen behavior.
2. **OAuth model selection:** ChatGPT subscription choices come from the authenticated account catalog or a clearly labeled supported catalog; `auto` is never silently replaced.
3. **OAuth link activation:** the long URL remains actionable when wrapped; only HTTPS URLs on approved ChatGPT auth hosts may open.
4. **Journal startup overlap on Windows:** do not read the journal or its lock file while the `sentinel-journal` worker is still verifying it.
5. **TUI teardown with a pending worker:** app shutdown must leave no active worker or unsafe journal access.
6. **Native-login cancellation:** the private challenge code may not enter chat history or persisted state.
7. **Fragmented or partial streams:** coalescing rendering must not lose, duplicate, or expose failed-step output, and steering must preserve its existing semantics.
8. **Large reasoning and content streams:** the UI must remain responsive, preserve the complete selectable result, and keep updates working when the active lane is off screen.

---

### Task 1: Re-establish the failure baseline

**Files:**
- Create: `docs/superpowers/results/2026-10-18-isycode-stability-baseline.md`
- Test: `tests/test_chatgpt_auth_tui.py::test_native_subscription_login_and_cancel_never_save_challenge`
- Test: `tests/test_ux_polish_and_resume.py::test_area_f_interrupted_turn_capture_and_resume`

**Interfaces:**
- Consumes: current `main` baseline and the existing `test-windows` CI job.
- Produces: a timestamped report that separates reproduced failures from historical observations.

- [ ] **Step 1: Capture the exact baseline.** Record the checked-out commit, OS, Python, pytest, Textual version, and historical run [38974723145](https://github.com/DannyBaanks/ISyCode/actions/runs/38974723145) with its PermissionError. Do not label the inferred worker race as the cause.
- [ ] **Step 2: Run both focused tests on the local host.**

  Run: `python -m pytest -q tests/test_chatgpt_auth_tui.py::test_native_subscription_login_and_cancel_never_save_challenge tests/test_ux_polish_and_resume.py::test_area_f_interrupted_turn_capture_and_resume`

  Expected: record the real exit status and full output. A pass here does not clear the historical Windows failure.

- [ ] **Step 3: Stress the previously intermittent resume test.**

  Run:
  ```bash
  for run in $(seq 1 20); do
    python -m pytest -q tests/test_ux_polish_and_resume.py::test_area_f_interrupted_turn_capture_and_resume || exit 1
  done
  ```

  Expected: either 20/20 passes or a saved failing iteration and traceback. Do not add `pytest-repeat` or another dependency for this check.

- [ ] **Step 4: Record the test-windows CI result.** On a Windows runner, execute the focused parametrized login test and preserve the run URL/output. If a Windows runner is unavailable before implementation, mark Windows reproduction `NOT_DEMONSTRATED`; do not infer success from Linux.
- [ ] **Step 5: Save the report and verify it.** Include raw command output or a stable reference to it, exact exit codes, environment, and SHA-256. No product files change in this task.

### Task 2: Fix the journal race only if evidence confirms it

**Files:**
- Modify: `tests/test_chatgpt_auth_tui.py`
- Possible, only if a product lifecycle defect is proven: `src/isycode/tui.py`, `src/isycode/tui_app_rail.py`, or `src/isycode/action_audit.py`
- Test, only if a product lifecycle defect is proven: `tests/test_tui_startup.py`

**Interfaces:**
- Consumes: Task 1's reproduction and the existing `sentinel-journal` worker group.
- Produces: deterministic test synchronization or a narrow, regression-tested product fix; no change when the cause is not demonstrated.

- [ ] **Step 1: Make the overlap reproducible.** If the failure reproduces, instrument the existing test to capture whether the `sentinel-journal` worker is active while the test walks and reads `tmp_path/state`. Preserve the exact failing path and exception.
- [ ] **Step 2: If the conflict is only in test timing, synchronize the test.** Use the established Textual pattern `await app.workers.wait_for_complete(workers)` for workers selected by `worker.group == "sentinel-journal"` before scanning persisted state. Keep the challenge-secret assertions intact.
- [ ] **Step 3: If production lifecycle behavior is at fault, add a focused failing test first.** Pin the observed start/stop/lock contract in `tests/test_tui_startup.py`; change only the owning source method among `TUIApp.on_mount`, `_load_sentinel_journal`, or journal verification. Do not relax journal locking or failure-closed behavior.
- [ ] **Step 4: Run the focused regression on the affected platform.**

  Run: `python -m pytest -q tests/test_chatgpt_auth_tui.py::test_native_subscription_login_and_cancel_never_save_challenge tests/test_tui_startup.py`

  Expected: PASS with the original secret-absence checks unchanged. If Task 1 did not reproduce the issue, do not add speculative synchronization or production code; record `NOT_DEMONSTRATED` and close this task as investigation-only.

- [ ] **Step 5: Run the Windows focused check.** Use CI's `test-windows` runner after the regression change. Expected: both parametrized cancellation states pass; a Linux pass is not a substitute.

### Task 3: Preserve completed assistant messages across turns

**Files:**
- Test: `tests/test_chat_sequence.py`
- Possible, only if the regression reproduces: `src/isycode/tui_app_chat.py` or the owning session method

**Interfaces:**
- Consumes: the existing `TUIApp._run_chat()` streaming path and active `ConversationLane`.
- Produces: a regression proving two completed assistant answers remain separately visible and unchanged after a later turn; a minimal fix if the lane reuses a completed stream widget.

- [ ] **Step 1: Write a two-turn regression first.** Use an offline fake provider returning distinct answers for sequential user turns, mount both prompts through the normal submission path, then assert both prompts and both answers remain in the mounted chat and in `_history`.
- [ ] **Step 2: Run the regression before changing production code.** Expected: if the issue reproduces, the first answer's widget is updated to the second answer or the prior turn is otherwise missing. Record the failure. If the test passes, inspect scroll position and record content loss as `NOT_REPRODUCED`; do not alter normal tail-follow behavior just to keep all history within a 24-row viewport.
- [ ] **Step 3: If reproduced, make the smallest lifecycle fix.** Ensure only an unfinished response owns `lane.stream_widget`; release that reference once the no-tool final response is committed, while preserving tool-followup, interruption, retry, and steering paths.
- [ ] **Step 4: Verify adjacent behavior.** Run `python -m pytest -q tests/test_chat_sequence.py tests/test_ux_polish_and_resume.py::test_area_f_interrupted_turn_capture_and_resume`.
- [ ] **Step 5: Inspect the diff and commit only exact chat source/test paths.** If no source change is justified, retain a test only if it covers a distinct contract not already protected; otherwise record the investigation in the baseline report.

### Task 4: Make ChatGPT subscription model selection explicit

**Files:**
- Test: `tests/test_chatgpt_auth_tui.py`
- Test: `tests/test_model_button.py`
- Possible: `src/isycode/tui_app_providers.py`, `src/isycode/tui.py`, or the owning model-selection module

**Interfaces:**
- Consumes: the existing ChatGPT OAuth completion path, active model control, and provider/account catalog returned through the existing authority owner.
- Produces: a visible, tested route from a signed-in ChatGPT subscription to an explicit model choice without changing the default automatically.

- [ ] **Step 1: Inspect the existing post-OAuth provider-selection and model-catalog path.** Confirm whether the active model button exposes model choices for `chatgpt`, and whether `Provider.models()` is backed by the authenticated Codex endpoint. Do not make a live request.
- [ ] **Step 2: Write a failing offline TUI test.** Simulate OAuth success with a fake connector, open the visible model control, and assert the user can reach a catalog-backed ChatGPT model choice while `auto` stays active until Enter selects one.
- [ ] **Step 3: Run the test before implementation.** Expected: the current route either offers only provider choices or cannot present/select ChatGPT account models. Preserve the failure output.
- [ ] **Step 4: Implement the smallest route/catalog fix.** Keep provider switching separate from model selection; send model-list requests only through existing `ProviderNetworkOwner` and Authority grants. If the authenticated endpoint supplies no catalog, show that state clearly and use only an explicitly labeled supported catalog; never invent IDs or claim account availability.
- [ ] **Step 5: Run focused auth/model tests.** Run `python -m pytest -q tests/test_chatgpt_auth_tui.py tests/test_model_button.py tests/test_resolved_chat_model.py tests/test_model_availability.py`.
- [ ] **Step 6: Verify opening, choosing, cancellation, focus return, and default `auto`; commit only exact source/test paths.**

### Task 5: Make the ChatGPT OAuth URL actionable when wrapped

**Files:**
- Test: `tests/test_chatgpt_auth_tui.py`
- Modify, only as needed: `src/isycode/provider_auth_screens.py`
- Possible: the narrow link-opening owner used by the current Textual UI

**Interfaces:**
- Consumes: the challenge URL returned by the existing approved ChatGPT connector.
- Produces: a readable, mouse/keyboard actionable official sign-in link that remains usable at 80×24, without exposing it to conversation or persistent state.

- [ ] **Step 1: Add a failing screen test** with a long HTTPS URL on `auth.openai.com`; assert the rendered control targets the exact URL and remains activatable after wrapping at 80×24.
- [ ] **Step 2: Run the test and confirm it fails** because the current screen exposes only plain static URL text.
- [ ] **Step 3: Implement a native actionable link or explicit Open button** using Textual's supported link/browser-opening path. Validate scheme and hostname against existing `AUTH_HOSTS`; reject unrelated hosts and keep cancellation reachable.
- [ ] **Step 4: Run login/cancel and link tests.** Run `python -m pytest -q tests/test_chatgpt_auth_tui.py tests/test_provider_auth_methods.py`.
- [ ] **Step 5: Confirm the one-use code and challenge URL remain absent from `_history` and persisted state; commit only exact source/test paths.**

### Task 6: Measure content and thinking render cost offline

**Files:**
- Create: `scripts/profile_tui_streaming.py`
- Create: `docs/superpowers/results/2026-10-18-isycode-stream-profile.md`
- Reference tests: `tests/test_daily_tui.py`, `tests/test_chat_sequence.py`, `tests/test_focused_box_expansion.py`

**Interfaces:**
- Consumes: `TUIApp._run_chat(text: str, *, resume: Any | None = None)`, with `isycode.tui.provider_complete` replaced by a synthetic provider in `TUIApp.run_test()`.
- Produces: `main(argv: list[str] | None = None) -> int` diagnostic script that reports per-run wall time, process CPU time, cumulative process-CPU time spent in `RichMarkdown` construction and `ThoughtBlock._paint_preview`, and each call count without making a CI timing assertion.

- [ ] **Step 1: Add an offline profile harness.** The fake provider emits no network traffic and returns the emitted text in the same shape as existing provider fixtures. Support content-only and reasoning-only runs with 16,384 total characters, chunk sizes of 16 and 128 characters, and five runs per combination. Add CLI options `--runs`, `--payload-chars`, and `--chunk-chars`; default to the values above and permit a 65,536-character scale run when requested.
- [ ] **Step 2: Capture a baseline profile.**

  Run: `python scripts/profile_tui_streaming.py`

  Expected: report median and min/max wall/CPU time, cumulative time spent in each measured renderer, and render counts per mode and chunk size. Store Python/Textual/OS versions, command, and raw output in the result file. Do not use real provider credentials or count network/model time.

- [ ] **Step 3: Decide whether optimization is justified.** Treat the renderer as a material bottleneck only if the same-host baseline shows repeated cumulative Markdown rendering or reasoning-preview work is responsible for at least 20% of measured CPU time in the synthetic stream. Otherwise preserve code and record that the user's perceived freeze was not reproduced by this profile.
- [ ] **Step 4: If the threshold is met, write behavioral tests before changing rendering.** Add tests in `tests/test_chat_sequence.py` proving that a burst of chunks is coalesced, the final content and reasoning remain byte-for-byte complete and selectable, and pending content is flushed on successful finish, failed partial stream, cancellation, and lane switch.
- [ ] **Step 5: Implement only the measured bottleneck.** If content Markdown formatting dominates, coalesce UI paints while retaining the full source text and flush at turn boundaries. If reasoning preview dominates, change `ThoughtBlock` only with the same boundary guarantees. Do not change stream transport, provider chunking, or Idea Box timing as a rendering workaround.
- [ ] **Step 6: Re-profile with identical samples.** Expected: the targeted render cost drops at least 20% against the same-host baseline; all full-content and boundary tests pass. If the target is missed, revert the optimization and retain the profile result only.

### Task 7: Verify and close the stability delivery

**Files:**
- Update: `docs/superpowers/results/2026-10-18-isycode-stability-baseline.md`
- Update: `docs/superpowers/results/2026-10-18-isycode-stream-profile.md` if Task 3 ran
- Verify: `.github/workflows/ci.yml` jobs `test`, `test-textual-current`, and `test-windows`

**Interfaces:**
- Consumes: completed diagnostics and any narrow regression/profile changes from Tasks 1–6.
- Produces: a reviewable evidence record and an explicit release/hold recommendation for Stability A.

- [ ] **Step 1: Run the full local non-integration suite.**

  Run: `python -m pytest -q -m "not integration"`

  Expected: record exact summary and exit status; resolve new regressions rather than weakening tests.

- [ ] **Step 2: Run the focused failure and streaming tests again.** Run the tests named in Tasks 1–3 and compare them with the baseline. Expected: no challenge secret in chat/state, no duplicate or lost stream text, and no active journal worker during the persisted-state scan.
- [ ] **Step 3: Obtain platform CI evidence.** Require Linux 3.10, Linux/Textual 8, and Windows CI jobs from `.github/workflows/ci.yml` before calling the change verified. Preserve each job URL and exact status; unavailable jobs remain `NOT_DEMONSTRATED`.
- [ ] **Step 4: Review evidence and working tree.** Run `git diff --check`, inspect every changed path, and hash the final result files. Do not update `docs/ROADMAP.md`'s overall audit date unless a full fresh roadmap audit was actually performed.
- [ ] **Step 5: Commit the stability change and its evidence by exact paths.** Keep unrelated files out of the commit; recommend a separate commit for any profile-only diagnostic if it is retained.
- [ ] **Step 6: Recommend ship, revise, or hold.** A ship recommendation requires the spec's acceptance criteria and relevant platform CI to pass. A non-reproduced historical failure or unavailable Windows evidence stays explicitly open.

## Self-review

- Spec coverage: Task 1 covers baseline and historical flake; Task 2 covers the Windows journal race; Tasks 3–5 cover the reported multi-turn overwrite, OAuth model-selector, and wrapped-link issues; Task 6 profiles content and reasoning and permits only measured optimization; Task 7 covers full-suite/platform validation and evidence. Gmail remains deferred.
- Review Focus coverage: consecutive-turn widgets are checked in Task 3; model catalog ownership and explicit selection are checked in Task 4; OAuth host validation and cancellation-secret absence are checked in Task 5; worker overlap is in Task 2; fragmented/failed/cancelled stream boundaries are tested in Task 6; large output and active-lane behavior are profiled without a timing assertion in CI.
- No task presumes the root cause. A missing reproduction yields a documented non-fix, not a speculative source edit.
- The 20% profile threshold is a proposed operational definition of “material” for review; it is not a product performance claim.

## Execution handoff

The plan and additions above are approved. Execute directly in this isolated branch, task by task, and require a final review before recommending a merge. Gmail Hive is still a separate later delivery.
