# ISyCode Stability and Gmail Hive — Design Spec

**Date:** 2026-10-18
**Status:** Approved for Delivery A implementation; Delivery B deferred
**Design approval:** The user approved “stability first, then Gmail Hive,” then approved adding the three reported chat/OAuth UX issues to Delivery A on 2026-10-18.
**Baseline checkout:** `main` at `7038d0dee866f6e3237f336ebd73f0532c1a2bf7` (verified against `origin/main` during this design pass).

## 1. Purpose

Define two reviewable deliveries for ISyCode:

1. Reduce known reliability and responsiveness risks in the current TUI, validating each change with repeatable evidence.
2. Add an opt-in Gmail “Hive” input that can surface selected email metadata as visible, human-reviewed events in ISyCode.

The second delivery depends on the first. This document specifies goals, boundaries, and acceptance criteria. It is not an implementation plan; the user reviews this spec before a milestone plan is written.

## 2. Current-state evidence and uncertainty

The following are observations from repository/CI inspection. Historical measurements are labeled as such; they are not claims about a fresh test run on this branch.

- **[CURRENT, code inspected]** The Idea Box is a short visible status note. Its approximately 150-second nudge asks the model to refresh that note during an active chat/tool lane; it does not poll Gmail or another remote inbox. Relevant implementation: `src/isycode/idea_box.py`, `src/isycode/tui_app_chat.py`, and `src/isycode/tui_app_sessions.py`.
- **[CURRENT, code inspected]** ISyCode has a local bounded event store (`src/isycode/agent_events.py`) and a polling cursor with interval/backoff for local agent events (`src/isycode/agent_polling.py`). These are useful primitives, but they are not a remote Gmail synchronizer.
- **[CURRENT, code inspected]** Gateway MCP invocation is mediated by Authority/Sentinel and approval owners. A background sync must not be smuggled in as an unrestricted MCP tool call or use the Idea Box timer as hidden permission.
- **[CURRENT, sibling code inspected]** The ISyCo monorepo Gateway has Gmail list/search/get/read and send operations. The Drive Mirror OAuth path requests read and send scopes. It does not currently expose a Gmail History cursor contract. The separate `ISyCo Drive Mirror/v0.9-opencode-plugin` folder is Drive-focused; it is not proof that a deployed Gmail MCP exists.
- **[NOT DEMONSTRATED]** Live Gateway deployment, Gmail History synchronization, and a production OAuth flow for this feature have not been demonstrated. Integration feasibility from source code is not proof of a live service.
- **[HISTORICAL, previous audit]** A full local pytest run recorded 2,040 passed, 160 skipped, and one failure in `test_area_f_interrupted_turn_capture_and_resume`; that test passed when rerun alone. This indicates possible load sensitivity, not a confirmed deterministic defect.
- **[HISTORICAL, CI]** Windows CI failed in `test_native_subscription_login_and_cancel_never_save_challenge[True]` with a PermissionError while reading the Sentinel journal lock during a TUI test. A background startup scan racing test teardown is a plausible cause, but remains an inference until reproduced and isolated.
- **[NOT DEMONSTRATED]** Rebuilding `RichMarkdown` from cumulative streamed content may contribute to long-response slowdown. It requires profiling before any optimization.
- **[USER-REPORTED, code-path cause identified; regression test pending]** After a completed assistant response, `lane.stream_widget` can still reference that response. A later `_content_line()` may reuse that mounted widget and replace the prior answer. The fix must preserve prior turn widgets while allowing only the active turn's stream widget to update.
- **[USER-REPORTED, implementation gap under investigation]** After ChatGPT subscription OAuth, the model selector should let the user choose a model actually available to the signed-in Codex account. Do not guess models or switch away from `auto` unless the user chooses.
- **[USER-REPORTED, code gap identified]** The subscription-login screen displays the raw long OAuth URL as plain static text, so the terminal does not expose an actionable link. Make the official URL clearly clickable while preserving host validation, cancellation, and secret-handling behavior.
- **[USER-REPORTED, reproduced from screenshot and code]** The native sibling-folder dialog accepts a display alias such as `Github`, but the store accepts only lowercase aliases and rejects the registration. Canonicalize casing at the store boundary, keep case-insensitive duplicates from registering twice, and preserve the exact sibling path and existing per-folder grants.
- `docs/ROADMAP.md` still identifies its static audit as 2026-10-09 / commit `49cb0a1`; its status text should not be treated as a fresh audit of the 2026-10-18 baseline.
- The prior workflow-gate validation reported historical evidence/approval mismatches. This work must not rewrite evidence, manufacture approvals, or mark gates complete without fresh proof.

