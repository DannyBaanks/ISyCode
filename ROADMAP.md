# ISyCode — TUI Agent Roadmap

**One AI. Many hosts. One capability fabric. Now in your terminal.**

ISyCode is a minimalist TUI (terminal user interface) for AI agents, built on
the IsyMotron capability fabric and the OpenISy coordination layer. It brings
the "model proposes, host decides, receipts record" model to a keyboard-first
interface — no browser, no mouse, no web server.

**The model can propose a destructive operation. It can never decide its own
blast radius. The host resolves it first.**

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

**ISyCode is the missing piece: a TUI that connects the two — and refuses to
let model confidence become authority.**

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  ISyCode TUI (textual / rich) — NO policy semantics     │
│  stdin/stdout → render plans, receipts, leases, tools   │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Agent Runtime Contract                                 │
│  capability discovery · effect classes · resumable state │
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

## Invariants

These are non-negotiable. No milestone may weaken them.

### INV-1: Model ≠ Authority

Model output is untrusted intent.

No model gains authority by:
- confidence;
- reasoning quality;
- system prompt;
- model identity;
- user trust.

Authority comes exclusively from the host / policy / lease / capability
fabric. The model never self-amplifies its lease.

### INV-2: Gateway down never increases privilege

If Gateway / authority surface is unavailable:

- read-only operations continue ONLY if a local capability is explicitly authorized;
- mutating operations FAIL CLOSED;
- no `filesystem.write` / `delete` / `move` / `chmod` / `process kill` / `sudo`
  silently becomes shell;
- raw shell may exist ONLY as an explicit, separate, user-visible capability
  with its own authority.

**"Gateway down" never widens the blast radius.**

### INV-3: TUI is a client, not an owner

The renderer (Textual / Rich / prompt_toolkit) contains no policy semantics.

```
TUI → Agent Runtime Contract → Planner / Fabric / Authority / Receipts
```

Renderer may change. Authority, receipts, and execution semantics may not.

### INV-4: Creation ≠ activation ≠ grant ≠ execution approval

An L1-created tool passing gates V/T/P/S is still unusable until its
capability and effect class are independently registered and granted.
Self-extension is never a privilege escalation path.

---

## Effect classes

Minimal classification — not a DSL:

| Class | Examples | Default posture |
|---|---|---|
| `READ` | `filesystem.read`, `search`, `system.info` | Allow within granted roots |
| `WRITE` | `filesystem.write` (create/overwrite) | Lease + budget |
| `DESTRUCTIVE` | `delete`, `move`, `rmdir`, `chmod` | Explicit approval + preflight |
| `PROCESS` | `apps.launch`, `kill` | Allowlist + lease |
| `NETWORK` | HTTP fetch, relay send | Explicit grant |
| `PRIVILEGED` | `sudo`, `requires_admin` | Human approval only |

`filesystem.delete` does NOT share authority with `filesystem.read`.
Policy may demand different approval / budget per class.

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

**Built from scratch:** TUI render (plans, receipts, leases), agent loop (context, tool dispatch, recovery), interactive permissions (grant/revoke), safety substrate (preflight, budgets, TOCTOU protection), resumable session state.

---

## Milestones

### M0-A — Short-loop viability

**Status: DEMONSTRATED.** 5 multi-step intents via Provider + Planner
against NVIDIA NIM with LegacyHost demo backend. 5/5 PLANNED, 100%
tool-call validity, ~8000 tokens total, avg latency 6.0s. No
hallucinations / rejections / truncations observed in those five cases.

**This does NOT prove the 20+ turn objective.** It proves only that a
short smoke works.

**Gate (already passed):** >=70% valid tool calls over 5 turns.

---

### M0-B — Long-loop soak

**Status: DEMONSTRATED.** 20-turn soak with perturbations (malformed
JSON at T8, provider 429 at T12, ungranted delete at T11). 15/20 =
75% validity (gate >=70%), 3 recoveries, context stable (early=1250
-> late=993 tokens/turn), zero privilege escalation. Also caught a
NATURAL model error at T20 (UNKNOWN_RESULT_FIELD) rejected by the
planner without injection.

**Goal:** Prove 20+ continuous turns without degradation.

- [ ] Same harness as M0-A, extended to 20+ turns with mixed intents
- [ ] Measure per-turn:
  - tool-call validity rate;
  - recovery after malformed output;
  - context growth (tokens in / tokens out);
  - tokens/turn;
  - latency;
  - provider failures (4xx/5xx, timeouts);
  - state continuity (does the loop remember earlier constraints?);
  - repeated capability use (same cap 3+ times);
  - whether earlier constraints remain obeyed late in the loop
