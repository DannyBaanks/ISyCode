# Provider authentication methods

## User requirement

Offer provider-specific connection choices like OpenCode: API key, ChatGPT subscription browser sign-in, and headless/device sign-in. Support every method we can implement truthfully. Preserve ISyCode's workspace owners and approvals; a login never grants workspace access. Finish and publish the already authorized daily-use/CI work first.

## Global constraints

- API key and subscription quotas remain visibly separate. Never promise unlimited use or all models.
- Use the official Codex app-server protocol for ChatGPT subscription authentication and inference, not private OAuth token injection or copied CLI code.
- Use a dedicated ISyCode-managed Codex home/keyring namespace, a minimal child environment with inherited proxy/CA trust, and never inspect/reuse harness ~/.codex auth or tokens.
- Empty `environments: []` on thread/start and turn/start explicitly disables official connector environment tools. Disable web, plugins, MCP and multi-agent tools. Reject every unexpected server request and all built-in approval requests. ISyCode's tools still execute only through its existing owners.
- Browser URLs/device codes stay in process memory and are displayed only to the signing-in user; never persist them in transcripts/audit journals. Persist only bounded non-secret lifecycle state and receipts.
- Missing Codex, incompatible protocol, absent keyring, denied grants, cancellation or revoked permissions fail closed. Do not silently fall back to an API key or API billing.
- No unsupported OAuth for arbitrary providers. Existing providers retain API-key methods; local providers retain no-key/local methods. Add methods through a bounded provider capability catalog.
- Local fake RPC servers verify login, lifecycle, streaming, tool-call conversion, malformed messages, cancellation, denial and secret suppression. Live subscription login requires the user's own interaction and allowed auth destinations; do not claim it from local tests.

## Task 1: Official connector protocol adapter

Create `isycode/codex_connector.py` and focused tests. No unrelated edits or commits while the controller finishes CI.

Expose an async context-managed `CodexConnector(executable: str, home: Path, *, timeout_s=120)` that starts an exact `codex app-server --listen stdio://` argv with a filtered child environment and dedicated home; exchange bounded newline JSON-RPC over pipes. Drain stderr without rendering it, reject oversized/invalid frames, use deadlines, kill/wait child on cancellation/exit, and never read credential files. Initialize with own client identity and `experimentalApi: true`. Support request/notification routing and reject unrecognized server requests.

Expose `account()`, `models()`, `start_login(method)` (`browser` -> chatgpt, `device` -> chatgptDeviceCode), `wait_login(login_id)`, `cancel_login(login_id)`, `logout()` and `complete(model, messages, tools, on_chunk)`. Login returns a bounded process-only challenge and validates official HTTPS auth URLs. account returns only auth type/plan/presence, not emails or tokens. Inference uses ephemeral threads with empty environments and read-only sandbox, no built-in actions. Preserve message boundaries by encoding the transcript as data in the user input rather than promoting imported messages to system authority. Set developer/base guidance explaining existing message-role contracts. Dynamic tool definitions adapt ISyCode OpenAI schemas; a dynamic-tool server request returns one OpenAI tool_call to the caller and stops the child/turn before any execution. Subsequent completions consume the externally produced tool results in the supplied transcript. Text deltas produce ordinary streamed content, bounded by existing transport limits. Failed/interrupted turns must raise a sanitized ProviderError/connector error, not report success.

Tests must use a fake executable RPC subprocess and local fixtures; never call login/account/model APIs on the installed harness credentials. Also inspect installed protocol schemas under /tmp/isycode-codex-schema/v2 as interface reference, not code to copy. Empty environments are documented there as disabling environment access.

## Task 2: Authentication ownership and provider selection

Add a provider capability catalog distinguishing billing/method requirements. Add a ChatGPT subscription preset backed only by the official connector, with default model `auto` resolved by connector and no API key. Keep OpenAI API preset distinct internally while showing both methods under OpenAI in the UI. Add a typed/journaled login owner and explicit grant/approval for official executable + authentication destinations + dedicated storage. Do not mint grants during execution. Token storage/refresh stays with official Codex keyring. Register owner/action/systembility and coverage. Add connector identity/method/executable to request material for inference so existing ProviderNetworkOwner receipts bind what executes.

## Task 3: Product flow and diagnostics

Provider selection opens supported auth-method choices. API-key selection keeps existing owned vault flow; browser/device login shows challenge in a modal and offers cancel/status, disconnect with confirmation, then provider model selection. Saved sessions carry provider/method via subscription preset identity; environment overrides remain authoritative. doctor reports non-secret method/billing/dependency requirements without reading credentials or spawning a connector. `/check` reports subscription connection through the same inference owner. Label available/unconfigured/unsupported methods truthfully.

## Task 4: Verification and delivery

Review each task and final diff. Verify minimum Python3.10 plus current3.12 transport/TUI tests, local suite and any user-authorized live login witness. Reconcile docs and authority coverage; commit and push to the PR branch. If cloud destinations or user login prevent live validation, report precise pending integration without claiming it passed.
