# Filtered project view and agent lifecycle

## User findings

The native session screenshots show a recursive `glob("**/*")` running with
`/home/danny` as the project root, an undifferentiated working indicator, and
repeated stop requests. The source used synchronous recursive glob collection
inside an async method. This can prevent its event loop from accepting cancellation.
The screenshots alone do not establish the complete cause of the reported UI freeze.

## Implemented source changes

- `core/project_tree.py`: cooperative, bounded directory snapshots with relative
  paths, ASCII file types, listing version, pagination and explicit partial flags.
- The Qt tree, native file search, project snapshots and discovery tools share
  the visible-name filter; discovery does not follow symlinks.
- The agent receives an initial root snapshot through existing host tool authority.
  `project_tree` expands directories; broad glob requests return an identified
  nonrecursive snapshot. Specific glob patterns retain bounded matching.
- `grep` is now literal text search with bounded files, lines and output. This
  deliberately changes its former regex behavior and is documented in GUIA.md.
- The chat receives tool cards, not artificial machine summaries appended to
  streamed assistant prose. The native tool event retains compact discovery metadata.
- Live provider deltas still drive text streaming. Native Markdown rendering is
  coalesced at 50 ms; progress notifications are limited to four per second per phase.
- Provider wait/activity, incoming text/tool arguments, executing tool, approval
  wait and stopping are distinct states. Quiet elapsed time is not proof of thinking.
- Cancellation is idempotent, reports an interrupted tool and preserves partial
  responses. Glob traversal yields regularly instead of building an unbounded list.
- A persistent toolbar tree button restores the minimized explorer.
- Both the GUI and agent reject home or filesystem root as a project for model turns.

## Authority and limits

The view is context curation, not an OS isolation boundary. It does not bypass
PLAN, disabled tools, path checks, policy, immutable file review or exact command
approvals. Each directory view is live; its version describes the listing, not
file contents. It is not a capture of the exact expanded viewport in Qt.
File contents require an explicit read. Partial/omitted discovery is reported.
Original account settings, history, workspaces and installed historical images
are preserved. RTK is not bundled or copied; optional command-output compression
is a separate future adapter under existing command authority and evidence rules.

## Acceptance still pending

Source syntax and packaging are checked separately from behavior. No automated
regression tests or live provider calls were run for these changes.

Manual E2E must establish:

1. Select a concrete project; compare its visible root with the supplied snapshot.
2. Expand a folder and paginate; partial flags/version changes remain explicit.
3. A broad glob returns a shallow snapshot instead of a recursive inventory.
4. Source, caches, dependencies and symlinks follow the documented discovery filter.
5. Receive actual Nemotron text incrementally and observe each agent phase.
6. Stop during generation/discovery/approval; preserve partial text and regain control.
7. Minimize and restore the explorer from the toolbar without switching views.
8. Recheck existing proposal, command grant and cross-project persistence behavior.

Runtime correctness, freeze resolution and visual regression: **NOT_DEMONSTRATED**.