## 3. Delivery A — Stability first

### Goal

Turn the observed reliability risks into reproducible findings, fix only verified causes, and preserve current safety behavior.

### Scope

- Reproduce the Windows Sentinel-journal CI failure with a focused test and determine whether test teardown races a still-running startup worker.
- Make a minimal lifecycle/synchronization change only if the race is reproduced; add a regression test that proves the worker has completed before the journal is inspected or that teardown waits safely.
- Reproduce the reported multi-turn chat behavior with consecutive user/assistant turns, including a tool round if needed. Preserve prior user and assistant messages in the visible transcript and conversation history; distinguish actual replacement from normal scroll-offscreen behavior.
- Make the ChatGPT subscription model selector usable after OAuth. It must source choices from the authenticated provider/account model catalog (or explicitly report that the account did not provide one), retain `auto` as the default, and never select a model silently.
- Make the official ChatGPT sign-in URL actionable in the OAuth modal, including at 80×24 and when displayed across wrapped terminal rows. Keep URL validation restricted to the official auth hosts and do not append the challenge URL or one-use code to chat history or persisted state.
- Make native sibling-folder registration accept natural mixed-case aliases by canonicalizing them to lowercase, reject case-only duplicates, and retain the current direct-sibling path checks and exact folder-scoped Authority grants.
- Rerun the focused test and relevant TUI/auth tests on Windows CI, then the required local suite. Record exact commands, commit, results, and any platform gaps.
- Profile streaming response rendering with a representative long response. Optimize only if measurements show a material bottleneck; preserve streaming order, visible thinking behavior, and message history.
- Refresh roadmap audit metadata only after the relevant state has actually been re-audited. Do not change milestone acceptance status as a side effect.
- Report the workflow-gate findings separately. Repair a gate only when the underlying contract or evidence is wrong and the change is supported by new evidence.

### Acceptance criteria

1. The prior Windows failure is either reproduced with a clear root cause and fixed with a regression test, or documented as not reproduced with the exact CI/local evidence and next diagnostic boundary.
2. A completed assistant response remains unchanged after later user turns and assistant/tool output; the regression test covers the observed consecutive-turn sequence. If only scroll position explains the screenshot, record that separately instead of claiming content loss.
3. After ChatGPT OAuth, the model control opens a selector that reflects the signed-in account's available model catalog; `auto` remains selected until the user chooses a concrete model.
4. The sign-in URL can be activated from the OAuth screen at supported terminal sizes, opens only an approved official auth URL, and the private one-use code/URL stays out of chat history and persistent state.
5. A mixed-case sibling alias such as `Github` registers canonically as `github`; case-only duplicates are rejected and permissions remain scoped to the selected folder.
6. Relevant tests pass on the supported CI platform(s); no assertion is weakened to hide the failure.
7. Any rendering optimization has before/after profiling evidence and does not regress stream correctness or TUI behavior. If no material bottleneck is measured, no optimization is made.
8. No historical evidence, approvals, or gate records are rewritten to create a pass.
9. The stability change is reviewable independently from Gmail Hive.

## 4. Delivery B — Gmail Hive, after stability

### User-visible behavior

Gmail Hive is an optional, foreground feature that can monitor one user-selected Gmail label while the ISyCode TUI is open. It surfaces concise metadata events in a visible queue. The user chooses which event to process. Processing creates a normal user-visible task/context item; it does not authorize tools or send mail.

The Idea Box remains a status display. It may show a concise “checking / N new items” status only while the explicitly enabled Hive session is active, but it is not the scheduler, cursor, queue, or authority source.

### Sync and event contract

