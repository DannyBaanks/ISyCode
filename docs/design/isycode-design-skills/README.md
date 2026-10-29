# ISyCode Design Skills v1

A versioned, searchable authoring catalog for the Python/Textual ISyCode repository. It captures Danny's selected **Contraste esencial** direction and comparator profile, so future menus and content boxes share the same palette, patterns and interaction targets.

Start with the [Spanish operator guide](GUIA.md). The repository's [AGENTS.md](../../../AGENTS.md) routes TUI changes to the [core skill](../../../.agents/skills/isycode-design/SKILL.md) and the relevant component skill.

## Canonical resources

- [Catalog](../../../.agents/skills/isycode-design/references/catalog.json): names, summaries, tags, paths and SKILL.md SHA-256 fingerprints.
- [Visual standard](../../../.agents/skills/isycode-design/references/visual-standard.md): accepted choices, provenance and dated implementation limits.
- [Shared tokens](../../../.agents/skills/isycode-design/assets/tokens.json) and [scoped TCSS](../../../.agents/skills/isycode-design/assets/tokens.tcss): reusable authoring assets.
- Component skills: [option boxes](../../../.agents/skills/isycode-option-boxes/SKILL.md), [Settings/sidebar](../../../.agents/skills/isycode-settings-sidebar/SKILL.md), [text/copy](../../../.agents/skills/isycode-text-copy/SKILL.md), [icons/motion](../../../.agents/skills/isycode-icons-motion/SKILL.md).

The JSON registry is the database for this first version: inspectable, searchable, committed alongside the instructions, and usable without a server or extra package. Read-only lookup lives in the core skill's `scripts/catalog.py`. Changes are reviewed and committed as ordinary source; update the entry's SHA-256 when its SKILL.md changes. The integrity checker reports stale fingerprints rather than rewriting them silently.

Local installation uses symlinks to these canonical folders under the Codex skills directory supplied by this environment's skill-creator convention (`~/.codex/skills` unless CODEX_HOME is set). All five links were inspected. The repository itself uses the documented `.agents/skills` location. [Official skill documentation](https://learn.chatgpt.com/docs/build-skills) describes repo discovery, symlink support and explicit invocation. Refresh of a new session's picker is not demonstrated by a filesystem check.

## Verification and limits

[Raw commands/output](validation.log) and [structured results](validation.json) record format validation for each skill, catalog search/check/show, an unknown-name negative control, idempotent local installation and whitespace checks. Textual parsed the TCSS template; YAML metadata and canonical link targets were also checked. [SHA256SUMS.txt](SHA256SUMS.txt) preserves hashes for the delivered library and evidence.

This deliverable adds development guidance, not production TUI styling. It does not alter terminal fonts, permission grants, the pinned application skill bundle, or the separate Qt ISyCode-IDE product. Space-only expansion, exact mouse-range clipboard behavior and native terminal animation must be implemented and verified in the relevant runtime task. Future-agent skill selection and production TUI behavior remain NOT_DEMONSTRATED in this validation.
