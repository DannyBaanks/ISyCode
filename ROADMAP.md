# ISyCode — TUI Agent Roadmap

**One AI. Many hosts. One capability fabric. Now in your terminal.**

ISyCode is a minimalist TUI (terminal user interface) for AI agents, built on
the IsyMotron capability fabric and the OpenISy coordination layer. It brings
the "model proposes, host decides, receipts record" model to a keyboard-first
interface — no browser, no mouse, no web server.

---

## Why this exists

IsyMotron already has the full agent backend: provider seam, strict planner,
deny-by-default enforcer, sealed receipts, demo-host fixtures. What it lacks
is a surface that feels like Pi or OpenClaw — a fast, keyboard-driven TUI
where you can watch Nemotron plan, approve execution, and inspect receipts
without leaving the terminal.

OpenISy already has the coordination substrate: bridge mailbox, capability
registry, role system, gateway HTTP API, L1 self-extension pipeline. What it
lacks is an agent that uses it.

**ISyCode is the missing piece: a TUI that connects the two.**

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  ISyCode TUI (textual / rich)                           │
│  stdin/stdout → render plans, receipts, leases, tools   │
└──────────────────────┬──────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐
   │ OpenISy  │  │IsyMotron │  │ OpenISy  │
   │ Gateway  │  │ Provider │  │ Bridge   │
   │ (I/O)    │  │ Planner  │  │ (coord)  │
   │          │  │ Enforcer │  │          │
   │ files    │  │ Host     │  │ leases   │
   │ search   │  │ Receipts │  │ identity │
   │ semantic │  │          │  │          │
   │ drive    │  │          │  │          │
   │ email    │  │          │  │          │
   │ github   │  │          │  │          │
   └──────────┘  └──────────┘  └──────────┘
