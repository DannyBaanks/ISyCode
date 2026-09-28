# ADR 0001: ISyCode runtime and OpenISy boundary

- **Status:** Proposed implementation direction; validate at M0 before broad integration.
- **Date:** 2026-09-27

## Context

ISyCode and IsyMotron are Python projects. OpenISy is a TypeScript/Bun fork with its own TUI, MCP, skills and L1 services. The ISyCo Gateway and Bridge are separate workspace services, not modules inside the OpenISy checkout. Coupling ISyCode to OpenISy's internal TypeScript modules would add a second runtime boundary and couple this UI to internals that may change.

## Decision

Keep the current Textual application as the first ISyCode renderer. Keep agent and workspace behavior behind Python runtime/provider interfaces. Consume OpenISy capabilities through their standard/configured interfaces: MCP protocol for tools and skill manifests/configuration for skill discovery. Consume Gateway through its HTTP API and Bridge through its handshake contract. Do not import OpenISy source files into Python or reimplement IsyMotron policy.

The UI remains a client. IsyMotron's host, grants, scopes, leases, executor and receipt verifier remain the only authority for local execution. A discovered MCP or skill is not a grant.

## Alternatives considered

1. **Extend the OpenISy TypeScript TUI.** This best reuses its live MCP/skill/session state, but requires an OpenISy-side feature and a versioned IPC/CLI boundary to the Python IsyMotron runtime. The OpenISy checkout has local modifications, so this is a cross-repository change with a larger review surface.
2. **Keep Textual and implement MCP/config adapters.** This preserves the existing Python/IsyMotron integration and isolates the renderer. It means ISyCode connects to configured MCP servers itself and may not observe another OpenISy process's ephemeral connection state unless OpenISy exposes a supported status API.
3. **Embed OpenISy as a subprocess and parse its TUI output.** Rejected: terminal rendering is not a stable integration contract and would make status, cancellation and errors fragile.

## Validation gate

Before M3 is considered complete, demonstrate a read-only spike that discovers one configured MCP, reports its actual connection/tool status, discovers a project skill using OpenISy's documented format, and leaves IsyMotron as the executor. If the MCP status cannot be shared through a supported interface, document that ISyCode owns its own MCP connection state; do not claim it mirrors another OpenISy session.

## Consequences

- UI, policy and side effects can be changed independently.
- MCP and skill lists must be populated from real sources and carry availability/permission state separately.
- The first version will not reuse OpenISy's live session store or session-specific MCP state unless a documented interface is available.
- Moving the UI into OpenISy later remains possible without changing IsyMotron's authority contract.

## Implementation update

The first adapter reads OpenISy's experimental instance HTTP endpoints `GET /mcp` and `GET /skill`, passing the captured launch directory. It does not start/stop servers, invoke tools, read another process's session store, or claim a tool count: the current `/mcp` status response does not include tool definitions. Configure the base URL with `OPENISY_API_URL`; protected servers use Basic credentials from environment variables. This is useful for the current prototype but does not satisfy the stable-contract validation gate above, so the ADR remains proposed.