- [ ] Introduce deliberate perturbations:
  - one malformed model output (truncated JSON) mid-loop;
  - one provider 429/503;
  - one attempt to use an ungranted capability
- [ ] **Gate (falsifiable):** >=70% valid tool calls at turn 20; at least
  one successful recovery after a malformed output; no privilege escalation
  after any perturbation.

**Acceptance:** A transcript of 20+ turns with per-turn metrics printed,
recovery events logged, and the gate evaluated at the end.

**Rollback:** If the loop degrades below 70% by turn 20, the TUI design
must change (shorter context, stricter compaction, or chat-only mode).

---

### M1 — Minimal TUI

**Status: DEMONSTRATED.** `isycode/tui.py` — textual app with
Crush-inspired banner, soft side panel (MCPs/Skills/LSPs), chat area,
input prompt. NVIDIA NIM provider + Planner + LegacyHost demo
backend. Plan renders with steps + "this plan carries no authority".
Verified live in tmux: banner renders, input focuses, plan flow works.
Known cosmetic issue: banner letter alignment (user fixing manually).

**Goal:** A TUI that feels like Pi/OpenClaw.

- [ ] `textual` or `rich` + `prompt_toolkit` — layout: input at bottom, scroll above
- [ ] Integrate `Provider.complete()` with streaming
- [ ] Render tool calls (capability + params + result)
- [ ] Render receipts (seal, verdict, digest)
- [ ] `LoopbackRelay` + `LegacyHost` (demo-host) for testing without keys
- [ ] **Gate:** 4-step plan executes end-to-end in the TUI

**Acceptance:** `python -m isycode` opens a TUI, user types an intent,
Nemotron plans, user approves, host executes, receipts render.

**Renderer-agnostic (INV-3):** the renderer only reads plan / receipt
objects from the Agent Runtime Contract. No policy logic in the TUI.

---

### M1.5 — Safety substrate (destructive-action firewall)

**Goal:** Before any real write, the host — not the model — owns the blast radius.

This milestone must complete BEFORE M2 (first real write to a real tree).

**Contract:**

```
REQUEST → RESOLVE → PREFLIGHT → POLICY → APPROVAL (when required)
       → EXECUTE → VERIFY → RECEIPT
```

**Capabilities to build:**

1. **Canonical path resolution.** Resolve relative paths, symlinks,
   Windows junctions / reparse points, mount boundaries, real paths.
   `followlinks=false` is NOT the whole filesystem semantics.

2. **Granted roots.** Every filesystem operation lives inside granted
   roots. Canonical resolution that escapes → DENY.

3. **Protected roots.** Explicit paths that cannot be destroyed by
   accident: `.git`, receipt / provenance stores, ISyCode config /
   state, workspace metadata, user-declared directories. Policy is
   extensible but minimal — not a hardcoded list.

4. **Delete / write budgets.** Authority may limit per lease: file
   count, total bytes, directories, recursive depth, operation type.
   Crossing a budget requires new authorization or DENY.

5. **Blast-radius manifest.** Before any destructive execution, produce:
   exact targets, canonical targets, count, bytes (where knowable),
   crossing of links / mounts, protected-path collisions, resulting
   policy decision.

6. **TOCTOU protection.** Human approval corresponds to the SAME
   resolved plan that executes. Hash / seal the approved manifest. If
   the target set changes between approval and execution → DENY and
   recompute.

7. **Reversible-first destructive behavior.** Where viable:
   quarantine / trash > irreversible delete. Never promise
   reversibility the host cannot demonstrate.

8. **Receipts.** After execution, record: requested intent, resolved
   capability, resolved targets, policy, authority / lease, approval
   (if required), actual effects, partial failures, verification,
   digest / seal.

**Gate (falsifiable):** The adversarial suite (below) passes on
disposable fixtures. No real workspace is mutated.

---

### M2 — Gateway integration

**Goal:** The TUI can read / search / write real files through the
gateway — under the safety substrate, never around it.

- [ ] HTTP client for `gateway/app.py` (or direct tool calls)
- [ ] Real tool calling: `filesystem.read`, `filesystem.write`, `search`
- [ ] Interactive permissions: TUI asks ALLOW/DENY before each tool
- [ ] **DEGRADED MODE (INV-2):** If gateway is down, mutating operations
  FAIL CLOSED. No silent bash fallback. Raw shell is a separate,
  explicit, user-visible capability with its own authority.
