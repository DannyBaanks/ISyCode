# IntentLang UI Translation Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make IntentLang's UI materializer and round-trip report refuse false confidence, then evaluate a small sanitized ISyCode-style catalog.

**Architecture:** Keep this work inside IntentLang's existing offline `translation_engine` pipeline. Reuse the semantic phrase extractor/verifier as bounded evidence; unknown target meaning remains review-required, and materialized text remains a draft unless a reviewed phrase/template supports it.

**Tech Stack:** Python 3.12+, pytest, existing IntentLang UI Message IR and semantic-phrase modules; no network or new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-10-01-isycode-spanish-localization-design.md` in the ISyCode repository.

## Global Constraints

- IntentLang is an offline proposal and evaluation tool; its output is never copied into ISyCode without review.
- The corpus must contain no credentials, user content, or workspace data.
- Unknown or unresolved semantic evidence is inconclusive/review-required, never a pass.
- Do not modify unrelated language packs or subsystems.
- Do not claim broad natural-language understanding or translation quality from a small corpus.

## Review Focus

- A destructive source/target polarity reversal must fail or be explicitly inconclusive; it must never count as a semantic pass.
- Unknown target-language words must not inherit source-language destructive/polarity facts as if they were verified.
- Short phrases with inflection or word order must not be emitted as fluent translations from isolated word substitution.
- Long messages and strings containing placeholders, accelerators, commands, brands, and technical tokens must remain structurally intact and visibly review-required when untranslated.
- A harness result must distinguish complete, draft, and failed work; an unchanged source string cannot be reported as a completed translation.

---

### Task 1: Make semantic round-trip verification fail closed

**Files:**
- Modify: `src/intentlang/translation_engine/roundtrip_verifier.py`
- Test: `tests/test_translation_engine.py`
- Reference: `src/intentlang/translation_engine/semantic_phrase/extractor.py`
- Reference: `src/intentlang/translation_engine/semantic_phrase/verifier.py`

**Interfaces:**
- Consumes: `extract_semantics(surface: str, locale: str)` and `verify_roundtrip(source, target, source_locale, target_locale)`.
- Produces: existing `RoundtripResult` and `Mismatch`; semantic unknowns are surfaced in `mismatches` and cannot increment `passed`.

- [ ] **Step 1: Add regressions for false-positive semantics**

Add tests named `test_destructive_polarity_reversal_does_not_pass_roundtrip` and `test_unresolved_target_semantics_are_not_counted_as_verified`. The first builds a one-key inventory containing `Delete this workspace?` and target locale `Keep this workspace.` and asserts the result is not 100% passing and identifies semantic/polarity review or failure. The second uses a target phrase with no supported Spanish parse and asserts it cannot pass as semantically verified.

- [ ] **Step 2: Run the regressions and verify failure**

Run: `pytest tests/test_translation_engine.py -q`
Expected: the reversal currently demonstrates the false green; the new assertions fail before implementation.

- [ ] **Step 3: Connect target-locale semantic analysis**

In `_build_ir_from_locale` / `verify_roundtrip`, analyze the source and target surfaces in their respective locales and compare only supported invariants. Record missing or unresolved target semantics as explicit mismatches/review-required evidence. Never assign source semantics to the target merely because it shares a key.

- [ ] **Step 4: Run the targeted verifier tests**

Run: `pytest tests/test_translation_engine.py tests/test_semantic_phrase/test_verifier.py -q`
Expected: reversal is rejected or inconclusive, unresolved target semantics do not increase `passed`, and existing supported equivalence cases remain green.

- [ ] **Step 5: Commit the verifier repair**

```bash
git add src/intentlang/translation_engine/roundtrip_verifier.py tests/test_translation_engine.py
git commit -m "fix(i18n): fail closed on unknown roundtrip semantics"
```

### Task 2: Prevent malformed materializer output from appearing complete

**Files:**
- Modify: `src/intentlang/translation_engine/materializer.py`
- Modify: `src/intentlang/translation_engine/harness.py`
- Test: `tests/test_translation_engine.py`

**Interfaces:**
- Consumes: `materialize_single`, `_materialize_text`, and current materialization statistics.
- Produces: explicit draft/review status in materialization and harness reports; preserve the existing public CLI and file format unless a backwards-compatible field is added.

- [ ] **Step 1: Add regressions for mixed-language phrases and review accounting**

Add tests named `test_short_phrase_does_not_mix_languages`, `test_long_untranslated_copy_is_reported_for_review`, and `test_placeholder_and_technical_tokens_survive_review_draft`. Assert that `Turn on` is not emitted as `Turn activado`, `Filter this list…` is not labeled complete as `filtrar this list…`, long prose has a visible review status, and placeholders/commands remain byte-identical.

- [ ] **Step 2: Run the regressions and verify failure**

Run: `pytest tests/test_translation_engine.py -q`
Expected: malformed short phrases or falsely complete status violate at least the new assertions.

- [ ] **Step 3: Materialize only supported reviewed phrases as complete**

Update `_materialize_text` and materialization statistics so dictionary word substitution is not treated as grammatical phrase translation. Keep unsupported text as an unchanged, visibly unverified draft; preserve protected placeholders, accelerators, brands, and technical tokens. The caller/report must distinguish completed translations from review drafts.

- [ ] **Step 4: Propagate draft status through the harness**

Update M3/M5 status aggregation so review-required drafts cannot produce overall `PASS`. Keep deterministic verification separate from translation completeness and include counts/keys in the machine-readable report.

- [ ] **Step 5: Run targeted tests**

Run: `pytest tests/test_translation_engine.py -q`
Expected: all materializer regressions pass; the harness reports review work without marking it complete.

- [ ] **Step 6: Commit the materializer repair**

```bash
git add src/intentlang/translation_engine/materializer.py src/intentlang/translation_engine/harness.py tests/test_translation_engine.py
git commit -m "fix(i18n): label unsupported UI translations as drafts"
```

### Task 3: Evaluate a sanitized ISyCode-style UI corpus

**Files:**
- Create: `tests/fixtures/ui_translation/isycode_sample_en.json`
- Create: `tests/fixtures/ui_translation/README.md`
- Create: `docs/translation/intentlang-isycode-evaluation.md`
- Test: `tests/test_translation_engine.py`

**Interfaces:**
- Consumes: fixed UI inventory schema and the repaired harness/materializer.
- Produces: reproducible evaluation report with per-class results, review decisions, and limitations; no dependency from ISyCode to IntentLang.

- [ ] **Step 1: Define a sanitized representative fixture**

Include only synthetic labels, actions, permission explanations, destructive confirmations, warnings, placeholders, keyboard shortcuts, technical terms, and long help text. Add assertions that fixture values contain no tokens, credentials, user messages, or workspace paths.

- [ ] **Step 2: Run the evaluation and preserve exact evidence**

Run: `pytest tests/test_translation_engine.py -q` and the documented harness command against the fixture into a fresh output directory.
Expected: report identifies translated vs unchanged/review-required entries and placeholder/technical-token parity; no one aggregate score is presented as translation quality.

- [ ] **Step 3: Record findings and limitations**

Write `docs/translation/intentlang-isycode-evaluation.md` with exact command, environment, report/artifact hashes, class-level counts, human review outcomes, known failure classes, and `NOT_DEMONSTRATED` claims. Do not overwrite prior evaluation output.

- [ ] **Step 4: Commit the fixture and report**

```bash
git add tests/fixtures/ui_translation/isycode_sample_en.json tests/fixtures/ui_translation/README.md tests/test_translation_engine.py docs/translation/intentlang-isycode-evaluation.md
git commit -m "docs(i18n): record sanitized UI translation evaluation"
```
