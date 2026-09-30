# ISyCode Mobile Host contract v1

This contract is owned by ISyCode. ISyCode owns runtime discovery, authorization,
sessions, event streams, and approval decisions. The mobile app is a client and
must not infer permission from discovery data.

## Implemented in this slice

The Textual TUI can start the host on `127.0.0.1:8765` after an explicit
workspace grant and request-bound approval. It remains loopback-only and stops
when the owning TUI exits. Pairing exchange is gated by the `mobile.pair`
owner; a valid, single-use PIN is the human-presence proof. Credential metadata
and a durable result receipt are recorded before the one-time token is returned.
If the receipt cannot be written, the new credential is revoked and pairing
fails closed. Settings shows host liveness, transport, the locally visible
pairing PIN, and active heartbeat clients.

Configuration:

| Variable | Default | Meaning |
|---|---|---|
| `ISYCODE_MOBILE_HOST_BIND` | `127.0.0.1` | Bind address. Non-loopback requires TLS. |
| `ISYCODE_MOBILE_HOST_PORT` | `8765` | TCP port; `0` asks the OS for a free port. |
| `ISYCODE_MOBILE_HOST_TLS_CERT` | unset | PEM certificate required for non-loopback. |
| `ISYCODE_MOBILE_HOST_TLS_KEY` | unset | Matching private key required for non-loopback. |

Pairing PINs contain six digits and expire after five minutes. A successful
exchange consumes the PIN and returns a random bearer credential once. The
credential expires after one hour. Invalid exchanges are limited to five per
peer per minute and twenty globally during the PIN lifetime. Credential
metadata and SHA-256 token digests live under
`$XDG_STATE_HOME/isycode/mobile-host/keystore.sqlite3` (or
`~/.local/state/isycode/mobile-host/keystore.sqlite3`) with restrictive POSIX
directory/file permissions. Raw API credentials are not persisted.

## HTTP routes

The host accepts both `/v1/...` and `/isycode/v1/...` forms for the mobile
client. The configured client base URL will be
`https://<verified-tailnet-name>/isycode`, so its health request is exactly
`GET /isycode/v1/health`. Both host route forms are registered because the
local Tailscale CLI help does not specify whether `--set-path` preserves or
strips the mount prefix when proxying. That behavior remains to be verified
from another tailnet device. ISyCode's TUI shows the exact route and requires a
fresh approval before changing it. It does not enable Funnel or replace
unrelated Serve routes. An enabled route persists after the TUI exits (Serve
runs with `--bg`) and is removed only through the approved disable action;
Settings warns about this while the route is live. See security invariant 11
in the private tailnet design. JSON errors use standard HTTP status codes and a short
text reason.

| Route | Auth | Current behavior |
|---|---|---|
| `GET /v1/health` and `GET /isycode/v1/health` | None | Minimal service/version/state probe; does not expose clients or pairing state. |
| `GET /v1/status` and `/isycode/v1/status` | Bearer + `host:status` | Returns state, authenticated connected-client labels, and whether pairing is pending. Pair-issued credentials do not include this operator scope. |
| `POST /v1/pair/exchange` and `/isycode/v1/pair/exchange` | Pair PIN | Body: `{"code":"123456","device_name":"Danny's phone"}`. Returns `201` with `{api_key,key_id,expires_at,scopes}` once; PIN is invalidated. The local `mobile.pair` grant and Sentinel decision must pass. |
| `GET /v1/runtimes` and `/isycode/v1/runtimes` | Bearer + `runtime:read` | Lists known runtime commands, whether each command is installed, and `adapter: "pending"`, `selectable: false` for now. |
| `POST /v1/runtimes/select` and `/isycode/v1/runtimes/select` | Bearer + `runtime:select` | Validates JSON `runtime_id` and key runtime scope, then returns `409` because no remote runtime adapter is connected yet. |
| `POST /v1/clients/heartbeat` and `/isycode/v1/clients/heartbeat` | Bearer + `client:heartbeat` | Body: `{"client_id":"stable-device-id","device_name":"Danny's phone"}`. Renews a 45-second in-memory client lease. |

Pair-issued credentials currently carry `runtime:read`, `runtime:select`, and
`client:heartbeat`, scoped to the runtime wildcard. A heartbeat proves client
liveness only. The host ignores client-supplied runtime/session state. Detailed
status is never exposed by the unauthenticated health route. The credential
store rejects every scope outside those three, including the reserved file,
session, and operator scopes; those stay unavailable until their action owners
and approval flows exist.

## Explicitly not implemented yet

There is no remote session creation/resume, conversation history API, WebSocket
event stream, runtime execution, tool approval endpoint, cancellation endpoint,
or key administration endpoint in this slice. The TUI has an owner-gated,
private Tailscale Serve setup for the Mobile Host; actual remote access is not
claimed until the route is explicitly approved and verified from another
tailnet device. Runtime
names in the catalog are inventory only; none is selectable. The mobile app
must not present a runtime as ready or attempt chat/session calls against
unimplemented routes. The existing mobile Bridge and pairings remain unchanged
until a later migration implements those contracts.

Before enabling remote execution, the contract must add authenticated session
routes, request/response schemas, event ordering/replay semantics, cancellation
and approval state machines, workspace/runtime/action grants, revocation
behavior, and a transport/deployment profile. Those decisions belong to the
ISyCode host contract and must be reviewed together with the mobile client.
