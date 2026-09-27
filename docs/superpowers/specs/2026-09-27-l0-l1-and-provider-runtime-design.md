# ISyCode L0/L1 and dynamic provider runtime

**Status:** design for review
**Date:** 2026-09-27
**Scope:** ISyCode TUI, inference routing, model-facing tool execution, and provider configuration

## Goal

Bring OpenISy's self-extension model to ISyCode without importing model-authored code into the TUI process or treating tool declarations as permission. Also make the Providers view discover provider/model catalogs dynamically while keeping a clear distinction between providers that are listed and providers that ISyCode can actually use.

ISyMotron remains the authority for filesystem, process, network, and tool effects. The ISyCo Bridge remains optional coordination only. This work does not modify OpenISy, OpenCode, or ISyCode Móvil.

## Current state

- `isycode/l1.py` is a small prototype. It stages Python source and runs `exec` in a subprocess, but it has no confined interpreter, no persistent activation generations, no receipts, and no runtime registry integration. It is not suitable to expose to the model as-is.
- The current chat path streams a single completion through IsyMotron-selected provider presets. It does not execute model tool calls.
- `OpenIsyClient` already reads `/provider` and `/provider/auth` from a configured OpenCode-compatible server. The TUI shows this data as discovery metadata; it does not route inference or perform OAuth through that server.
- `isymobile` starts OpenISy or OpenCode and emits a pairing link. It is not the provider catalog. The server's `/provider` route supplies all/default/connected providers; `/provider/auth` supplies authentication methods, and its OAuth routes start and complete authentication.

## Product behavior

### Provider catalog and routing

1. Providers displays two execution paths:
   - **IsyMotron native:** the locally supported provider adapters and credential states.
   - **OpenCode-compatible server:** the catalog returned by `/provider`, including models, server default, and connected providers.
2. Each provider and model has an explicit state: discovered, connected, selected, and runnable. Discovery alone never implies connectivity or execution support.
3. Native API keys remain in ISyCode's credential vault or supported environment configuration. OAuth for a remote provider is performed and stored by the configured OpenCode-compatible server; ISyCode must not copy or display the server's OAuth secrets.
4. Inference routing selects the native streaming adapter for native providers. The remote path sends prompts through an OpenCode-compatible session backend only when that backend is explicitly active and connected. It must not silently fall back to a different provider or server.
5. `/provider` and `/provider/auth` responses are metadata only. The TUI must handle unsupported endpoints, authentication failures, timeouts, and provider-specific missing models without showing stale data as current.

### L0/L1 self-extension

1. L0 is ISyCode's protected host, loader, validation gates, broker, registry, recovery logic, and built-in tools. L1 contains user- or model-authored tool packages.
2. L1 packages live under ISyCode-owned project and user roots, separate from `.opencode/l1/`. The model-facing API is `l1_create_tool`, `l1_activate_tool`, and `l1_list`; the semantic CLI/TUI surface also supports history, rollback, disable, doctor, and safe mode.
3. Candidate state transitions are `REQUESTED → STAGED → VALIDATED → TESTED → PROBED → SEALED → ACTIVE`. Any gate failure records `REJECTED` evidence and leaves the currently active generation untouched.
4. Activation is atomic and updates the running tool registry at a turn boundary. The previous sealed generation remains available for rollback. An activation journal supports recovery after an interrupted switch.
5. L1 source is never imported or evaluated in the ISyCode host process. A resource-bounded, out-of-process confined worker exposes no ambient filesystem, process, network, or host-runtime globals. Host effects are explicit IPC requests to a capability broker.
6. The broker checks each requested capability against the manifest's declared `requires` and `effects`, then delegates the concrete operation to IsyMotron. Missing declarations or IsyMotron grants fail closed. Creating, testing, sealing, activating, or listing a tool does not grant its effects.
7. Gates, broker decisions, activation, disable, and rollback produce receipts linked by content hashes. Listing tools shows active generations and rejected generations with their evidence.
8. Safe mode disables L1 discovery and execution while preserving the TUI, built-ins, and recovery controls. The initial product setting is opt-in; enabling L1 does not broaden IsyMotron grants.
9. Built-in tool names cannot be shadowed. The loader accepts only verified active descriptors under allowed L1 roots. Symlinks, path escapes, malformed manifests, tampered receipts, timeouts, and oversized output are fail-closed.

## Architecture and boundaries

### Provider components

- Extend the existing OpenCode-compatible client to retain provider model metadata and default selection, plus explicit server authentication state.
- Add a remote inference backend behind the same chat/session boundary as the native provider backend. It owns remote session creation, prompt submission, cancellation, and event translation.
- Keep credential storage separated by owner: ISyCode vault for native API keys; remote OpenCode server for its own OAuth credentials.
- Never report a provider as runnable until the selected backend has a concrete supported request path and the required credentials are available.

### L1 components

