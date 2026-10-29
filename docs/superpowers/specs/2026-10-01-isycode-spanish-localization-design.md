# ISyCode Spanish-First Localization

## Status

Design approved in conversation on 2026-10-01; this document is awaiting user
review. No implementation is authorized until this written specification is
approved.

## Goal

Make Spanish the default language for the ISyCode CLI/TUI and active official
documentation, while offering English as a selectable interface language and
maintaining English copies of official user documentation as a secondary
reference. Use IntentLang to propose and evaluate translations, and repair only
its demonstrated translation and verification defects before relying on its
output.

## User intent and terminology

- Spanish is the default interface and the primary language of official active
  documentation.
- English is selectable in the interface and remains available as a secondary
  copy of official user documentation.
- Product and brand names remain unchanged, including ISyCo, ISyCode,
  ISySentinel, Workspace Authority, Bridge, Gateway, and IsyMotron. Branded
  feature names such as `Authority & Security` remain intact.
- Generic interface labels are translated: for example, `Settings` becomes
  `Configuración` and `Context` becomes `Contexto`.
- Slash commands, shell commands, option flags, provider/model identifiers,
  protocol names, paths, environment variables, code, and machine-readable
  output retain their exact syntax. Explanatory prose around them is Spanish in
  Spanish mode.
- Prose comments and docstrings in ISyCode source are Spanish. Literal command
  examples, identifiers, and protocol text embedded in them retain their exact
  spelling.
- Chat messages, workspace file contents, provider responses, and external tool
  output are user data and are never translated automatically.

## Existing state and evidence

ISyCode currently embeds display text across `src/isycode/`, with the TUI as
the largest concentration and a separate Textual command browser. There is no
complete runtime locale catalog. The repository is mid-migration to `src/` and
`tests/`; implementation must preserve that in-progress working tree and touch
only scoped localization files.

IntentLang already contains a UI-message pipeline under
`src/intentlang/translation_engine/`: inventory extraction, UI Message IR,
context resolution, materialization, and round-trip verification. A local probe
against real ISyCode-style messages demonstrated these limitations:

1. `Delete this workspace?` translated to `Keep this workspace.` was reported
   as 100% round-trip success (one checked, one passed, zero failed). The target
   message is not analyzed for semantic invariants, so this result is a false
   positive for meaning preservation.
2. `Turn on` materialized as `Turn activado` and `Filter this list…` as
   `filtrar this list…`.
3. Longer safety explanations remain unchanged and receive `[NEEDS_REVIEW]`.

IntentLang is therefore an offline proposal and evaluation tool in this work;
its output is never copied into the product without review. It does not enter
the ISyCode runtime, provider path, permission model, or security boundary.

## Localization architecture

Add a small ISyCode-owned localization layer backed by Python's standard
`gettext` support and contextual message catalogs. English source strings are
the stable message identifiers; Spanish translations live in a packaged
catalog. Context is included where identical English words have distinct UI
meanings. All displayed owned strings pass through the localization API.

The selected locale is a user-wide presentation preference, not workspace
configuration. Spanish is the default for new and existing users unless they
choose English. The preference is stored through the existing user-preference
owner and can be changed from Settings. It must not be loaded from `.isycode/`,
create workspace grants, or influence Authority, ISySentinel, or execution.

Formatting values remain separate from translated templates. Placeholder names
and multiplicity must match between locales; formatting uses named values where
possible. Pluralized messages use gettext plural forms. Rich markup, terminal
key names, paths, code spans, command examples, URLs, and machine-readable
strings are protected and reviewed as part of each catalog entry.

English remains the source/fallback locale. Missing Spanish entries must be
reported by locale validation and cannot silently be treated as a finished
translation. Release acceptance requires no untranslated owned UI messages in
Spanish mode, except explicitly approved product names and machine tokens.

## IntentLang repair and evaluation

Work in `/home/danny/Development/ISyCo Git/IntentLang` as a separate stage.
Preserve its current user worktree state; do not change unrelated language
packs or subsystems.

1. Repair the round-trip verifier so a target with absent or unresolvable
   semantic facts cannot count as a semantic pass. It must analyze target text
   using the target locale and compare available invariants, or return an
   explicit inconclusive/failure result. A destructive polarity reversal must
   be rejected by a regression case.
2. Repair the UI materializer's handling of short multiword phrases and longer
   messages. It must not emit a confidently wrong mixed-language or
   ungrammatical result as a completed translation. If the deterministic
   engine cannot resolve a phrase, preserve it as a visibly unverified draft
   for human review, with an accurate report status.
3. Evaluate a representative ISyCode corpus covering labels, actions,
   permissions, destructive confirmations, warnings, placeholders, shortcuts,
   technical terms, dynamic values, and long-form explanations. Record
   unchanged strings, review markers, placeholder parity, semantic reversals,
   and human-review decisions. Do not report one aggregate score as proof of
   translation quality.

The corpus must contain no credentials, user content, or workspace data. Any
IntentLang fixes remain useful to that project independently; ISyCode consumes
only reviewed catalog text.

## Translation scope in ISyCode

Translate all owned, user-visible CLI/TUI prose, including:

- command browser categories, descriptions, search states, and keyboard help;
- menus, status labels, input prompts, placeholders, buttons, and hints;
- setup flows, confirmations, warnings, error and success messages;
- local diagnostics/help output intended for users;
- explanatory strings produced by ISyCode adapters before display.

Do not translate external provider/model names, IDs, raw provider responses,
workspace text, command invocations, paths, security/action IDs, serialized
protocol values, source-code identifiers, or evidence records. Exact error
codes and status enums remain machine-stable; any human-facing explanation is
localized at the presentation boundary.

## Documentation scope

Make active official user and contributor documentation Spanish-first, with
an English secondary counterpart. The implementation stage must inventory
current documents before editing and identify the canonical Spanish path and
its English counterpart for each included document. Initial candidates are
the root README, CONTRIBUTING guide, user guide, installation/update
instructions, and active user-facing reference pages.

Keep research evidence, hashed reports, experiment artifacts, historical
plans, fixtures, generated output, and archived handoffs in their current
language to preserve provenance. Operational `AGENTS.md` files require a
separate explicit inventory: translate their explanatory prose and comments
only where doing so preserves commands, contracts, and exact machine tokens.
Do not change an evidence hash or rewrite historical claims as part of
localization.

Code examples retain executable commands and identifiers exactly. Their
surrounding explanations and expected human-facing prose are Spanish in the
primary version; English counterparts keep the same commands and semantics.

## Comments and source maintenance

Translate explanatory prose comments and docstrings in ISyCode Python source
to Spanish, including the modules touched by localization. Do not translate
third-party or vendored code, license text, generated code, strings that form
protocols, or comments whose contents are executable fixtures. Any comment
that describes security or authority must retain the current contract exactly;
translation must not alter implementation behavior.

## Security and compatibility constraints

- Localization changes presentation only. It grants no capability and changes
  no action request, parameter, scope, approval, or decision.
- Workspace Authority, ISySentinel, execution owners, receipts, and their
  deny-by-default behavior remain byte-for-byte equivalent in effect.
- Locale selection is user-wide and cannot be overridden by workspace files,
  prompt content, model output, or integrations.
- JSON/headless output, protocol payloads, persisted schemas, command names,
  flags, and existing machine consumers remain stable.
- If loading the Spanish catalog fails, show English source text and a clear
  diagnostic; never block startup or weaken authorization.

## Approaches considered

### Translate literals independently in each module

This would produce Spanish quickly but leaves English alternatives and
consistency checks scattered across dozens of files. It does not provide a
reliable language selector or enforce placeholder parity.

### Apply IntentLang output directly

The probe produced a destructive semantic reversal, malformed short phrases,
and untranslated long messages while its verifier reported a false pass. This
approach does not meet the product's accuracy requirements.

### Contextual catalog with reviewed IntentLang proposals — selected

Use gettext catalogs for runtime switching, retain stable English message IDs,
and curate Spanish entries with IntentLang as an offline aid. This centralizes
context, locale completeness, placeholder validation, and product terminology.

## Rollout stages

1. **IntentLang reliability:** repair demonstrated semantic-verification and
   materialization failures; evaluate a small representative corpus and record
   limitations honestly.
2. **ISyCode runtime localization:** inventory owned strings; add the locale
   owner/catalog and Settings selection; translate the CLI/TUI; update local
   comments/docstrings in scope; verify both locales and security invariants.
3. **Official documentation:** inventory active official docs, publish Spanish
   primary versions and English counterparts, and cross-link them from the
   README. Preserve evidence and historical records.

Each stage is reviewable independently. Do not begin the next stage if the
previous stage has unresolved semantic or compatibility failures.

## Acceptance criteria

1. Spanish is selected by default; the user can select English and the choice
   persists across launches without workspace configuration.
2. Every owned CLI/TUI string is localized or explicitly classified as a brand
   name, command, technical token, external/user data, or machine output.
3. Spanish and English catalogs have matching message IDs and placeholders;
   required locale validation fails on missing or malformed entries.
4. The branded names specified above remain unchanged; generic UI terms such as
   Settings and Context use the approved Spanish labels.
5. Commands, flags, provider/model IDs, paths, protocol payloads, and
   machine-readable output remain stable in both locales.
6. Security-critical confirmation and denial strings preserve actor, action,
   polarity, scope, consequences, and approval requirements; no permission
   behavior changes with locale.
7. IntentLang reports semantic uncertainty as inconclusive/review-required,
   and the destructive reversal reproduction no longer passes.
8. No completed Spanish UI entry contains `[NEEDS_REVIEW]`, mixed-language
   leftovers, or unresolved placeholders.
9. Active official documentation has a Spanish primary and English secondary
   counterpart; historical evidence, fixtures, and research records retain
   their original bytes and hashes.
10. Explanatory ISyCode source comments/docstrings are Spanish within scope;
    executable snippets, tokens, and commands remain exact.

## Out of scope

- Translating chat/provider responses, workspace files, code, or tool output.
- Adding translation to IntentLang's runtime or making it an ISyCode
  dependency.
- Changing security policy, execution, grants, approvals, protocols, or
  persisted data schemas.
- Translating research evidence, experiment reports, fixtures, archived plans,
  or third-party material.
- Broad cleanup or unrelated edits in either repository.