1. The user explicitly connects Gmail, selects a label, and enables monitoring. The feature is **off by default**.
2. The connector reads message metadata only: stable message ID, thread ID, selected labels, sender, subject, and timestamp. It does not fetch message bodies or attachments in the initial version.
3. The Gateway owns Gmail API access. ISyCode uses a narrow read-only integration contract; it does not store OAuth refresh tokens in workspace files or expose them to a model.
4. The Gateway provides incremental Gmail History synchronization with a durable cursor. ISyCode stores only the minimum local cursor and deduplication/event state required for restart-safe display.
5. Every candidate event is checked against the configured label ID in the application layer. Gmail query text alone is not an authorization boundary.
6. Events enter the existing local event-store pattern as untrusted input, are sanitized and deduplicated, and appear in an explicit pending-events view.
7. The user must select **Process** before content is added to the chat/task. **Dismiss** and **Pause** are available. Merely receiving or displaying mail never invokes a tool.
8. Any later tool action still goes through the existing workspace authority, ISySentinel, and one-use approval flows. An email cannot grant permissions, modify allowlists, or bypass policy.
9. Polling occurs only while the user has enabled the feature and the TUI is running. It uses a bounded cadence with backoff and visible last-sync/error status. No hidden daemon, Gmail push notification, or background service is part of V1.
10. If Gmail reports an expired history cursor (including 404), the connector performs a bounded resynchronization for the selected label, deduplicates by message ID, then persists the new cursor. The UI must show that a resync occurred.
11. Authentication revocation, permission errors, rate limits, network errors, cursor expiry, duplicate delivery, and app restart are explicit states. Failures pause or back off; they do not silently skip events or invoke model actions.
12. Stored state is minimal and private. Message body, attachment content, and full email archive are out of scope.

### Permissions and privacy

- Use the narrowest Google scope that supports the chosen metadata contract; the initial design target is `gmail.metadata`, not `gmail.readonly` or `gmail.send`.
- Google classifies Gmail metadata/read scopes as restricted. OAuth verification and any applicable security-assessment obligations must be reviewed before distribution. The design does not claim these requirements are waived.
- The Gateway service permission should be a distinct read-only capability such as `isyco.email.metadata.read`; it must not inherit `email.send`.
- The feature must disclose the selected label, fields read, polling state, local retention, and how to disconnect/purge its own state.
- Gmail content is untrusted data. Email text, sender names, and headers cannot become system/developer instructions or change tool policy.

### Explicit non-goals for V1

- Sending, replying, forwarding, drafting, labeling, archiving, deleting, or marking mail read.
- Reading bodies, attachments, or arbitrary mailbox contents.
- Watching all inbox mail by default.
- Running while ISyCode is closed, hidden, or in a daemon/service.
- Gmail Pub/Sub push, browser automation, or using the user's Chrome session.
- Treating an email as a command, tool grant, approval, or trusted agent message.
- Replacing ISyCode's existing Authority/Sentinel or local event-store contracts.

### Acceptance criteria

1. Disabled-by-default behavior is proven; no Gmail request occurs until the user connects and explicitly enables the selected label.
2. The selected label, metadata field allowlist, and read-only Gateway permission are enforced in code and covered by tests.
3. Incremental History sync survives restart, deduplicates repeated events, and visibly recovers from an expired cursor without losing the user’s pending queue.
4. No message body, attachment, send operation, or model/tool invocation occurs during polling.
5. Pending items require an explicit user action to enter chat context; an email cannot change Authority, Sentinel, or approval state.
6. Tests cover revoked auth, 403/429, network timeout, duplicate events, cursor expiry, pause/resume, and restart using offline fixtures.
7. A live test, if later approved, uses a dedicated test label/account and records exactly which metadata was read. It is not a prerequisite for writing this spec or plan.
8. OAuth verification and data-handling obligations are documented before enabling this for general users.

## 5. Shared design decisions

- Treat Gmail as an external source of untrusted events, not a source of authority.
- Keep transport (Gateway), persistence (local cursor/event store), presentation (visible queue), and user authorization as separate responsibilities.
- Do not add a second polling framework if the existing event-store/polling patterns can be extended safely. Confirm that with a plan and tests first.
- Any failure to meet a safety or data-retention contract blocks release of Gmail Hive, even if the demo appears to work.
- Each delivery has its own tests, evidence, review, and release decision.

## 6. Review boundary

Delivery A's product behavior and scope are approved for implementation by the user. Gmail Hive will get its own implementation plan only after Delivery A has passed its review gate. This approval does not authorize Gmail OAuth scopes, live Gmail account access, or external service writes.

## 7. References

- ISyCode local event store and poller: `src/isycode/agent_events.py`, `src/isycode/agent_polling.py`.
- ISyCode Idea Box and TUI integration: `src/isycode/idea_box.py`, `src/isycode/tui_app_chat.py`, `src/isycode/tui_app_sessions.py`.
- Google, [Choose Gmail API scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).
- Google, [Gmail API `users.history.list`](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list).
- Historical project roadmap: `docs/ROADMAP.md` (its audit date is stale against this baseline and is not used as current proof).