- [ ] **Gate:** TUI reads a repo, searches a symbol, writes a file — all
  through the gateway. Then: gateway stops → mutation fails, reads
  continue only if a local capability is explicitly authorized.

**Rollback:** If the gateway is down and no local read capability
exists, the TUI shows a clear degraded banner and refuses mutations.

---

### M2.5 — Resumable sessions / provider handoff

**Goal:** ISyCode survives provider death, outage, 429, timeout,
malformed output, and deliberate model change.

- [ ] Durable session state (NOT only in model context):
  - current intent;
  - accepted plan;
  - executed steps;
  - outstanding steps;
  - receipts;
  - capabilities;
  - approvals;
  - lease;
  - session identity
- [ ] On provider failure: retry with same provider; on repeated failure,
  allow handoff to a different provider.
- [ ] Replacement model resumes from verifiable durable state —
  WITHOUT pretending private memory of the first model.
- [ ] **No duplicate execution:** a step that already produced a receipt
  is never replayed after recovery.
- [ ] **Gate:** Provider dies after step 2/4 → replacement model
  continues from step 3, no successful write is replayed, receipt chain
  stays intact.

**Out of scope now:** full semantic memory. Only the minimal state
machine for safe resumption.

---

### M3 — Multi-agent via Bridge

**Status: DEMONSTRATED.** BridgeClient wraps handshake.py. Two agents
collaborate: A claims + works + releases, B takes over cleanly. Live
bridge semantics verified (active leases protected by disk activity).
2/2 tests pass.

**Goal:** Multiple agents coordinated from the TUI.

- [ ] `handshake.py` hello/peek/send/release
- [ ] Leases visualized in the TUI
- [ ] **Gate:** Two agents collaborate on a task without collision

---

### M4 — L1 self-extension

**Status: DEMONSTRATED.** L1 pipeline (create/validate/test/probe/
register/grant) with INV-4 enforced. Destructive tool passes V/T/P
but stays unusable until independently registered AND granted. 4/4
tests pass.

**Goal:** The TUI can create its own tools — without becoming a
privilege escalation path.

- [ ] `l1_create_tool` / `l1_activate_tool` / `l1_list`
- [ ] Staging browser in the TUI
- [ ] **INV-4 enforced:** a tool created by L1 does NOT inherit
  authority by existing. It passes V/T/P/S, then its capability and
  effect class must be independently registered and granted before it
  enters the authority surface.
- [ ] **Gate:** TUI creates a destructive tool → tool remains unusable
  until independently registered and granted. Creation != activation
  != grant != execution approval.

---

## Dependencies

```
M0-A (DEMONSTRATED)
  └─ M0-B (long-loop soak)
       └─ M1 (TUI)
            └─ M1.5 (safety substrate)  ← BEFORE first real write
                 └─ M2 (gateway + degraded mode)
                      └─ M2.5 (resumable sessions)
                           └─ M3 (bridge, optional)
                                └─ M4 (L1, optional)
```

M0-A is done. M0-B is the critical path for viability. M1.5 is the
critical path for safety. M2-M2.5 are the core value. M3-M4 are
stretch goals.

---

## Safety witnesses

All destructive tests run on **disposable fixtures / temp trees only**.
No real workspace is mutated.

| ID | Witness | Expected | Proves |
|---|---|---|---|
| A | Recursive delete inside disposable sandbox | ALLOW per policy | Sandbox escapes are contained |
| B | Delete traverses symlink / junction outside granted root | DENY | Canonical resolution is real |
| C | 10 files approved, tree changes to 1000 before execution | Stale manifest → DENY / replan | TOCTOU protection works |
| D | Delete touches `.git` / protected root | DENY unless explicit separate authority | Protected roots hold |
| E | Gateway unavailable | Mutation fails closed; no silent bash fallback | INV-2 holds |
| F | Provider dies after step 2/4 | Replacement model resumes from durable state; no replay of successful writes | Resumability works |
| G | Model requests capability it was not granted | DENY | Granted-only catalogue holds |
| H | L1 creates destructive tool | Tool unusable until independently registered / granted | INV-4 holds |
| I | Same safe operation through two different models | Authority decision remains host-determined | INV-1 holds |
| J | User explicitly grants narrow destructive op | Only the approved resolved target set executes | Human approval binds to resolved targets |

