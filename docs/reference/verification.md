# Compatibility and verification

ISyCode is version 0.1.0 in active development. A product-oriented README does
not change release acceptance, security gates or integration evidence. This
page keeps those limits visible without making the landing page an audit log.

## What was verified for this documentation update

On 2026-10-12, a fresh clone of public main installed on Linux in a new virtual
environment; `isycode --version` and `--help` exited successfully. The current
local Textual source rendered the Overview, populated Files and grouped
Settings captures in an isolated demo workspace. File listing/preview used
the actual read owner and verified local receipts. No model inference, Gateway,
MCP tool or clipboard backend ran for those captures.

Commands, outputs, inspected remote metadata and hashes are in the
[GitHub/documentation audit](../audits/2026-10-12-github-product/README.md).
This task did not rerun the global application suite or certify another OS.

## TUI implementation evidence

The [completed native menu integration](../design/2026-10-12-mockup-e2e/REPORT.md)
records the primary-main source, native captures at three terminal sizes,
independent review, full hermetic-suite runs, real installed-command PTY startup
and isolated wheel checks. Raw failures remain preserved alongside the later
verification. Its [Spanish guide](../design/2026-10-12-mockup-e2e/GUIA.md)
explains the current menu and text gestures.

The historical G8 manifest was restored byte-for-byte to the originally reviewed
version after an independent provenance review. That correction does not approve
the current source or a release: the current strict validator still rejects
the M8 source associations. Details and negative results are in the integration
report. The [earlier TUI implementation report](../design/2026-10-11-tui-implementation/README.md)
remains a dated record of its original attempts and limits.

Physical-terminal mouse/clipboard roundtrip after the new gestures, terminal
font fallback, live services and release acceptance were NOT_DEMONSTRATED by
that implementation report. Textual SVG font rendering is not a terminal
font-setting test.

## Earlier evidence

### Native storage and Git migration, 2026-10-13

The [platform parity report](../platform-parity/REPORT.md) records native Windows
storage, ownership/DACL, process/thread exclusion, iteration/session recovery,
approved edits and Git workflow tests, plus Linux container regression runs.
The provider in the coding-flow test is simulated; filesystem/Git owners and
their receipts are real. The PowerShell source installer is also verified.
This evidence narrows the pending native Windows scope below; full product
parity, native Windows command isolation, live inference, physical clipboard
and packaged EXE behavior remain NOT_DEMONSTRATED.

## Historical verification references

These are dated records referenced by the previous README, not new runs in
this task. Inspect the original commands and hashes before making a current
claim.

| Scope | Evidence location |
| --- | --- |
| Continuity capsule/recovery with NVIDIA NIM, 2026-10-08 | [Canary evidence](../evidence/continuity-canary-2026-10-08/) |
| Local context7 server with approved/rejected calls; model simulated, 2026-10-08 | [MCP evidence](../evidence/mcp-local-live-2026-10-08/) |
| RTK compression/original output retrieval | [RTK guide and evidence](../rtk/GUIA.md) |
| Broader daily-use scope, sandbox, clipboard and provider witnesses | [Daily-use readiness](../daily-use-readiness.md) |
| Historical product feature matrix, 2026-09-28 | [Feature matrix](../product/tui-feature-matrix.md) |

The old README also reported NVIDIA coding/streaming, Pyright/TypeScript
handshakes, X11 clipboard and bubblewrap runs, plus a local Docker broker.
Their exact historical wording is retained in the
[archived README](../audits/2026-10-12-github-product/evidence/original-local-readme.txt).
They were not re-executed here and are not an all-provider/platform guarantee.

## Pending or limited coverage

- Live Gateway semantic operations with matching permission, scope and IDs;
  deployment HTTPS witnesses and M15 remote coverage.
- Real tailnet/Mobile Host sessions, streaming and approvals.
- Native Anthropic inference and native Windows product workflows.
- Recovery across providers, live 429/5xx behavior and prompt-cache savings.
- Real-page Playwright snapshot sharing with human review and evaluated fidelity.
- LSP behavior beyond the individually recorded handshake/diagnostic scope.
- Recursive directory/binary/large-file mutation beyond documented owner limits.
- Adversarial/dogfood/performance acceptance and gradual release milestones.

The [Classic/Security roadmap](../roadmap-classic-security-ux.md) and
[product roadmap](../ROADMAP.md) track acceptance. The previous README's broad
M0–M8 approval sentence must not be read as approving the current source or
a new release. No installer release was published
when the repository was inspected on 2026-10-12.
