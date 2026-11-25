# Native ISyCode Telegram Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run native, persistent ISyCode agent sessions from a personal Telegram bot, with asynchronous messages, tool/provider events, native approvals and crash-safe queues.

**Architecture:** Extract a frontend-independent turn controller and core local-tool dispatcher from the current agent, preserving the native owners, policy, continuity and provider contracts. A local per-profile service consumes Telegram updates, stores transactional queue/delivery state and translates interaction requests into private-chat controls. TUI and Telegram use the extracted core; Telegram never drives a Textual test harness or executes chat text as shell.

**Tech Stack:** Python 3.10+, asyncio, existing aiohttp transport, sqlite3, existing OS keyring, StateIndex, ISyCode owners and pytest. Telegram Bot API via HTTPS long polling, with an injectable transport for hermetic tests.

**Spec:** `docs/superpowers/specs/2026-11-24-isycode-telegram-native-design.md`, including its verified-baseline addendum. Original approved artifact: monorepo commit `79f482ed`. Product base: remote-verified `e88109b5d12df4d0acd679b40db792ca062563f6`.

## Global Constraints

- Each user supplies their own bot; only the paired owner in their own private chat may act. Groups and arbitrary first senders have no access.
- A local independent service survives closing the TUI. Nothing starts automatically on installation.
- All durable state derives from StateIndex; tokens stay in the secure keyring and never enter request digests, transcripts, events or logs.
- Native Authority, Sentinel, execution owners, receipts and approval semantics remain in force. Classic/Security retain their sandbox requirements; Flow retains its locally selected v2 semantics. Telegram is explicitly enabled separately in every mode.
- Sessions use ChatSessionOwner, including revision/divergence checks. Do not merge two writers or replay effects after an uncertain interruption.
- No global saved-key reader is switched between concurrently running workspaces: resolve provider credentials per run through its own owner and inject the Provider instance.
- FIFO per session; at most one active turn per session and one effectful turn per workspace in this service; bounded concurrency between different workspaces.
- Provider-exported reasoning is observational. Never fabricate or retrieve hidden reasoning, or use event content as authority.
- Changes remain in `/tmp/isycode-telegram-native`, branch `feat/telegram-native-service`; preserve the original dirty checkout. No push, service installation or live pairing is implicit.

## Review Focus

- Duplicate/delayed Telegram updates and crashes between acceptance and acknowledgment must not create a second turn (Task 3).
- Mode/grant changes, session switching and callback replay during approval must invalidate the old decision (Tasks 2 and 4).
- Concurrent workspaces must not share provider credentials or overwrite a TUI continuity (Tasks 1 and 5).
- Long/non-BMP text, hostile formatting, oversized diffs and token-bearing transport errors must remain bounded and correctly represented (Task 6).
- Disconnect/restart while a command was running must preserve an explicit uncertain outcome without executing it again (Tasks 3 and 5).

---

## File map

- New `src/isycode/agent_runtime.py`: neutral turn loop, provider-step/checkpoint hooks, events and cancellation.
- New `src/isycode/agent_tools.py`: core read/write/command/Git routing and frontend approval/question ports; no Textual imports.
- Adapt `headless.py`, `tui_app_chat.py`, `tui_app_tools.py` to the extracted pieces without duplicating loops or changing their visible behavior.
- New `src/isycode/telegram/{__init__,state,owner,transport,render,service,cli}.py`: persistence, Authority boundary, HTTP adapter, message formatting, scheduling and operator CLI.
- Adapt `actions.py`, `workspace_authority.py`, `action_coverage.py`, `credential_owner.py`, `state_index.py`, `launcher.py` and the generated coverage snapshot where required.
- New focused tests: `test_agent_runtime.py`, `test_agent_tools.py`, `test_telegram_state.py`, `test_telegram_owner.py`, `test_telegram_transport.py`, `test_telegram_service.py`, `test_telegram_cli.py`.
- Native guide `docs/integrations/telegram/GUIA.md`; approved spec and this plan travel with the product branch.

### Task 1: Extract the turn runtime and preserve frontend parity

**Files:** Create `agent_runtime.py`, `tests/test_agent_runtime.py`; adapt `headless.py` and `tui_app_chat.py` as the extraction requires.

**Interfaces:** `TurnPorts` supplies `emit(kind: str, payload: dict) -> None`, `dispatch(call: dict) -> Awaitable[tuple[str, str]]` and checkpoint/context callbacks. `AgentTurn.run(messages: list[dict], *, provider: Provider, tools: list[dict], ports: TurnPorts) -> Awaitable[TurnResult]`. `TurnResult` contains `text: str`, `messages: list[dict]`, `usage: dict` and `provider_receipts: list[str]`. Provider resolution is caller-owned and injected, not a process-global credential hook.

