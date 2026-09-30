# M15 Gateway perimeter review — 2026-09-28

## Follow-up — Gateway code work

The initial read-only audit below identified an inaccurate health flag, an AST
test that scanned operator-only modules, a claims-name mismatch, and broad
Drive/Gmail/GitHub scopes that authorized both reads and mutations. The
Gateway checkout has since been updated:

- The structural test follows the local import graph reachable from FastAPI;
  it still checks the explicit mutation route allowlist and audit write mode.
- The claim is now consistently named `WRITE_SURFACE_RESTRICTED`.
- `/health` reports `read_only: false`; the advertised scopes do not grant a
  caller any authority by themselves.
- New granular scopes separate Drive read/write, Gmail read/send, and GitHub
  read/issue creation. Legacy broad scopes remain read-only. Duplicate, blank,
  reserved, or malformed configured scope aliases prevent startup.
- The production Compose recipe fixes one Uvicorn worker and enables HTTPS
  enforcement while trusting forwarded protocol only behind its tunnel.
- The schema smoke treats `/v1/workspace/identity` as a real route and reports
  the correct granular scope for each integration operation.

Verification: `gateway/tests` passed **89 tests** with all 35 named Gateway
claims PASS. `run_schema_smoke.py` reported 6 PASS, 10 documented DEGRADED, 16
NOT_DEMONSTRATED, and zero schema drift or missing backend routes. Compose
configuration validation passed; it warned that `CLOUDFLARE_TUNNEL_TOKEN` is
not set.

The local deployment has since been restarted from the repair Compose file.
The Gateway and semantic broker are healthy; the Gateway reports
`read_only: false`, rejects an HTTP request without the trusted proxy marker
(400 `HTTPS_REQUIRED`), and accepts the proxy-marked health request. The
`.isyroot` at `/home/danny/Development/ISyCo` is empty, and the running
Gateway and ISyCode now agree on its derived opaque workspace ID. An
authenticated identity read through ISyCode's real `SemanticGatewayClient`
matched that ID. No public tunnel is running, and the active workspace has no
local Authority policy file. Therefore public-origin behavior and a semantic
operation passing the local Authority + IsySentinel + approval gates remain
NOT DEMONSTRATED.

## Scope

Gateway review, focused ISyCode integration, and a local container restart.
The repair Compose file and Gateway README were updated; an ignored,
mode-0600 Compose `.env` now contains only the non-secret workspace ID. No key
store or credential value was changed or printed.

## What the current FastAPI server demonstrates

- `gateway/app.py` authenticates requests with `gateway.auth.KeyStore`; each
  route uses a dependency that checks its required scope.
- Revoking a key is re-read from the keystore and invalidates requests using
  that key. The isolated Gateway suite passed this witness.
- Rate limits are enforced, but their buckets are in-process memory. The
  Gateway's own `gateway/ratelimit.py` documents that effective limits multiply
  with the worker count. This is not a distributed limit.
- `GATEWAY_REQUIRE_HTTPS` defaults to `false`. When enabled, the middleware
  rejects a plain request. Forwarded-protocol headers are consulted only when
  `GATEWAY_TRUST_FORWARDED_PROTO` is also enabled. This proves configurable
  enforcement, not the production deployment's configuration or proxy trust.
- The focused HTTP tests demonstrated that presented keys are not written to
  the audit log and that credential-shaped provider data is redacted.
- The current `gateway/app.py` does not import or call `gateway/sentinel.py`.
  The latter's `enabled=False` allow-all behavior and key-prefix logging are
  therefore legacy module risks, not evidence of a bypass in the inspected
  FastAPI path. Keep that module disconnected or retire it before anyone wires
  it into a request path.
- The repair Compose deployment binds only `127.0.0.1:8787`, enables
  `GATEWAY_REQUIRE_HTTPS=1`, and trusts forwarded protocol for its local TLS
  terminator. A request without `X-Forwarded-Proto: https` returns 400; the
  proxy-marked health request returns 200 and reports `read_only: false`.
  The semantic API key can read the configured opaque workspace identity; the
  response does not include `IESY_ROOT`.

## Test evidence

Commands used `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, and
`GATEWAY_CLAIMS_DIR=/tmp/isycode-m15-gateway-claims`.

| Suite | Result | Finding |
|---|---:|---|
| `gateway/tests/test_gateway.py` | 27 passed, 1 failed | `test_no_write_surface_exists` expects the scoped HTTP write-route list, which matched, but then scans every package module and fails on `socket`/`subprocess` imports in standalone `cli.py` and `subprocess` in standalone `provider_vault.py`. It does not establish that those imports are reachable from an HTTP route. |
| `gateway/tests/test_containment.py`, `test_redaction_surfaces.py`, `test_semantic_workspace_identity.py` | 35 passed | Case/path containment, symlink escape, provider redaction, and opaque workspace identity witnesses passed. |
| `gateway/tests/test_linux_operator.py` in isolation | 5 passed | Launcher ownership refusal and log/status behavior passed when run alone. |
| Combined Gateway selection excluding the package-wide write-surface test | 65 passed, 2 failed | The two Linux operator tests passed in isolation; their combined-run failures are order/environment-sensitive and need isolation in the Gateway test suite. |

The Gateway test suite's claims recorder writes `WRITE_SURFACE_ABSENT`, while
the current assertion records `WRITE_SURFACE_RESTRICTED`. The claim naming
needs reconciliation as well. Do not call that structural test a pass, and do
not infer an HTTP bypass from its module-wide import findings without tracing
the route import graph.

## M15 consequence

Gateway source-level auth/scope enforcement, revocation, path containment,
request limits, redaction and focused HTTPS middleware behavior are
demonstrated by tests. The test/import-graph defect and fixture environment
leak remain to be reconciled. The repair Compose service is now restarted and
serves the updated health metadata. A matching per-root workspace identity is
configured in Gateway and derived by ISyCode; an authenticated identity read
through the real ISyCode client matched. These changes do not widen any
ISyCode grant or make an unowned operation available.

No public tunnel is running. The current workspace also has no local
Authority policy file, so a semantic query through the full local
Authority + IsySentinel + approval path remains NOT_DEMONSTRATED.

## Remaining acceptance items

1. Restore a functioning tunnel/origin and verify HTTPS enforcement and proxy
   trust against that public origin.
2. Confirm one worker is the intended production limit or move request quotas
   to shared state before increasing worker count.
3. The matching workspace identity is configured and demonstrated. To close
   the operation witness, obtain the explicit local
   `gateway.semantic.read` grant and one-use approval in ISyCode Settings,
   keep the remote key scoped to `isyco.semantic`, and invoke one read-only
   semantic query. No Gateway write route is needed for this witness.

The origin, matching workspace ID, local grant/approval and remote key scope
are operational prerequisites. Unit tests and `/health` alone do not satisfy
the end-to-end acceptance item.
