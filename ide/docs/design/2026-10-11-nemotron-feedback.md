# Provider output, repeated discovery and safe diagnostics

## Observed evidence

Human screenshot at 2026-10-11 12:47 local; read-only inspection of the selected
nemotron-e2e conversation database. Root snapshots returned entries=[], next_offset=null,
truncated=false with identical version 4f53cda18c2baa0c. The model repeatedly requested
project_tree/broad glob, an absent README and excluded .git, then limit=200 despite
schema maximum=100. run_command was denied by PLAN, not executed. The turn was failed.
The legacy worker suppressed every exception; the final exception/HTTP status is
NOT_DEMONSTRATED. Do not retrospectively call it a timeout or malformed SSE.

## Changes

- Explicit empty-visible-directory advice; no claims about hidden files.
- Three identical discovery pages in one turn trigger a final response request without
  tools. Mutating successes reset counts; changed versions/pages differ. No unlimited
  retry or argument repair. A provider ignoring the final request cannot execute new tools.
- Display only returned string reasoning_content/reasoning, separate from answer/tool
  arguments. Source: https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b/build
- Qt coalesces reasoning delivery at 100 ms and bounds its view to 32 KB UTF-8. Foldable,
  plain text viewport avoids rich text links/execution. Normal Copy excludes reasoning.
- One bounded reasoning event is stored at normal turn closure, independent of wire
  history; replay appears after transcript. Abrupt process death remains a limitation.
- Safe allowlisted codes for HTTP status, transport, timeout, token exhaustion, invalid
  tool arguments, incomplete stream. No exception bodies/URLs/locals are persisted.
- Diagnostic event records phase/step and relative core frame locations; old failures
  remain unknown. No account inference/configuration changes or token-budget increase.

## Delivery scope

No automated tests or model calls. Static syntax/diff inspection and additive package
build only. Live provider, loop-finalization, cancellation persistence, restoration and
visual regression are NOT_DEMONSTRATED pending the user's E2E. Historical tests do not
validate this change. Packaging/install manifest is under docs/verification/nemotron-feedback-*.