- [ ] Write failing cases: controlled provider emits reasoning/text, invokes a real read-owner adapter and answers; events preserve order and call/result IDs. Cancellation after a tool result does not lose it. A second workspace cannot use the first provider/owner; changed transcript revision is refused by the session owner.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_agent_runtime.py -q`; observe missing runtime behavior before implementation.
- [ ] Move the smallest cohesive provider/tool iteration out of UI rendering. Keep TUI retry, compaction, turn journal, session steering and partial-output cleanup as explicit callbacks/state transitions; use the same extracted implementation from TUI/headless/service rather than adding a parallel lasting loop.
- [ ] Run the new tests plus `tests/test_headless.py` and the existing chat/context/continuity tests selected by the actual touched paths. Compare failure/cancel and reasoning behavior, not only successful final text.
- [ ] Commit only this runtime extraction and its tests after reading the successful run output.

### Task 2: Native core-tool interactions without a UI dependency

**Files:** Create `agent_tools.py`, `tests/test_agent_tools.py`; adapt `tui_app_tools.py` and its current write/command adapters only where needed to use the shared dispatcher.

**Interfaces:** `LocalAgentTools(root: Path, authority: WorkspaceAuthority, approvals: ActionApprovalStore, interactions: InteractionPort)`. `await dispatch(call: dict) -> tuple[str, str]`. `InteractionPort.review(request: ActionRequest, preview: ReviewMaterial) -> Awaitable[bool]`; `ask(question: dict) -> Awaitable[dict]`. `ReviewMaterial` carries the exact digest, complete review text, action label and policy fingerprint. Native approvals are issued only after the port returns a valid reviewed response and the request is revalidated.

- [ ] Write failing fixtures for a real temporary file edit accepted/rejected, exact command preview, altered preview/policy after review, one-use approval and a question answered/cancelled. A tool name unknown to ISyCode remains denied. Classic/Security without a sandbox never run host commands; locally selected Flow keeps its native owner semantics.
- [ ] Run the new tests before moving effectful code.
- [ ] Extract routing for the core local tools into this dispatcher; keep effects in existing owners. Frontends implement the interaction port; remove duplicated routing only where the shared equivalent is verified. Optional integrations without a complete port remain unavailable, with an explicit result.
- [ ] Run tool, writer, command, Git and frontend regression tests appropriate to touched branches; verify actual file bytes and receipts in positive/negative cases.
- [ ] Commit the shared dispatcher and adapters.

### Task 3: Durable profiles, queue and event delivery

**Files:** Create `telegram/__init__.py`, `telegram/state.py`, `tests/test_telegram_state.py`; add the state directory resolver to `state_index.py`.

**Interfaces:** `TelegramStore(profile: str, *, index: StateIndex | None = None)`. `accept_update(update_id: int, user_id: int, command: dict) -> AcceptResult`; `enqueue(session_id: str, text: str, update_id: int) -> QueueItem`; `claim_next() -> QueueItem | None`; `finish(turn_id: str, state: str)`; `append_event(turn_id: str, kind: str, payload: dict) -> int`; `pending_deliveries() -> list[Delivery]`; `ack_delivery(id: str, telegram_message_id: int)`. Profile stores canonical bot/user IDs, opaque session bindings and locally registered workspace aliases, never token values. Queue state and update cursor transitions share SQLite transactions. `QueueItem` has `id: str`, `session_id: str`, `workspace: Path`, `turn_id: str`, `text: str`, `update_id: int`, `state: str`; `AcceptResult` has `accepted: bool`, `duplicate: bool`, `cursor: int`, `queue_id: str | None`; `Delivery` has `id: str`, `turn_id: str`, `sequence: int`, `payload: dict`, `attempts: int`.

- [ ] Write failing cases: duplicate update creates one item, rejected update advances safely, process restart preserves FIFO and marks running items interrupted, cancelled pending items never claim, a second claimant cannot claim the same turn, bad IDs/unknown schema refuse mutation.
- [ ] Test two stores in separate state roots for user isolation; rollback a transaction between update acceptance and enqueue and verify neither half persists.
- [ ] Implement schema/version validation, WAL/transactions, private files and a kernel-held per-profile process lock. Persist snapshots/event records and delivery acknowledgments; never use a JSON queue rewrite.
- [ ] Run `PYTHONPATH=src python -m pytest tests/test_telegram_state.py -q` and StateIndex regression tests. Verify DB contents and native file permissions in fixtures.
- [ ] Commit state/store implementation and tests.

### Task 4: Telegram's own authority and approval owner

**Files:** Create `telegram/owner.py`, `tests/test_telegram_owner.py`; adapt `actions.py`, `workspace_authority.py`, `credential_owner.py`, `action_coverage.py` and generated coverage snapshot.

**Interfaces:** `TelegramOwner(root, authority, approvals)` authorizes connection, instruction intake and content export with action IDs `telegram.connect`, `telegram.receive`, `telegram.send`; targets include verified bot ID, private user ID and workspace. `RemoteReviews.open(context: ReviewContext, material: ReviewMaterial) -> PendingReview`; `resolve(callback_id: str, context: ReviewContext, approve: bool) -> bool`. Review context binds profile, bot, user/chat, workspace, session, turn and policy fingerprint. `ReviewContext` is a frozen dataclass with those bound identity fields and `policy_fingerprint: str`; `PendingReview` contains `callback_id: str`, `request_digest: str`, `expires_at: float` and `context: ReviewContext`. Callbacks are opaque and single use; native approval secrets remain process-local.

- [ ] Write failing deny-by-default tests in Security, Classic and Flow; a saved token or paired account never grants workspace actions or export. Test changed mode/policy/digest/session, cross-profile callbacks, replay, expiry and restart: none yields an approval or an effect.
- [ ] Extend credential service/consumer registries narrowly for `isycode-telegram`; use the existing credential owner/vault and explicit local setup approval. No plaintext fallback or token-valued ActionRequest.
- [ ] Implement authorizations and remote review lifecycle. Recheck live authority before every instruction, exported batch and reviewed action; invalidate pending requests on revoke/restart/policy change.
- [ ] Regenerate coverage through the repository's canonical generator, run its verifier and relevant Authority/credential tests; do not hand-edit the snapshot.
- [ ] Commit owner, catalog/registry integration and evidence.

### Task 5: Native sessions and asynchronous scheduler

**Files:** Create `telegram/service.py`, `tests/test_telegram_service.py` using Tasks 1–4.

**Interfaces:** `TelegramService(store: TelegramStore, transport: TelegramTransport, runner_factory: Callable)`. `await start()`, `await stop()`, `await handle_update(update: dict)`, `await work_once()`. A runner resolves Provider credentials through the current workspace CredentialUseOwner, opens a native ChatSessionOwner, injects the runtime/tool ports, persists the user message before execution and the verified assistant result after execution, and streams events to the store. Active sessions are selected through validated opaque bindings.

- [ ] Write failing end-to-end controlled-transport tests: `/nueva`, multivuelta text, enqueue during a blocked turn, FIFO and queue withdrawal, questions, approval, cancel, native session reopen, concurrent workspaces and TUI divergence. Assert real transcript bytes/events/receipts and denied effects.
- [ ] Implement a receive task independent of per-workspace workers; default two active workspaces, one turn per workspace/session. Edits to Telegram messages do not mutate accepted instructions. Only aliases registered locally may open a workspace.
- [ ] Implement restart semantics: retain pending queue, mark active runs interrupted, require explicit continuation, expire reviews and deliver saved events. Never retry uncertain tool calls to recreate an output. Revoke stops intake/export and cancels at the owner-safe boundary.
- [ ] Run service tests plus runtime/tools/state/owner tests; test network disconnection while a real temporary command is in progress without replaying that command.
- [ ] Commit scheduler and session integration.

### Task 6: Real Telegram adapter and bounded presentation

**Files:** Create `telegram/transport.py`, `telegram/render.py`, `tests/test_telegram_transport.py`.

**Interfaces:** `TelegramTransport(secret_reader, *, session_factory=...)`: `await get_updates(offset: int) -> list[dict]`, `await send(chat_id: int, render: RenderedMessage) -> SendReceipt`, `await edit(...)`, `await answer_callback(...)`. `TelegramRenderer.event(event: dict) -> list[RenderedMessage]`. `RenderedMessage` contains `text: str`, `buttons: list[list[dict]]`, `filename: str | None`, `document: bytes | None`; `SendReceipt` contains the verified `chat_id: int` and `message_id: int`. Transport exceptions carry safe error codes and retry timing only; URL/token strings are never logged. Inject an aiohttp-compatible controlled session in tests.

- [ ] Verify official Bot API operations, polling conflict behavior, rate limit response and message/entity limits before implementing; cite official references in the native guide.
- [ ] Write failing tests for HTTP errors, malformed JSON, rate limit/reconnect, failed sends preserving delivery state, partial chunks, emoji/non-BMP boundaries, hostile Markdown/buttons, long results and oversized review material. A review cannot approve a truncated summary when the full material was not delivered.
- [ ] Implement using existing aiohttp rather than another runtime dependency. Use escaped/plain text plus renderer-owned buttons, coalesce progress updates, preserve full detail separately and export reasoning only when actually provided.
- [ ] Run controlled HTTP tests; scan artifacts against synthetic secrets and assert delivery retries never enqueue a second tool call.
- [ ] Commit adapter and renderer.

### Task 7: Operator CLI, lifecycle and pairing

**Files:** Create `telegram/cli.py`, `tests/test_telegram_cli.py`; adapt `launcher.py`; create `docs/integrations/telegram/GUIA.md`.

**Interfaces:** Native subcommands `isycode telegram configure`, `serve`, `status`, `stop`, `revoke`, `workspace add <alias> <path>`. Configuration uses `getpass`, an explicit expected user ID and a one-use pairing PIN presented locally; subsequent bot input is accepted only from that private user. Canonical bot identity is checked with getMe. Mode/grants and export scope are shown locally; setup never changes workspace mode silently. `serve` runs foreground and can be explicitly managed by a user service; unit installation is an opt-in operator action documented separately.

- [ ] Write failing CLI tests against temporary state/keyring and the controlled transport for missing keyring, mismatched bot/user/PIN, group messages, duplicate service lock, status/stop of the owned process, and revocation during a pending approval. Never kill a guessed or reused PID; use the service's local control channel and verified identity.
- [ ] Implement CLI wiring and service control via a private local endpoint; command arguments and errors never contain tokens. Detect a webhook/another consumer without deleting or taking it over.
- [ ] Execute help/config/status/denial/lifecycle commands under test; document exact verified outputs. Mark real Telegram pairing, live provider calls and installed background service NO PROBADO unless explicitly executed with the owner's configuration.
- [ ] Commit CLI, guide and tests.

### Task 8: Whole-feature acceptance and review

**Files:** Feature code above plus `docs/integrations/telegram/` sanitized evidence and hashes. Update the private briefing registry with the new runtime map only after actual architectural changes are verified.

- [ ] Run the native guide's controlled end-to-end scenario: create session, enqueue second message while first runs, approve one edit/command, deny another, observe reasoning/tools, disconnect/reconnect, restart, cancel/revoke and reopen conversation from TUI. No live bot token is used for these hermetic cases.
- [ ] Run the full repository hermetic suite with `ISYCODE_STATE_HOME`, `XDG_STATE_HOME` and `PYTHONPATH=src` pointing to isolated state/source; retain baseline and feature outputs separately. Report every failure or skip without changing unrelated tests to hide it.
- [ ] Run generated action coverage verification, affected roadmap gate checks, package/import/CLI checks, secret scanning against synthetic credentials and git diff checks. Publication or installing a service remains separate from local implementation.
- [ ] Obtain a whole-branch review on the most capable available reviewer model, addressing evidence-backed findings without expanding unrelated scope. Keep user data and existing contracts intact.
- [ ] Commit exact owned paths, record SHA/hashes, summarize demonstrated behavior and remaining live-test limits. If publishing is later authorized, first push must set upstream to this branch, not origin/main.

## Self-review

Spec requirements map to runtime/tools (1–2), durable state/recovery (3), authority/pairing/review (4/7), session scheduling (5), observability/transport (6), and lifecycle/acceptance (7–8). Optional tools without an approved interaction port are explicitly unavailable, never silently executed. Baseline-addendum Flow semantics and private per-run credential resolution are explicit. No task claims a local test proves a real Telegram deployment.


## Baseline verification before implementation

The source is clean at `e88109b` apart from these planning documents. The complete hermetic suite was started inside the restricted sandbox and manually interrupted after progress stopped; it did not finish and is not a passing baseline. The isolated `tests/test_audit_modal_usage.py::test_usage_refresh_does_not_crash_with_an_active_modal` reproduced the wait during `asyncio.Runner.close()` inside the sandbox, then passed outside it with isolated state, before any product source modification. Preserve `/tmp/isycode-telegram-baseline.log`, `/tmp/isycode-telegram-baseline-probe.log` and `/tmp/isycode-telegram-baseline-probe-unsandboxed.log` as the diagnostic outputs. Execute the complete baseline and feature suites outside that restriction with explicit execution permission rather than changing the test or the product to hide the environment issue.

Plan self-review completed: no uncovered spec requirement identified. Execution method review is pending: native implementation with a whole-branch reviewer is recommended because the shared-runtime extraction and its ports must stay consistent across the scheduler, TUI and Telegram. The user may instead select per-task agents/reviews. No product code has been modified at this planning checkpoint.
