# ISyCode resume — 2026-10-03

Recovered the runtime WIP after the interrupted session. The headless JSON now includes explicitly estimated context and unknown cost; the TUI status shows the same distinction. The compact header is `:3_ ISYCODE`, as requested, with the workspace mode aligned to the right. The existing startup landscape remains the only hero.

## Local command guide

Run from the configured workspace:

```sh
isycode models --json
isycode dirs --json
isycode sessions list --json
isycode sessions search parser --json
isycode stats --json
isycode completion bash
isycode -p 'Summarize this workspace' --json
isycode -p 'Answer without workspace tools' --no-tools --json
```

`models` and `dirs` inspect local metadata, without a provider request. Session inspection and stats use the existing session owner and scoped grants. A missing grant returns exit 3. `--no-tools` removes tool exposure; it grants nothing. `--offline -p` exits visibly with code 1 before constructing a provider. JSON headless output includes `events`, `usage`, `context` and `cost`; unknown cost is `{"status":"unknown"}`, never a fabricated zero. `/compact instructions` accepts an optional compaction preference. A configured small-model slot remains metadata and still needs the ordinary provider grant.

Dry-run is a Python request-preview API (`isycode.dry_run.preview_request`), not a new CLI switch: ALLOW=0, DENY=3, ASK=4. It performs no effect, writes no journal and consumes no approval. HTML export is the local `ChatSessionStore.export_html` API, with escaped and sanitized text; no upload action is implied.

## Visual provenance

Read `/home/danny/Development/CLI-TUI/isycode-tui-visual-handoff-codex.md`, verified SHA-256 `024fe4970768584060dc6b54fddffe0c2219a95541057ca245c7717052756ddd`. Its broader visual phases remain pending; this commit delivers only the compact header and context/cost status integration. No external art or runtime dependency was imported. Full NO_COLOR support is NOT_DEMONSTRATED.

Captures: `/tmp/isycode-cat-{80x24,100x30,120x40,140x40}.svg` from Textual `run_test` with fixture configuration. These are ephemeral local review artifacts. ImageMagick did not faithfully rasterize Rich SVG text; use the SVG directly.

## Verification

Initial suite: 1244 passed, 6 skipped, one stale coverage-snapshot failure. The regenerated snapshot and 15 visual tests passed. Context/cost/dry-run/inspection/runtime tests: 26 passed. Subsequent visual/layout/session set: 29 passed. A later full run had five intermittent fake-provider test failures; their module alone passed 16 tests. The fixture now supplies a public resolver result instead of relying on live DNS, retaining the real egress policy. Final suite evidence is recorded separately after completion.

The research roadmap additions and earlier audit/handoff documents remain separate WIP. No security gate or full roadmap is declared complete.

Final verification: `PYTHONPATH=src pytest -q -p no:cacheprovider --tb=short`, exit 0: **1245 passed, 6 skipped, 8 warnings in 168.19s**. Raw output: `codex-resume-2026-10-03-pytest.log`, SHA-256 `818ea07fad5893a8cf5be62aed94c3c4b2d399e4a29b5ffe04227c93401fd838`. Warnings are the existing multiprocessing fork-from-thread deprecation. `python3 scripts/validate_gates.py`: exit 0, historical evidence checked, no gate approved. `git diff --check`: exit 0.
