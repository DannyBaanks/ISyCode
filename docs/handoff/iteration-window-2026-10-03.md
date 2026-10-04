# Iteration Window — bounded vertical slice

## Current result

The protocol and minimal UI are implemented. Real cross-provider completion is
NOT_DEMONSTRATED: ChatGPT subscription returns text resembling a tool call
instead of an actual dynamic call. The owner refuses its unobserved contribution.
No text-to-tool parser, permission reduction, or provider-specific coordinator
branch was introduced. An experimental eager-loading connector change did not
resolve this and was withdrawn; codex_connector.py remains unchanged.

A historical initial real NVIDIA run (GLM 5.3 → Kimi K3 → Nemotron 3 Ultra)
completed head 4, WAITING_FOR_HUMAN; both subsequent participants repeated
`otter-731926` from GLM. This preceded the final storage binding correction.
Subsequent current-code NVIDIA runs stopped at Kimi with an invalid/empty
returned contribution. These are preserved as negative evidence, not called PASS.
The current deterministic fixtures execute the unchanged run_child and real
execution-owner gates, with simulated provider transport explicitly identified.

## Architecture and contracts

`src/isycode/iteration.py` provides IterationOwner and run_iteration. IterationOwner
composes the existing registered `chat_sessions` storage binding; it does not
register a second ambiguous execution owner for the same actions. Both
session.create and session.resume remain required for participant reads because
observations are durably recorded. Provider traffic goes through the existing
ProviderNetworkOwner. Authority, Sentinel, action catalog, grants, normal chat
formats and run_child are unchanged.

One private hash-chained JSONL is canonical. It includes creation, attempt,
read, failure receipt and rename events, plus numbered human/agent/human_handoff
contributions. event_seq numbers every record; seq numbers only contributions.
Metadata and last_seen_seq are replayed from that ledger. This avoids dual-file
transaction ambiguity. Successful execution receipts are embedded in their
contribution, committed in the same append. The separate existing action audit
continues to contain metadata/digests only, never transcript contents.

Every operation validates the ledger under flock. Permission is checked before
creation/append. Partial tails, hash damage, unsafe files, stale heads, wrong
participants, wrong attempts and out-of-range reads fail closed. Identical
completed-attempt replay returns the existing contribution; conflicting replay
is denied. Failure keeps head unchanged; retry keeps turn_id/based_on_seq and
uses a fresh attempt_id. A final contribution marks WAITING_FOR_HUMAN and ends
the round. Cancellation produces ABORTED and preserves earlier contributions.
No automatic retries, skips, or new rounds.

References are random per active attempt and never filesystem paths. Only their
hash enters the ledger. The model tool takes ref/after_seq/through_seq; trusted
dispatch binds session, participant and attempt independently of model arguments.
Reads may reconstruct from zero; private provider memory is not canonical.
There is no workspace tool, command, Git, recursive delegation or MCP capability
in the participant's tool set. Existing redaction is applied to content.
No chain-of-thought is persisted.

## Human guide

Restart ISyCode to load the new commands.

- `/iteration <objective>`: choose three participants in order using the existing
  grouped provider/model selector. Each Launch selection is explicit. The last
  participant has the HUMAN_HANDOFF contract.
- Esc during execution cancels the current iteration. Prior contributions remain.
- `/iteration retry <iteration_session_id>` explicitly retries a failed participant;
  completed participants are not executed again. The session must have no active
  unresolved attempt. Crash reconciliation is deliberately manual in this slice.
- Sessions labels iteration rows `↻ Iterative`; first click previews their order,
  status and final contribution, second click opens the persisted contributions.
  Opening is inspection, never replay. The ordinary chat context is not replaced
  with iteration content.
- `/models` is the single model selector; `/providers` is the provider selector.
- `/keys` shows grouped credential status. Configured is expanded; optional and
  unconfigured groups are folded. It displays no credential values.
- Recognized slash commands no longer create user-message bubbles. Command history
  remains available with arrow keys. Ordinary messages are unchanged.

The backend accepts two or three participants; the minimal UI currently selects
three. One human round per iteration. There is no fresh-round, skip, cost routing,
summary/checkpoint, persistent provider-session, or parallel-participant feature.
Saved identities reflect the requested model (`auto` for subscription); the
underlying subscription's resolved concrete model is not captured in this slice.

## Evidence and tests

See ../evidence/iteration-window-2026-10-03/hashes.json. `*-turns.jsonl` are
read-only projections of contributions; `happy.jsonl` and `failure-retry.jsonl`
are the actual append-only canonical ledgers. Fixtures use a test-only resolver
and simulated transports, not live providers. They demonstrate:

```
seq 1 human
seq 2 fixture A, based_on_seq 1, TOKEN_A=nonce-314159
seq 3 fixture B/human_handoff, based_on_seq 2, repeats nonce-314159
```

Failure fixture: B timeout leaves head 2 and PARTICIPANT_ERROR receipt. Explicit
retry uses a new attempt ID, same turn/head, then appends seq 3 and handoff.
NVIDIA historical ledger, current NVIDIA failure and current cross-provider
failure are included separately. Their outcome labels must not be merged.

Final full suite: 1324 passed, 6 skipped, 8 multiprocessing deprecation
warnings in 221.77 seconds (final-suite.log). Focused check: 43 passed.
Concurrency, corruption, redaction and cancellation controls passed. Preserve unrelated docs/ROADMAP.md and other agents'
untracked audit/handoff files.

## Verdicts

- ITERATION_OWNER: DEMONSTRATED (existing owner binding composition).
- ITERATION_APPEND_ONLY_STATE: DEMONSTRATED.
- AUTHORIZED_ITERATION_REFERENCE: DEMONSTRATED.
- TURN_CONTINUITY: DEMONSTRATED.
- SEQUENTIAL_MULTI_AGENT_LOOP: DEMONSTRATED with controlled transports;
  real NVIDIA historical success, current NVIDIA failures recorded.
- CROSS_PROVIDER_ITERATION: NOT_DEMONSTRATED live; deterministic two-provider
  fixtures pass. Subscription dynamic tool invocation is the outstanding gate.
- HUMAN_HANDOFF: DEMONSTRATED in fixtures and historical real NVIDIA round.
- SECURITY_COMPATIBILITY: DEMONSTRATED by existing checks and negative fixtures;
  this is not a proof against a same-user process modifying private state.

Next minimum step: separately establish a genuine dynamic tool call through the
installed ChatGPT connector, then repeat the persisted NVIDIA → ChatGPT → NVIDIA
round. Do not turn emitted JSON text into a tool request as a shortcut.
