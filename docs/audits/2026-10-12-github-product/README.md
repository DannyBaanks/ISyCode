# GitHub and product documentation audit

Inspected on 2026-10-12. Scope: public repository presentation, community entry
points, documentation claims, screenshot provenance and installation. This is
not a new application security audit or release acceptance.

## Repository state inspected

- Public repository: [DannyBaanks/ISyCode](https://github.com/DannyBaanks/ISyCode).
- Default branch: `main`, fetched SHA
  `f3866098fa7addc556fbd9e3c8fa825437665aee`.
- Local implementation base: `65161a07e9df1d03c6dad4d77c04cdd001ae112e`;
  seven commits ahead of main, none behind when fetched. Documentation work
  is on `codex/readme-product`, based on that local implementation.
- The public README contained 514 lines. The local pre-edit README contained
  516 lines. Both originals are preserved in `evidence/`.
- Repository description and topics already identify the terminal-agent
  product. Homepage is unset. Issues are enabled; the inspected response had
  no open non-PR issues. Discussions are disabled; wiki is enabled.
- One open PR was returned:
  [#49, fix(tui): keep the chat tail anchored when the thinking block is focused](https://github.com/DannyBaanks/ISyCode/pull/49).
  It was used as context, not modified or submitted for review by this task.

Raw API responses are `repository.json`, `community.json`, `pulls.json`,
`runs.json`, `releases.json`, `issues.json`, `tree.json` and `readme.json` in
`evidence/`. `commands.json` records endpoint argv, timestamp and exit codes.
The public README blob was `03ddd4eb6eaa216154eb25efd512c90115d1a959`.

## Findings and treatment

| Priority | Finding | Treatment |
| --- | --- | --- |
| P1 | No root license file and GitHub license metadata is null. | Recorded for the owner to choose a project license. No license, badge or permission statement was invented. Third-party licenses do not license ISyCode itself. |
| P1 | Current local theme/copy behavior is ahead of public main. A docs-only publication would advertise UI absent from that main commit. | README captures are linked to the local implementation provenance. Publish together with the implementation after its checks/gates are resolved. No push or merge occurred here. |
| P1 | Existing green CI results do not cover this local redesign; the implementation report records an unresolved historical G8 association. | Kept the verification limits visible in a dedicated reference. No passing-suite badge, release-ready claim or gate modification. |
| P2 | The landing page mixes duplicated installation, permission matrices, test witnesses and milestones. | Replaced it with a concise product overview, one start path, practical features, screenshots and documentation links. Preserved original bytes and moved topics into the reference. |
| P2 | Public screenshots predate the accepted visual standard. | Captured current real Textual Overview, Files and grouped Settings. No AI mockup or simulated inference is presented as a running product result. |
| P2 | No issue forms or PR template in the inspected repository tree/community response. | Added local bug/feature forms and a PR template requesting reproducible behavior, environment and honest validation. These appear on GitHub only after publication. |
| P2 | Native packaging exists but the release endpoint returned no releases. | Source install is the README entry point; packaging plans and platform limits live in the reference. No dead installer/download CTA. |
| P3 | No homepage URL. | Existing repository/docs links remain usable. A hosted product site is optional and outside this edit. |

The community API's health percentage measures recognized community files; it
is not a product-quality or security score. A Code of Conduct/security contact
was not invented. Repository protection, account permissions, private
vulnerability reports and live external integrations were not evaluated.

## CI context

The inspected main workflow run
[38041667976](https://github.com/DannyBaanks/ISyCode/actions/runs/38041667976)
reported success for `f3866098fa7addc556fbd9e3c8fa825437665aee`. PR/push runs
[38101159319](https://github.com/DannyBaanks/ISyCode/actions/runs/38101159319)
and [38101150429](https://github.com/DannyBaanks/ISyCode/actions/runs/38101150429)
reported success for `c9bb088533694959dc2d5924612fc4a217c610bd`. These are
API-reported historical conclusions, not execution by this documentation task.

The workflow tests Linux on Python 3.10/3.12 and validates gates. Packaging
depends on those jobs; tagged release publication additionally requires
approved gates and matching package/tag version. Those constraints were not
weakened. The [implementation report](../../design/2026-10-11-tui-implementation/README.md)
retains the full-suite failures and exact G8 mismatch.

## Documentation and capture verification

- A fresh clone of public main installed in an isolated Linux virtual
  environment. Version/help both exited 0. No account credentials, provider
  calls or approval choices were used. See `evidence/install-command.json`
  and `evidence/install.log`.
- Captures used the current local source via `PYTHONPATH=src`, at 120×40.
  Optional catalog/Gateway probes were suppressed; configured model status
  remained local. A temporary sample Python file was listed/read through the
  actual workspace owner/receipt path. See the [capture guide](../../screenshots/2026-10-12-product/GUIA.md).
- The first invocation without `PYTHONPATH=src` loaded an older installed
  package from the existing development venv and failed on its old defaults
  signature. The corrected invocation explicitly used current source.
- A subsequent capture attempt combined `Tree.select_node` (which posts a
  read event) with an explicit awaited handler, causing duplicate selection
  and a generation race. Its assertion failed before Files was captured.
  The script now moves only the cursor, then awaits the owner handler once.
  The failed log and partial Overview are preserved; the README uses the
  successful `complete/` images only.
- SVGs were rendered with the installed system PyGObject/librsvg; the three
  final PNGs were visually inspected. This checks compositor output, not a
  physical terminal font or desktop clipboard.
- Local Markdown links, referenced images, issue-form structure and whitespace
  are checked by the task's validation script/log. The global application
  suite was not rerun for this documentation/capture-helper change.

`SHA256SUMS.txt` records the audit evidence, new reference, templates, changed
README/capture script and screenshot artifacts. Historical application reports
were preserved rather than rehashed as new test claims.

## Remaining decisions and limits

Choose the project license before advertising licensing terms. Reconcile the
existing G8 evidence association and obtain the applicable implementation CI/
release checks before publishing UI claims to main. No release, provider
certification, native-platform guarantee or public GitHub update was made by
this task.
