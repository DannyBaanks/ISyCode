# ISyCode CLI/TUI Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Spanish the default ISyCode CLI/TUI language, offer persistent English selection, and localize owned interface copy without changing commands or security behavior.

**Architecture:** Add an ISyCode-owned gettext localization layer with contextual message IDs and packaged English/Spanish catalogs. Store locale in the existing user-wide preferences owner, then route owned display strings through the localization API; IntentLang supplies reviewed proposals only and is not a runtime dependency.

**Tech Stack:** Python 3.12+, standard-library `gettext`, existing Textual CLI/TUI, `UserDefaultsStore`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-01-isycode-spanish-localization-design.md`.

## Global Constraints

- Spanish is the default interface and the primary language of official active documentation.
- English is selectable in the interface and remains available as a secondary copy of official user documentation.
- Product and brand names remain unchanged, including ISyCo, ISyCode, ISySentinel, Workspace Authority, Bridge, Gateway, and IsyMotron; branded feature names such as `Authority & Security` remain intact.
- Slash commands, shell commands, option flags, provider/model identifiers, protocol names, paths, environment variables, code, and machine-readable output retain their exact syntax.
- Chat messages, workspace file contents, provider responses, and external tool output are never translated automatically.
- Localization changes presentation only; Authority, ISySentinel, execution owners, receipts, and deny-by-default behavior remain equivalent in effect.
- Locale is user-wide and cannot be overridden by workspace files, prompt content, model output, or integrations.
- If the Spanish catalog fails to load, show English source text and a clear diagnostic; never block startup or weaken authorization.
- Preserve the in-progress `src/`/`tests/` migration and unrelated working-tree changes; make path-scoped edits only.

## Review Focus

- Corrupt, missing, or unsupported locale preference must safely resolve to Spanish/default behavior without blocking startup.
- A missing contextual catalog entry must be found by validation rather than silently shipped as completed Spanish.
- Strings with named placeholders, plural counts, rich markup, paths, slash commands, and keyboard shortcuts must preserve their structure.
- Headless JSON, protocol payloads, enum values, and CLI command parsing must be byte-compatible across locales.
- Security-critical allow/deny/confirmation text must preserve actor, action, polarity, scope, consequences, and approval requirement in both languages.

---

### Task 1: Add locale preference to user-wide defaults

**Files:**
- Modify: `src/isycode/user_defaults.py`
- Test: `tests/test_user_defaults_mode.py`

**Interfaces:**
- Consumes: existing `UserDefaultsStore.load()` and `update()` schema.
- Produces: `locale: str` (`"es"` or `"en"`) defaulting to `"es"`, persisted in the same private user-wide file; no workspace path or grant is added.

- [ ] **Step 1: Add locale persistence regressions**

Add `test_locale_defaults_to_spanish`, `test_locale_preference_persists_english`, and `test_invalid_locale_is_rejected`. Assert the key is present on first load, survives reload, and accepts only `es`/`en`.

- [ ] **Step 2: Run the new tests and verify failure**

Run: `pytest tests/test_user_defaults_mode.py -q`
Expected: locale persistence assertions fail before the schema adds the field.

- [ ] **Step 3: Add validated user-wide locale storage**

Extend `UserDefaultsStore` defaults, validation, returned data, and `update(locale=...)`; preserve existing file safety checks and backward-compatible version-1 files without the new key.

- [ ] **Step 4: Run user-default tests**

Run: `pytest tests/test_user_defaults_mode.py -q`
Expected: Spanish default, English persistence, and invalid-value rejection pass; existing fields remain unchanged.

- [ ] **Step 5: Commit the preference change**

```bash
git add src/isycode/user_defaults.py tests/test_user_defaults_mode.py
git commit -m "feat(i18n): persist user interface language"
```

### Task 2: Build localization API and contextual catalogs

**Files:**
- Create: `src/isycode/localization.py`
- Create: `src/isycode/locales/en/LC_MESSAGES/isycode.po`
- Create: `src/isycode/locales/es/LC_MESSAGES/isycode.po`
- Modify: `pyproject.toml`
- Test: `tests/test_localization.py`

**Interfaces:**
- Produces: `configure_locale(locale: str) -> None`, `tr(message: str, *, context: str | None = None, **values: object) -> str`, and `validate_catalogs() -> list[str]` (empty list means IDs/placeholders are aligned).
- Catalog context distinguishes homographs; named formatting values remain separate from localized templates; package resources load without repository-relative cwd assumptions.

- [ ] **Step 1: Add tests for fallback, context, placeholders, and catalog parity**

Create tests named `test_spanish_contextual_message`, `test_english_catalog_selection`, `test_missing_catalog_entry_uses_english_and_reports_diagnostic`, `test_named_placeholders_are_preserved`, and `test_catalog_validator_rejects_missing_id_or_placeholder_mismatch`.

- [ ] **Step 2: Run localization tests and verify failure**

Run: `pytest tests/test_localization.py -q`
Expected: tests fail because the localization module/catalogs do not exist.

- [ ] **Step 3: Implement the localization API and catalogs**

Implement the declared interfaces using `gettext`/`pgettext` and packaged catalog resources. For Spanish fallback failures return stable English msgids and expose a non-sensitive diagnostic. Include starter entries for `Settings` -> `Configuración`, `Context` -> `Contexto`, while preserving the branded `Authority & Security` label.

- [ ] **Step 4: Package catalogs and validate completeness**

Configure build inclusion and add a deterministic validator for matching message IDs and named placeholder multiplicity. Do not load translations for protocol/headless serialization paths.

- [ ] **Step 5: Run localization tests**

Run: `pytest tests/test_localization.py -q`
Expected: all locale selection, fallback, context and placeholder tests pass; validator rejects a deliberately malformed temporary catalog.

- [ ] **Step 6: Commit the localization foundation**

```bash
git add src/isycode/localization.py src/isycode/locales pyproject.toml tests/test_localization.py
git commit -m "feat(i18n): add contextual gettext catalogs"
```

### Task 3: Integrate language selection and localize owned CLI/TUI surfaces

**Files:**
- Modify: `src/isycode/tui.py`
- Modify: `src/isycode/cli.py`
- Modify: `src/isycode/launcher.py`
- Modify: `src/isycode/diagnostics.py`
- Modify: other `src/isycode/*.py` modules only where the string is ISyCode-owned display copy
- Test: `tests/test_localization.py`
- Test: focused tests in `tests/test_tui_startup.py`, `tests/test_authority_menu.py`, and `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `tr(...)`, `configure_locale(...)`, and `UserDefaultsStore` locale preference.
- Produces: startup-resolved Spanish/English display language and a `Configuración → Idioma` selector; commands, IDs, protocol output, raw user/provider text remain unchanged.

- [ ] **Step 1: Add startup/menu and security-copy locale regressions**

Add tests for Spanish default at initial TUI render, switching to English and preserving it after a new app instance, brand-name preservation, localized diagnostics, unchanged slash command registration, and identical authorization decision values for both locale settings.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/test_localization.py tests/test_tui_startup.py tests/test_authority_menu.py tests/test_diagnostics.py -q`
Expected: locale UI assertions fail before integration; all existing security assertions continue to pass.

- [ ] **Step 3: Resolve locale before rendering and expose the selector**

Load the validated user-wide locale during app startup; add an explicit language choice in Settings and persist through `UserDefaultsStore.update(locale=...)`. Do not consult `.isycode/` or change workspace authority.

- [ ] **Step 4: Route owned user-visible strings through the catalog**

Localize command browser copy, menus, input hints, status, setup, warnings/errors, diagnostics, and adapter explanations. Preserve branded vocabulary and technical syntax from the Global Constraints. Leave provider replies, workspace contents, and machine-readable output untouched.

- [ ] **Step 5: Validate catalog coverage and run focused regressions**

Run: `pytest tests/test_localization.py tests/test_tui_startup.py tests/test_authority_menu.py tests/test_diagnostics.py -q`
Expected: both locales render, the validator reports no missing owned UI keys, preference persists, and authorization/protocol assertions are unchanged.

- [ ] **Step 6: Commit the UI integration**

```bash
git add src/isycode tests/test_localization.py tests/test_tui_startup.py tests/test_authority_menu.py tests/test_diagnostics.py
git commit -m "feat(i18n): localize CLI and TUI in Spanish and English"
```

### Task 4: Complete localization compatibility checks

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_localization.py`
- Test: `tests/test_security_contract.py`
- Test: `tests/test_tool_protocol.py`

**Interfaces:**
- Consumes: catalogs, validator, and dual-locale integration.
- Produces: CI gate for catalog ID/placeholder parity and regression checks for unchanged machine/security surfaces.

- [ ] **Step 1: Add CI-level catalog and output parity assertions**

Add tests that run owned-string coverage validation and compare representative headless/protocol/security outputs under `es` and `en`.

- [ ] **Step 2: Verify tests catch an omitted or malformed entry**

Run the catalog validator test against a temporary incomplete catalog.
Expected: validation fails with the exact missing key or placeholder mismatch.

- [ ] **Step 3: Add the validator to CI**

Wire the existing project test command to execute locale validation; keep the workflow's Python/runtime setup unchanged.

- [ ] **Step 4: Run focused compatibility tests**

Run: `pytest tests/test_localization.py tests/test_security_contract.py tests/test_tool_protocol.py -q`
Expected: all tests pass; machine output and authorization decisions are locale-invariant.

- [ ] **Step 5: Commit the validation gate**

```bash
git add .github/workflows/ci.yml tests/test_localization.py tests/test_security_contract.py tests/test_tool_protocol.py
git commit -m "test(i18n): gate catalog and security parity"
```
