# Visual corrections requested on 11 October

Scope: the existing approved Qt design, Conversation/Files navigation and GitHub.
The user supplied live screenshots showing a duplicate navigation destination,
an empty editor consuming chat space and a mostly empty GitHub detail pane.
The accepted targets remain `mockups/conversation.png`, `code-chat.png` and
`github-sync.png`. This is a bounded correction to existing flows, authorized
by the request and the earlier instruction to continue through completion.

## Decisions

- Conversation opens chat first and keeps history visible. An unopened editor
  is hidden. A file already opened remains available in the inspector.
- Files opens the large editor with compact chat and the file tree. Both modes
  reuse the same session, draft and editor. Their menu selection follows mode.
- GitHub shows repository metadata and recent PR, issue, commit and Actions
  samples independently of a linked local folder. Read-only gh REST requests
  reverify the owner, use a fixed host and bounded pages; failures are unknown.
- Local upstream comparison and reviewed fast-forward keep their existing
  authority and guards. Activity never makes Pull available by itself.
- Replace custom shell icons with licensed official Tabler outline assets.
  Keep the supplied cat logo. Use Lato (installed here) with Qt fallback.
- Add unchanged, attributed vscode-icons SVGs for file types and a shared
  dependency-free identity mapping for literal ASCII TUI labels. Do not install
  fonts or change global editor configurations. Package licenses and provenance.
- Reduce excessive empty panels, improve typography, useful row density and
  rounded controls; group approvals on charcoal surfaces with cyan borders.

## Native workflow rulings

Product Design audit/image-to-code/design-qa are applied to the existing native
Qt product. Web scaffolding, cloud browser, deployment and share prompts do not
apply. Current screenshots supplied by the user are the audit baseline; source
renders are real Qt widgets with private fixture state. Account access in those
renders is replaced at the network boundary and is never a real account claim.
No new generated visual alternatives or raster assets are needed. The approved
design and explicit corrections provide the design authorization; no additional
brainstorming approval gate is imposed. Tests are authorized by the supplied
root AGENTS §12 and the user's audit/correction request.

## Acceptance

Distinct destinations, unchanged drafts/session, no empty editor in initial
Conversation, remote activity without local link, explicit unknown/partial and
bounded sample states, safe fixed-host links, unchanged Git sync safeguards,
same-viewport native captures and a visible comparison to the selected targets.
No deletion, reset, pull, push or credential/configuration changes are needed.

## API sources

Official documentation consulted: [repository metadata](https://docs.github.com/en/rest/repos/repos),
[pulls](https://docs.github.com/en/rest/pulls/pulls),
[issues](https://docs.github.com/en/rest/issues/issues),
[Actions runs](https://docs.github.com/en/rest/actions/workflow-runs).
The issues endpoint includes PRs; these are filtered from the issue sample.
Lists are recent samples of at most 30, never claimed as aggregate totals.
[Tabler](https://github.com/tabler/tabler-icons) provides the licensed outline
icons; original SVG bytes, commit and hashes live in `ui/assets/tabler/`.
