# ISyCode security boundaries: Authority, Sentinel, and Gateway

Status: architecture contract for ISyCode. The referenced implementations in
ISyCo were inspected read-only on 2026-09-27; this document does not claim that
the contracts are already wired through every ISyCode action.

## What the existing code calls Sentinel

There are two different components named Sentinel and they must remain distinct.

### Runtime Sentinel and Systembilities

`bridge_core/runtimes/windows/python/engine/runtime/sentinel.py` is a pure
consensus point. It receives an immutable execution context, invokes every
configured Systembility, records each PASS/FAIL result, and returns only
ALLOW/DENY. An empty Systembility set, a failure, or an exception denies. It
does not execute, repair, grant permissions, or mutate the context. The Engine
is the execution owner and must make execution unreachable unless Sentinel
returns ALLOW. The bootstrap `MiniSentinel` is a separate bootstrap-operation
allowlist; it is not the runtime security Sentinel.

Authority answers the different normative question “may this transition
exist?”. Sentinel is its sole consumer. An ALLOW from Authority is necessary,
but not sufficient: the execution owner must also be verified by a
Systembility before the aggregate decision is ALLOW.

### Gateway HTTP Sentinel

Gateway HTTP authentication is an independent gate for every request, even
when ISyCode's local decision allows the action. The current FastAPI app uses
`gateway.auth.KeyStore`, `_authenticated`, and route-specific scope dependencies.
Its tests demonstrate key/scope rejection, immediate persisted-key revocation,
secret-free audit output, and per-process rate limits. The old
`gateway/sentinel.py` module is not imported by `gateway.app` and has no
production callsite in the inspected Gateway tree. Its disabled-pass behavior
and key-prefix logging are legacy-code risks, not evidence that the current
FastAPI request path bypasses authentication. It should remain disconnected or
be retired; it must not be mistaken for the active HTTP gate.

The current app defaults `GATEWAY_REQUIRE_HTTPS` to false for local use. It
rejects plain HTTP when that setting is enabled, and trusts
`X-Forwarded-Proto` only when the operator separately enables forwarded-proxy
trust. Its token-bucket limits are explicitly in-memory and per process, so
multiple workers multiply the effective limit. These are deployment
conditions, not local ISyCode grants. The Gateway tests run on 2026-09-28
passed key, scope, revocation, path, rate, HTTPS-when-enabled, and redaction
checks. One structural “write surface” test fails because it scans standalone
`cli.py` and `provider_vault.py` for imports as though they were mounted HTTP
modules; the live route set matches the test's explicit list of scoped write
routes. A live local health response also reports `read_only: true` while the
app mounts scoped file-write, Drive-upload, email-send, and GitHub-issue
endpoints. ISyCode does not use that field as an authorization signal; the
Gateway should correct the misleading health metadata. See the
[Gateway perimeter audit](../security/m15-gateway-audit-2026-09-28.md) for
exact commands and remaining evidence.

ISyCode uses HTTPS/origin checks in its client, keeps credentials in its own
protected vault, sends only the minimum required key to the Gateway, and
reports remote Gateway auth separately from local workspace authorization.
This does not prove the production endpoint is configured for HTTPS or that a
live Gateway request has both local and remote grants.

## ISyCode's contract

The request path is:

```text
intent → resolve immutable ActionRequest → Workspace Authority
       → applicable read-only Systembilities → IsySentinel ALLOW/DENY
       → execution owner performs the action → verification/receipt
```

- **`.isyroot`** identifies the nearest workspace root and caps paths that an
  action may address. It is not a grant, does not turn on file enumeration,
  and does not grant ancestors or siblings.
- **Workspace Authority** is bound to the canonical `.isyroot` identity and
  stores explicit action/effect/scoped grants in ISyCode private state, outside
  the checkout. Missing, malformed, or mismatched policy denies. Grants may
  further narrow to paths, hosts, executables, runtimes, or tools; they cannot
  widen the `.isyroot` boundary.
- **IsySentinel** only evaluates the applicable Systembilities and the
  Authority result. It evaluates all applicable checks and reports each one.
  An empty applicable set, a failed check, a thrown check, or an unknown action
  produces DENY. It never prompts, consumes an approval, writes a receipt, or
  performs the requested effect.
- **Approval UI** may create a short-lived, single-use approval bound to the
  immutable request digest. Authority/Systembilities verify it. An approval is
  not a persistent grant and cannot change the request after confirmation.
- **Execution owner** (local filesystem adapter, provider transport, Gateway
  client, MCP adapter, LSP process manager, Docker broker manager, Mobile Host,
  Bridge client, or L1 runtime) calls Sentinel before its effect. It must fail
  closed if the decision is absent, stale, or not ALLOW. It records the
  post-action result/receipt separately.
