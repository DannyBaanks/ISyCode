# ISyCode repository guidance

- ISyCode is the active project in this repository. Do not attribute its code, roles, or behavior to OpenISy.
- ISySentinel is ISyCode's deny-by-default decision layer. It aggregates read-only Systembility results; it never executes actions or mutates requests.
- Workspace Authority is separate from Sentinel and owns explicit per-`.isyroot` grants. `.isyroot` defines only the maximum logical sandbox boundary; it never grants access.
- Each workspace runs in Security mode (everything off until explicitly granted) or Classic mode (a fixed Workspace Authority preset for workspace coding: read/edit, chosen provider, saved sessions/keys, Git review/approved commits, and exact-executable sandboxed commands when available). Classic never bypasses IsySentinel, execution owners, per-action approvals or the action journal, and never implies integrations or explicitly denied actions.
- Execution owners/adapters perform an action only after Sentinel returns ALLOW, then report verified outcomes. Roles, injected context, provider credentials, Gateway keys, MCP scopes, and Bridge leases are not workspace grants.
- IsyMotron may be an optional runtime/provider integration, but it is not ISyCode's security authority. Do not require or modify its policy semantics for ISyCode security.
- The ISyCo Gateway HTTP Sentinel is a separate remote perimeter: it validates API keys, operation allowlists, expiry/status, and rate limits. For Gateway calls, both local ISyCode authority/Sentinel and the Gateway's own request validation must pass.
- The ISyCo Bridge is optional, opt-in coordination. A lease is a traffic light between peers, not authorization. Do not start a Bridge daemon.
- When using the Bridge, call `bridge_core/capabilities/cap.agent_bridge/handshake.py`; do not edit `workspace/agents/bridge/` files directly. Keep identity and lease tokens in process memory and never print them in chat or logs.
- Preserve unrelated user changes. Inspect repository state before editing and keep changes scoped to the requested work.
- Do not claim that commands, tests, integrations, or external services ran unless they actually ran.

## ISyCode Design Skills

- Before adding or changing ISyCode TUI screens, menus, panels, icons or text gestures, read [.agents/skills/isycode-design/SKILL.md](.agents/skills/isycode-design/SKILL.md), then only the component skill relevant to the task. The catalog is [.agents/skills/isycode-design/references/catalog.json](.agents/skills/isycode-design/references/catalog.json).
- Follow the accepted visual direction and shared tokens unless the current user request changes them. The skills distinguish design targets from demonstrated runtime behavior; publishing a standard does not implement it or close an audit finding.
- These skills guide development of this Textual repository. They do not modify terminal preferences, grant runtime authority or automatically enter the separately pinned application skill bundle.

## Classic/Security evolution gates

- For changes advancing Classic autonomy, Security policy, or the associated UX, follow [the executable roadmap](docs/roadmap-classic-security-ux.md). Its target does not describe current behavior: the per-action approval rule above remains the baseline until the applicable gates authorize a tested transition.
- Do not advance dependent milestones or release affected capabilities with failed, missing, or reopened prerequisites. Preserve evidence and user work; document publication is not gate completion. These are procedural requirements today; automated CI enforcement is a pending roadmap deliverable.

## Cross-repo agent briefing registry

- Before a large refactor, audit, or when planning work that touches the TUI architecture, read the private registry [DannyBaanks/vicios-tecnicos](https://github.com/DannyBaanks/vicios-tecnicos) (clone it with `gh repo clone DannyBaanks/vicios-tecnicos` if not present locally). It holds dated, evidence-backed briefings per repo — for ISyCode start with `briefings/isicode/2026-10-16-post-remediacion-v0.md`.
- The registry maps where code lives after the V0 remediation (M0–M10, commits `f73ead1`..`86aee1d`), which patterns are known debt, and which decisions are pending. A briefing describes a moment in time: verify against the working tree before citing it, and update the registry when your session materially changes the picture.
- Additions to the registry are commits like any other repo: honest, dated, with evidence.