```

**IsyMotron** = the brain (provider → planner → enforcer → receipts)
**OpenISy Gateway** = the eyes and hands (files, search, semantic, drive, email, github)
**OpenISy Bridge** = coordination (if multiple agents)
**OpenISy L1** = self-extension (model-authored tools)

---

## What is reused (not rebuilt)

| Component | Source | What it gives ISyCode |
|---|---|---|
| `Provider.complete()` | IsyMotron `agents/provider.py` | One call to Nebius/NVIDIA/Ollama/llama.cpp |
| `Planner.plan()` | IsyMotron `agents/planner.py` | Intent → typed capability request, strict schema |
| `Enforcer.decide()` | IsyMotron `core/isymotron/policy.py` | Pure function, deny-by-default, closed vocabularies |
| `Host` (authority) | IsyMotron `core/isymotron/host.py` | lease + execute + receipt minting |
| `LoopbackRelay` | IsyMotron `relay/loopback.py` | In-process transport, no network needed |
| Demo-host fixtures | IsyMotron `hosts/simulator/engines.py` | ModernHost/LegacyHost — real authority, fake OS |
| `Grants` | IsyMotron `hosts/windows/grants.py` | Local authority, JSON, deny-by-default |
| `verify_receipt()` | IsyMotron `core/isymotron/verify.py` | Re-derive decisions, show provenance |
| Gateway HTTP | OpenISy `gateway/app.py` | files, search, semantic, drive, email, github |
| Bridge mailbox | OpenISy `bridge_core/capabilities/cap.agent_bridge/` | hello/peek/send/release, leases, identity |
| Capability registry | OpenISy `bridge_core/capabilities/` (81 caps) | `Registry.list()/search()/get()` |
| Role system | OpenISy `.opencode/role_doctor/contracts.json` | 8 roles with owns/must_not/handoffs |
| L1 pipeline | OpenISy `OpenISy/packages/opencode/src/l1/` | Model-authored tools with gates V/T/P/S |
| Hook session | OpenISy `.claude/hooks/bridge_session.py` | Session lifecycle (start/beat/end) |

**Not rebuilt:** HTTP server, avatar, browser auto-open, CSP headers, LAN tier, `link/` subsystem (remote-only).

**Built from scratch:** TUI render (plans, receipts, leases), agent loop (context, tool dispatch, recovery), interactive permissions (grant/revoke).

---

## Milestones

### M0 — Agent loop prototype (1-2 days)

**Goal:** Answer the only question that matters — *does Nemotron survive a 20+ turn agent loop?*

- [ ] Python script using `Provider` + `Planner` + `Enforcer` directly
- [ ] `ScriptedProvider` for offline tests
- [ ] 10-turn loop with a multi-step intent
- [ ] Measure: tool-call validity rate, tokens/turn, recovery rate
- [ ] **Gate:** <70% valid tool calls after 10 turns → Nemotron not viable for agent loop

**Acceptance:** A script that runs 10 turns, prints a table of tool-call validity, and exits 0 if ≥70% valid.

**Rollback:** If gate fails, the TUI pivots to a simpler chat-only interface (no tool calling) — still useful, still demoable.

---

### M1 — Minimal TUI (3-5 days)

**Goal:** A TUI that feels like Pi/OpenClaw.

- [ ] `textual` or `rich` — layout: input at bottom, scroll above
- [ ] Integrate `Provider.complete()` with streaming
- [ ] Render tool calls (capability + params + result)
- [ ] Render receipts (seal, verdict, digest)
- [ ] `LoopbackRelay` + `LegacyHost` (demo-host) for testing without keys
- [ ] **Gate:** 4-step plan executes end-to-end in the TUI

**Acceptance:** `python -m isycode` opens a TUI, user types an intent, Nemotron plans, user approves, host executes, receipts render.

**Rollback:** If `textual` is too heavy, fall back to `rich` + `prompt_toolkit` — still a TUI, less pretty.

---

### M2 — Gateway integration (3-5 days)

**Goal:** The TUI can read/search/write real files.

- [ ] HTTP client for `gateway/app.py` (or direct tool calls)
- [ ] Real tool calling: `filesystem.read`, `filesystem.write`, `search`
- [ ] Interactive permissions: TUI asks ALLOW/DENY before each tool
- [ ] **Gate:** TUI reads a repo, searches a symbol, writes a file

**Acceptance:** From the TUI, read `README.md`, search for a symbol, write a new file — all through the gateway.

**Rollback:** If gateway is down, TUI falls back to `bash` commands (Canal A) — less safe but functional.

---

### M3 — Multi-agent via Bridge (optional, 1-2 weeks)

**Goal:** Multiple agents coordinated from the TUI.

- [ ] `handshake.py` hello/peek/send/release
- [ ] Leases visualized in the TUI
- [ ] **Gate:** Two agents collaborate on a task without collision

**Acceptance:** Two ISyCode instances, different roles, coordinate via bridge to complete a shared task.

**Rollback:** If bridge is unstable, TUI runs single-agent — still useful.

---

### M4 — L1 self-extension (optional)

**Goal:** The TUI can create its own tools.

- [ ] `l1_create_tool` / `l1_activate_tool` / `l1_list`
- [ ] Staging browser in the TUI
- [ ] **Gate:** TUI creates a tool, activates it, uses it

**Acceptance:** From the TUI, create a new tool, watch it pass gates V/T/P/S, use it in a plan.

**Rollback:** If L1 gates are too slow, TUI uses pre-built tools only.

---

## Dependencies

```
M0 (agent loop)
  └─ M1 (TUI)
       └─ M2 (gateway)
            └─ M3 (bridge, optional)
                 └─ M4 (L1, optional)
```

M0 is the critical path. If M0 fails, M1-M4 are moot. M1-M2 are the core value. M3-M4 are stretch goals.

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Nemotron tool-calling degrades over long loops | Medium | High | M0 gate — pivot to chat-only if <70% |
| `textual` too heavy for the use case | Low | Medium | Fall back to `rich` + `prompt_toolkit` |
| Gateway unstable / not running | Medium | Medium | Fall back to `bash` (Canal A) |
| Bridge coordination bugs | Medium | Low | Single-agent fallback |
| L1 gates too slow for interactive use | High | Low | Pre-built tools only |

---

## Success criteria

- [ ] M0: ≥70% tool-call validity over 10 turns
- [ ] M1: 4-step plan executes end-to-end in TUI
- [ ] M2: TUI reads/writes real files via gateway
- [ ] M3: Two agents coordinate without collision (optional)
- [ ] M4: TUI creates and uses a new tool (optional)

---

## Timeline

| Phase | Duration | Depends on |
|---|---|---|
| M0 | 1-2 days | — |
| M1 | 3-5 days | M0 |
| M2 | 3-5 days | M1 |
| M3 | 1-2 weeks | M2 |
| M4 | 1-2 weeks | M3 |

**Core (M0-M2):** 1-2 weeks. **Full (M0-M4):** 3-5 weeks.

---

## References

- IsyMotron: `../IsyMotron/` — provider, planner, enforcer, receipts
- OpenISy: `/home/danny/Development/ISyCo/` — bridge, gateway, roles, L1
- Hackathon: Nebius x NVIDIA Global AI Hackathon (deadline Oct 30, 2026)