- **Gateway call** requires both local ISyCode ALLOW and remote Gateway HTTP
  Sentinel ALLOW. A Gateway key is authentication to Gateway, not a local grant;
  a local grant does not authenticate to Gateway.
- **IsyMotron** can remain an optional runtime/provider adapter. ISyCode's
  security decision does not depend on its grant files or receipts. The
  hackathon integration may display its own results, clearly labeled as such.
- **Bridge** is optional coordination only. Hello, leases, messages, and
  wakeups do not grant filesystem, process, network, or tool permissions.

## Action catalog coverage

The UI and policy store should enumerate these semantic action families; every
concrete invocation carries an action ID and scoped target. Unknown IDs deny.

| Family | Actions to cover |
| --- | --- |
| Workspace | list, read, search, preview, context injection, write, create, move, delete, sensitive-read |
| Models and credentials | provider request, model discovery, API-key add/use/revoke, OAuth start/callback, Roundtrip review |
| Gateway | health/status, semantic reads, file reads/writes, remote key/scope check |
| MCP and skills | discover/list, inspect, activate, invoke, deactivate |
| LSP | discover, start, initialize, request, cancel, stop |
| Semantic broker | choose root/recipe, preview, build, start, health, logs, stop, remove |
| Sessions | create, list, resume, rename, export, delete, cancel turn |
| Mobile Host | status, start, stop, pair, revoke device, runtime/session list, create, stream, cancel, approval response |
| Bridge | connect, hello, peek, send, claim/release lease, wake |
| L1 runtime | stage/create, validate, test/probe, activate, disable, rollback, list |
| Desktop/UI | native file picker, clipboard copy, open file, search transcript, choose role |

Listing a provider/tool/runtime is read-only discovery. Selecting it is not an
execution grant. Each side effect must use the same authorization path. The
policy UI must show the exact action, scope, target, decision source, and
receipt/status without displaying secrets.

## Implementation status and gaps

The canonical pure contracts now live in `src/isycode/security.py`: immutable
`ActionRequest`, request-bound `AuthorityDecision`, all-check aggregation, and
fail-closed handling for unknown actions, missing Systembilities and exceptions.
`src/isycode/workspace_authority.py` separately stores explicit path/host/executable/
target grants per canonical workspace, and `src/isycode/approvals.py` holds
short-lived, one-use request-bound approvals. `src/isycode/actions.py` centralizes
the semantic action catalog. The old combined implementation remains in
`src/isycode/isysentinel.py` as `LegacyIsySentinelPrototype`; it is not canonical.

The provider request owner and bounded workspace list/read/name-search owner
call Workspace Authority and the pure IsySentinel through
`src/isycode/action_runtime.py`. Provider requests bind a digest of their complete
request material and append a result receipt without storing prompt or result
content. Settings has a user-consented management flow to grant or revoke the
exact read-only workspace scope and active provider host. Provider credentials
do not imply network scope. The request digest includes a registered
execution-owner identity; the aggregate gate denies owner/action pairs absent
from its closed registry. `src/isycode/action_audit.py` stores decisions and
verified receipt digests in a private per-workspace hash-chain journal outside
the checkout. Journal failure denies before an action or returns
NOT_VERIFIABLE after an effect. The Files rail and context injection use the
native read owner. Native picker invocation remains unavailable in Secure;
IsyMotron's old read adapter remains only as a legacy adapter.

The local Secure frontier is closed: active Workspace, provider, Gateway MCP,
semantic Gateway, LSP, broker, and session-delete owners use the central gate
and write their supported receipts. Mobile Host, Bridge, L1, general workspace
mutation, persistent session creation/resume, clipboard, and file pickers
remain unavailable because those owners are not connected. This is an
intentional Secure boundary, not a claim that these features are implemented.
The IsyMotron Planner's provider call now runs through `ProviderNetworkOwner`;
its legacy Executor remains disabled. The action journal has a read-only UI
inspector/verifier; local receipt and HTTP redirect tests use isolated fixtures.
M15 is still open for the production Gateway deployment witness and a real
remote-Gateway operation. The current server source and isolated tests
demonstrate authentication, scopes, revocation, HTTPS enforcement when
configured, and redaction. They do not prove the deployed origin enables
HTTPS, uses a trusted proxy correctly, or has a suitable worker/rate-limit
configuration. Local client HTTPS/origin checks do not prove any of those
deployment facts.

The semantic workspace-binding work updates only the Gateway HTTP identity
contract; it does not change `bridge_core` or the Gateway key/scope policy.
The failed structural test and deployment witness remain separate work; no
Gateway source was changed from the ISyCode checkout.
