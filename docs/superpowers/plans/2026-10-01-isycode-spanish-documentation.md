# ISyCode Spanish-First Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish active official ISyCode user/contributor documentation primarily in Spanish with an English secondary counterpart while preserving historical evidence unchanged.

**Architecture:** Inventory current active docs before edits, define canonical Spanish and English paths, then translate only maintained user/contributor material. Cross-link language counterparts from the root landing page and verify command/code parity; preserve research, evidence, historical and generated documents byte-for-byte.

**Tech Stack:** Markdown, Python standard-library path/hash checks, existing repository documentation and CI conventions.

**Spec:** `docs/superpowers/specs/2026-10-01-isycode-spanish-localization-design.md`.

## Global Constraints

- Spanish is the primary language of active official documentation; English is a secondary counterpart.
- Preserve product and brand names including ISyCo, ISyCode, ISySentinel, Workspace Authority, Bridge, Gateway, IsyMotron, and branded `Authority & Security`.
- Executable commands, flags, identifiers, paths, protocol examples, and their semantics stay exact in both language versions.
- Keep research evidence, hashed reports, experiment artifacts, historical plans, fixtures, generated output, and archived handoffs in their current language and preserve hashes.
- Inventory operational `AGENTS.md` files separately; translate explanatory prose only when exact contracts, commands, and machine tokens remain intact.
- Preserve existing local edits and untracked files; translate in place or add counterparts without replacing unrelated content.

## Review Focus

- A command copied from either language version must remain runnable and semantically identical.
- Active user guidance must not be mistaken for a historical plan, security evidence, generated file, or archived handoff.
- Spanish and English counterparts must link to one another and describe the same supported behavior.
- Security/authority documentation must preserve deny-by-default rules, owners, scopes, confirmation requirements, and exceptions.
- No evidence report, fixture, or hashed artifact may be rewritten merely to achieve language consistency.

---

### Task 1: Inventory and classify active documentation

**Files:**
- Create: `docs/superpowers/plans/2026-10-01-isycode-docs-localization-inventory.md`
- Inspect: `README.md`, `CONTRIBUTING.md`, `docs/GUIA.md`, `docs/ROADMAP.md`, install/update references, and active user-facing docs
- Inspect separately: root and nested `AGENTS.md`

**Interfaces:**
- Produces: table of each candidate's status (active user/contributor, historical, evidence, fixture, generated, archived), current language, Spanish canonical path, English counterpart path, and explicit include/exclude decision.
- Consumes: approved documentation boundary in the localization spec.

- [ ] **Step 1: Write the inventory format and classification rules**

Create the inventory with columns `path`, `audience/status`, `current language`, `Spanish primary`, `English secondary`, and `decision/reason`. Explicitly list the known active candidates and all excluded evidence/historical categories.

- [ ] **Step 2: Fill the inventory from current files**

Run: `rg --files -g '*.md' -g 'AGENTS.md' -g '!**/.git/**'`
Expected: each maintained user/contributor guide is classified; evidence, fixtures, plans, handoffs, and generated reports are recorded as excluded or retained in original language.

- [ ] **Step 3: Review paths and preserve exact provenance**

Record hashes for representative excluded evidence/docs before implementation; verify hashes after translations. Do not edit excluded documents.

- [ ] **Step 4: Commit the inventory only**

```bash
git add docs/superpowers/plans/2026-10-01-isycode-docs-localization-inventory.md
git commit -m "docs(i18n): inventory active documentation"
```

### Task 2: Establish Spanish-primary and English-secondary guide pairs

**Files:**
- Modify or create paths according to Task 1 inventory, initially including: `README.md`, `README.en.md`, `CONTRIBUTING.md`, `CONTRIBUTING.en.md`, `docs/GUIA.md`, and `docs/GUIA.en.md`
- Modify: `docs/ROADMAP.md` only if inventory classifies it as an active public guide; otherwise preserve it as current planning material

**Interfaces:**
- Consumes: reviewed Task 1 path inventory.
- Produces: official Spanish page plus linked English counterpart for every included active user/contributor guide; examples and executable commands match.

- [ ] **Step 1: Add counterpart and command-parity checks**

