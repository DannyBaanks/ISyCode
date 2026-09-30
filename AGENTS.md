# ISyCode repository guidance

- ISyCode is the active project in this repository. Do not attribute its code, roles, or behavior to OpenISy.
- ISySentinel is ISyCode's deny-by-default decision layer. It aggregates read-only Systembility results; it never executes actions or mutates requests.
- Workspace Authority is separate from Sentinel and owns explicit per-`.isyroot` grants. `.isyroot` defines only the maximum logical sandbox boundary; it never grants access.
- Each workspace runs in Security mode (everything off until explicitly granted) or Classic mode (a fixed Workspace Authority preset of implicit grants for workspace read/edit, the chosen provider, saved sessions and saved keys). Classic never bypasses IsySentinel, execution owners, per-action approvals or the action journal, and never implies integrations or explicitly denied actions.
- Execution owners/adapters perform an action only after Sentinel returns ALLOW, then report verified outcomes. Roles, injected context, provider credentials, Gateway keys, MCP scopes, and Bridge leases are not workspace grants.
- IsyMotron may be an optional runtime/provider integration, but it is not ISyCode's security authority. Do not require or modify its policy semantics for ISyCode security.
- The ISyCo Gateway HTTP Sentinel is a separate remote perimeter: it validates API keys, operation allowlists, expiry/status, and rate limits. For Gateway calls, both local ISyCode authority/Sentinel and the Gateway's own request validation must pass.
- The ISyCo Bridge is optional, opt-in coordination. A lease is a traffic light between peers, not authorization. Do not start a Bridge daemon.
- When using the Bridge, call `bridge_core/capabilities/cap.agent_bridge/handshake.py`; do not edit `workspace/agents/bridge/` files directly. Keep identity and lease tokens in process memory and never print them in chat or logs.
- Preserve unrelated user changes. Inspect repository state before editing and keep changes scoped to the requested work.
- Do not claim that commands, tests, integrations, or external services ran unless they actually ran.
