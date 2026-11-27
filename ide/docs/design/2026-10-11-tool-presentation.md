# Deterministic native tool presentation hook

## Scope

User requested readable actual-result cards rather than raw argument JSON. The native
presentation hook is ui/tool_presentation.py, a pure formatter with no filesystem,
provider or authority calls. It maps known real tool results into bounded plain-text
Spanish titles/summaries/status. Argument descriptions while running are not evidence
of completion. Unknown payloads fall back to Details; failed results never become PASS.

ObservableAgent attaches presentation metadata before existing stdout/stderr UI clipping.
Both chat and ToolsPanel consume it; raw arguments and existing clipped outputs remain
available in Details with explicit clipping flags. Model wire results and host journals
are unchanged. Filenames preserve case and QLabel summaries use PlainText.

ProjectView now distinguishes missing directory from existing non-directory so the UI
can say no encontrada based on a real runtime result. Resident summaries report recorded
references, not on-disk existence. No new project scan, automatic permission or model call.

## Verification boundary

AST parsing, git diff --check, additive PyInstaller/AppImage packaging and source/package
hash checks. No automated tests. Actual GUI/Nemotron behavior and visual regression are
NOT_DEMONSTRATED pending human E2E. Prior screenshots show the earlier release only.