Add a small documentation validation test/script that checks every included Spanish page links to its English counterpart, every English page links back, and fenced command blocks match after excluding localized prose-only examples.

- [ ] **Step 2: Run the checks against the current docs**

Run the new documentation check.
Expected: it identifies missing counterparts or mismatched command blocks before the guides are translated.

- [ ] **Step 3: Translate the Spanish-primary active guides**

Translate only content classified active in Task 1. Keep commands, flags, paths, identifiers, branded terms, and supported-behavior claims exact; do not invent features. Add clear links to the English counterpart near each title.

- [ ] **Step 4: Create or update English secondary counterparts**

Keep the same structure, command blocks, security meaning, and product claims as Spanish; add reciprocal language links. Existing English docs can serve as source where current and accurate.

- [ ] **Step 5: Run documentation parity and link checks**

Run the new check plus link/path validation.
Expected: all included guide pairs are reciprocal and command blocks match; excluded evidence hashes remain unchanged.

- [ ] **Step 6: Commit guide pairs in bounded groups**

```bash
git add README.md README.en.md CONTRIBUTING.md CONTRIBUTING.en.md docs/GUIA.md docs/GUIA.en.md
git commit -m "docs(i18n): publish Spanish-first user guides"
```

### Task 3: Translate approved active reference pages and source comments

**Files:**
- Modify: only additional paths marked included in `docs/superpowers/plans/2026-10-01-isycode-docs-localization-inventory.md`
- Modify: explanatory comments/docstrings under `src/isycode/` in modules touched by localization, followed by remaining ISyCode source modules in the approved scope
- Test: documentation parity validator and existing tests for touched source modules

**Interfaces:**
- Consumes: Task 1 inventory and accepted Spanish terminology list.
- Produces: Spanish-first maintained references and Spanish explanatory source comments/docstrings; English docs remain secondary and code behavior is unchanged.

- [ ] **Step 1: Add a terminology and protected-token review checklist**

Record generic UI terms (`Settings` → `Configuración`, `Context` → `Contexto`) separately from protected ISyCo brand terms. List syntax that must remain exact: commands, flags, IDs, paths, environment variables, protocol values, and code examples.

- [ ] **Step 2: Translate only approved active references and source prose**

Translate descriptions, comments, and docstrings without changing executable statements or security assertions. Leave third-party/vendor/license text, fixtures, evidence, protocol strings, and historical/archived material untouched.

- [ ] **Step 3: Verify documentation commands and source behavior**

Run: documentation parity/link validation and targeted tests for changed source modules.
Expected: docs remain reciprocal; command examples match; tests confirm localization-only comment/docstring edits do not alter behavior.

- [ ] **Step 4: Recheck excluded evidence hashes and inspect diff scope**

Run: `git diff --name-status` and recompute the Task 1 excluded-file hashes.
Expected: no excluded evidence/history/fixture file changed and no unexpected paths appear.

- [ ] **Step 5: Commit the bounded reference/comment translation**

```bash
git add <only inventoried active documentation and scoped src/isycode files>
git commit -m "docs(i18n): translate active references and source prose"
```

### Task 4: Set Spanish-first documentation entry points

**Files:**
- Modify: `README.md`
- Modify: `CONTRIBUTING.md`
- Modify: inventory-listed docs index/navigation page, if one exists
- Test: documentation parity/link validator

**Interfaces:**
- Consumes: completed guide pairs and inventory.
- Produces: obvious Spanish-first landing links and discoverable English alternatives.

- [ ] **Step 1: Add landing-link assertions**

Extend the documentation validator to assert the root landing page links to the Spanish user guide, contributor guide, and corresponding English alternatives.

- [ ] **Step 2: Update landing-page navigation**

Keep the home-page structure focused on source tree, contribution entry points, setup/use docs, and language choices; do not move/delete project files as part of this task.

- [ ] **Step 3: Run final docs checks**

Run the documentation parity/link validator.
Expected: all required language links resolve, counterpart links are reciprocal, and command blocks match.

- [ ] **Step 4: Commit navigation updates**

```bash
git add README.md CONTRIBUTING.md <inventory-listed docs index>
git commit -m "docs(i18n): link Spanish and English documentation"
```
