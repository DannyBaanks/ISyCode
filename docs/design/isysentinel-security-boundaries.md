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

`gateway/sentinel.py` is a remote API perimeter, not a Systembility aggregator.
It hashes presented keys, checks registered key status and expiry, operation
allowlists, applies an in-memory per-process rate limit, and returns key
metadata/scopes. Gateway HTTP auth remains an independent gate for every
request, even when ISyCode's local decision allows the action.

The inspected Gateway implementation also has limits that ISyCode must not
mistake for guarantees: the settings argument is unused by key loading;
`enabled=False` allows every request; `require_https` is declared but not
enforced in `validate`; rate buckets and revocations are process-local; and
unknown-key logging writes the first eight characters of the supplied key.
These audit observations remain; the semantic workspace-identity change does
not alter key verification, HTTPS enforcement, rate limits, revocation, or
logging. ISyCode uses HTTPS/origin checks in its client, keeps credentials in
its own protected vault, sends only the minimum required key to the Gateway,
and reports remote Gateway auth separately from local workspace authorization.

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

The canonical pure contracts now live in `isycode/security.py`: immutable
`ActionRequest`, request-bound `AuthorityDecision`, all-check aggregation, and
fail-closed handling for unknown actions, missing Systembilities and exceptions.
`isycode/workspace_authority.py` separately stores explicit path/host/executable/
target grants per canonical workspace, and `isycode/approvals.py` holds
short-lived, one-use request-bound approvals. `isycode/actions.py` centralizes
the semantic action catalog. The old combined implementation remains in
`isycode/isysentinel.py` as `LegacyIsySentinelPrototype`; it is not canonical.

The provider request owner and bounded workspace list/read/name-search owner
call Workspace Authority and the pure IsySentinel through
`isycode/action_runtime.py`. Settings has a user-consented management flow to
grant or revoke the exact read-only workspace scope and the active provider
host. Provider credentials do not imply network scope. The request digest
includes a registered execution-owner identity; the aggregate gate denies
owner/action pairs absent from its closed registry. `isycode/action_audit.py`
stores decision and verified receipt digests in a private per-workspace
hash-chain journal outside the checkout. Journal failure denies before an
action or returns NOT_VERIFIABLE after an effect. The Files rail and context
picker use the native ISyCode read owner; IsyMotron's old read adapter remains
in the repository only as a legacy adapter.

This is partial enforcement, not a complete product boundary. Connected
owners now include Workspace, provider, Gateway/MCP discovery and invocation,
LSP, sessions delete, and semantic broker. Mobile Host, Bridge, L1, general
workspace mutation and other unimplemented action families remain
unavailable. The IsyMotron Planner may produce a proposal after provider-host
authorization, but its legacy Executor is disabled in Secure. The action
journal has no UI inspector/verifier yet, and code has only received syntax
and diff checks for the latest journal changes; do not claim a live journal
witness or complete coverage.

The semantic workspace-binding work updates only the Gateway HTTP identity
contract; it does not change `bridge_core` or the Gateway key/scope policy.
Other Gateway perimeter findings above remain separate work.
