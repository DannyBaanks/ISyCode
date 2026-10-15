# Installation and updates

ISyCode is a Python/Textual terminal application. The supported entry point is
the `isycode` command. Open it from the directory you want to work in.

## Install from source

Python 3.10 or newer and Git are required. A fresh clone of public `main`,
editable installation, `--version` and `--help` were executed on Linux on
2026-10-12; the [raw installation log](../audits/2026-10-12-github-product/evidence/install.log)
records that run. It did not call a model provider.

```bash
git clone https://github.com/DannyBaanks/ISyCode.git
cd ISyCode
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
isycode
```

The native Anthropic adapter is an optional extra:

```bash
python -m pip install -e '.[anthropic]'
```

The main install includes Textual 8.2.8. Keep the virtual environment active
when launching from another project. The repository also supplies
`scripts/install-path` for installing its launcher on your user PATH; see the
[user guide](../GUIA.md) for that workflow.

## First workspace

Choose a recurring or temporary workspace and Classic or Security. A recurring
workspace can create `.isyroot` and save conversations; a temporary workspace
is intended for a single session. The marker identifies the logical boundary,
not permission to access its contents. Quick Start and Custom setup offer
different onboarding paths. Cancelling setup with Esc uses Security.

Select a provider under Settings → Conversation → Providers & models.
Credentials and workspace permission are separate. See [provider setup](workflows.md#providers-and-models).

## Local dependencies

Read/edit/chat workflows and sandboxed command execution have different
requirements. Linux sandboxed commands require bubblewrap, libseccomp and
Python. ISyCode leaves command execution unavailable when isolation is missing;
there is no unrestricted-shell fallback.

`isycode doctor` inspects local dependencies and configuration without network
calls. `isycode dirs` shows config/state locations and their precedence without
showing credentials. Optional LSP, MCP and RTK runtimes have their own
requirements.

The terminal controls the font and size. The accepted comparator preference
is Ubuntu Sans Mono, Unicode, 14 CSS px and line-height 1.3; Textual does not
set terminal font preferences or translate that CSS size to terminal points.
Use ASCII display if glyphs are unavailable and reduced motion for static
activity indicators.

## Launcher surface

| Command | Purpose |
| --- | --- |
| `isycode` / `isycode tui` | Open the TUI in the current directory |
| `isycode -p "question"` | Answer once, then exit; read-only granted tools only |
| `isycode cli` | Browse actions by purpose; it does not execute arbitrary shell |
| `isycode doctor [--json]` | Inspect local dependencies/configuration |
| `isycode dirs [--json]` | Inspect state/config locations |
| `isycode models [--json]` | Inspect local provider/model metadata |
| `isycode sessions ...` | Inspect and manage saved conversations |
| `isycode stats [--json]` | Aggregate locally recorded usage |
| `isycode completion SHELL` | Print bash, zsh or fish completion |
| `isycode --help` / `--version` | Show help or installed version |

## Update

`isycode update` (alias `isycode actualizar`) discovers the installation from
the program location. It can update a checkout or prepare a user installation.
Only the canonical `github.com/DannyBaanks/ISyCode` remote is accepted; forks
are rejected before fetching.

- `--check` checks without installing or advancing the branch.
- `--yes` pre-approves a stash/merge confirmation. Without an interactive
  terminal, the default is no unless this flag is present.
- If the only conflict is `docs/security/m15-authority-coverage.json`, the
  updater regenerates it. Other conflicts stop the update.

## State and packages

Recurring conversations live outside the checkout, normally under
`~/.local/state/isycode/`, respecting `$XDG_STATE_HOME` and the application
state override. Preferences/configuration normally live under
`~/.config/isycode/`. Credentials use the system keyring.

The [GitHub releases endpoint](https://github.com/DannyBaanks/ISyCode/releases)
returned no releases when audited on 2026-10-12. Install from source rather
than relying on a downloadable installer.

CI contains packaging targets for Windows x64 console EXE, Linux x64 AppImage
and Debian package, and macOS ARM64 PKG/tarball. Tag version matching, tests and
gate review constrain release publication. Packaging code is not proof of a
published or supported native product. macOS notarization and native Windows
product behavior were not demonstrated in this documentation task.