- `L1Service`: candidate creation, manifest validation, real test/probe gates, generation history, activation journal, live registry refresh, rollback, disable, recovery, and safe-mode state.
- `L1Worker`: isolated interpreter process with strict input/output limits and an IPC-only host interface. The host reads source as inert text and launches the worker; it never imports candidate code.
- `CapabilityBroker`: validates declared capabilities and routes each operation through IsyMotron's existing authorization and receipt verification. Bridge messages and leases never satisfy this check.
- `ToolLoop`: consumes provider tool-call events, dispatches only registered built-ins or verified active L1 tools, returns bounded results to the model, and supports cancellation and turn limits.
- `L1Catalog`: exposes the three model-facing L1 tools and semantic CLI/TUI controls without making candidate code executable during discovery.

The provider catalog and L1 runtime are separate work streams. Provider discovery may ship independently, but remote provider selection is not enabled until its session backend is complete. L1 must not ship as active execution until its worker and broker boundaries are in place.

## Failure handling

- Provider discovery failure leaves the last result visibly stale or unavailable and preserves the current working backend. It never silently changes providers.
- OAuth failure returns an explicit state and does not expose tokens in UI, logs, or model context.
- Candidate gate failures record which gate failed and bounded diagnostic evidence. They cannot replace the active generation.
- Worker crash, timeout, output overflow, malformed IPC, hash mismatch, undeclared effect, or IsyMotron denial terminates that invocation and records a denial/failure receipt.
- Activation failure restores the previous active generation from the journal. If recovery cannot verify the previous state, L1 stays disabled and built-ins remain available.
- L1 disabled or safe mode leaves normal chat and native providers usable.

## Rollout milestones

1. **M0 — contracts and baselines:** record current provider routing, TUI tool-loop behavior, L0 fingerprints, and IsyMotron authority interfaces; define versioned manifests, receipts, and IPC messages.
2. **M1 — provider catalog:** show all remote providers/models and connected/default status from the configured server; keep discovery distinct from execution.
3. **M2 — provider authentication and routing:** support remote OAuth through the server's authorize/callback routes and add remote session inference, cancellation, event translation, and explicit backend selection.
4. **M3 — L1 storage and gates:** create isolated project/global roots; implement manifest validation, staging, actual tests, isolated probe, sealing, and rejection history.
5. **M4 — worker and broker:** add the confined worker, bounded IPC, declared-effect enforcement, IsyMotron authorization, receipts, and built-in shadowing protection.
6. **M5 — model/tool loop:** register `l1_create_tool`, `l1_activate_tool`, and `l1_list`; support tool calls, cancellation, turn limits, and live activation at a turn boundary.
7. **M6 — recovery and TUI controls:** add history, rollback, disable, doctor, opt-in, safe mode, and status surfaces.
8. **M7 — hostile verification:** exercise tamper detection, workspace escapes, undeclared effects, denial behavior, L0 fingerprints, timeout/output limits, worker cleanup, crash recovery, and provider auth/routing failures.

## Acceptance criteria

- The Providers view returns the complete dynamic remote catalog, model lists, server default, and connected state without falsely labeling discovery as executable.
- A user can select a connected remote provider/model and observe prompts routed through the selected remote backend; native provider selection remains unchanged.
- OAuth credentials remain on the server that performed OAuth; native API keys remain in the ISyCode vault; neither appears in logs or model context.
- A model can stage and activate an L1 tool only after the real gates pass; a rejected generation never changes the active generation.
- Active L1 tool code executes only in the confined worker. A hostile tool cannot access ambient filesystem, process, network, built-in shadowing, or undeclared capabilities.
- Every broker decision and state transition has verifiable receipt evidence; tampering is detected and execution fails closed.
- IsyMotron denial remains effective even when an L1 manifest declares a capability. Activating a package never creates or widens a grant.
- Activation and rollback take effect without restarting the TUI. A crash during activation recovers to the last verified generation or leaves L1 disabled.
- Safe mode and opt-out prevent L1 discovery/execution without disabling the core TUI or native provider path.
- The Bridge remains optional, does not start a daemon, and has no role in authorizing L1 execution.

## Explicit limitations

- A child process and hash chain alone do not prove OS-enforced memory or filesystem isolation, nor do local receipts provide external authenticity. These must remain marked as limitations unless independently demonstrated.
- OAuth methods in a provider catalog are not proof that every provider's flow is compatible with the TUI. Unsupported methods remain unavailable with an explicit reason.
- The catalog can advertise providers that the active backend cannot execute; UI and APIs must preserve that distinction.

## Non-goals

- Changing OpenISy or ISyCode Móvil source code.
- Moving provider credentials between the mobile app, ISyCode, and the OpenCode-compatible server.
- Letting L1 bypass IsyMotron, the Bridge, or user-selected authority policy.
- Claiming operating-system-enforced immutability, unlimited provider compatibility, or resource bounds stronger than the worker can demonstrate.