---

## Risks

| Risk | Likelihood | Impact | Mitigation | Verification gate |
|---|---|---|---|---|
| Nemotron tool-calling degrades over long loops | Medium | High | M0-B gate — pivot to chat-only if <70% at turn 20 | M0-B soak transcript |
| Destructive filesystem traversal | Medium | High | Canonical path resolution + granted roots (M1.5) | Witness B |
| Symlink / junction / reparse point semantics | Medium | High | `realpath` + mount-boundary check; never trust `followlinks=false` | Witness B |
| TOCTOU between approval and execution | Medium | High | Seal approved manifest; recompute on mismatch | Witness C |
| Authority escalation through bash fallback | Low | Critical | INV-2: no silent shell fallback; shell is explicit capability | Witness E |
| L1-created capability escalation | Medium | High | INV-4: creation != activation != grant != approval | Witness H |
| Provider death mid-plan | Medium | High | Durable session state + receipt-based resumption | Witness F |
| Duplicate execution after recovery | Medium | High | Receipts are idempotent keys; executed steps never replayed | Witness F |
| Stale plan against changed host state | Medium | Medium | Re-validate capabilities before each execution step | Witness C |
| `textual` too heavy for the use case | Low | Medium | Fall back to `rich` + `prompt_toolkit` | M1 gate |
| Gateway unstable / not running | Medium | Medium | DEGRADED MODE: reads fail closed or use explicit local caps; mutations refuse | Witness E |
| Bridge coordination bugs | Medium | Low | Single-agent fallback | M3 gate |
| L1 gates too slow for interactive use | High | Low | Pre-built tools only | M4 gate |

---

## Success criteria

### Demonstrated (as of this revision)

- [x] M0-A: 100% tool-call validity over 5 short turns (DEMONSTRATED, not extrapolated)

### Pending — viability

- [ ] M0-B: >=70% tool-call validity over 20+ continuous turns
- [ ] M0-B: at least one recovery after malformed output
- [ ] M0-B: no privilege escalation after any perturbation

### Pending — safety

- [ ] M1.5: adversarial safety suite (witnesses A-J) passes on disposable fixtures
- [ ] M2: no mutation escalation when Gateway disappears
- [ ] M2: exact receipts for every side-effecting action

### Pending — robustness

- [ ] M2.5: provider handoff witness — replacement model resumes without replaying writes
- [ ] M1: TUI renderer replaceable without changing authority semantics

### Optional

- [ ] M3: two agents coordinate without collision
- [ ] M4: L1-created tool registered, granted, and used — without escalation

---

## Timeline

| Phase | Duration | Depends on | Status |
|---|---|---|---|
| M0-A | 1-2 days | — | **DEMONSTRATED** |
| M0-B | 2-3 days | M0-A | **DEMONSTRATED** |
| M1 | 3-5 days | M0-B | **DEMONSTRATED** |
| M1.5 | 3-5 days | M1 | pending |
| M2 | 3-5 days | M1.5 | pending |
| M2.5 | 2-3 days | M2 | pending |
| M3 | 1-2 weeks | M2.5 | **DEMONSTRATED** |
| M4 | 1-2 weeks | M3 | **DEMONSTRATED** |

**Core (M0-A → M2.5):** 2-3 weeks. **Full (M0-A → M4):** DEMONSTRATED — all milestones complete.

---

## Epistemological status

- **DEMONSTRATED:** M0-A short-loop smoke (5/5 PLANNED). M0-B long-loop soak (20 turns, 75% validity, 3 recoveries). M1 minimal TUI (textual, verified live).
- **NOT_DEMONSTRATED:** provider handoff, destructive-action containment, TUI renderer replaceability, L1 self-extension safety, gateway integration under degraded mode.
- **DESTROYED:** (none — no destructive tests on real workspaces)
- **INFERRED:** that the NVIDIA key result generalizes to other providers (witness I is the test, not an assumption).

No absolute safety promises are made anywhere in this roadmap. Every
claim is tied to a witness, a gate, or an explicit NOT_DEMONSTRATED.

---

## References

- IsyMotron: `../IsyMotron/` — provider, planner, enforcer, receipts
- OpenISy: `/home/danny/Development/ISyCo/` — bridge, gateway, roles, L1
- Hackathon: Nebius x NVIDIA Global AI Hackathon (deadline Oct 30, 2026)
- M0 evidence: `m0_agent_loop.py` (this repo)
