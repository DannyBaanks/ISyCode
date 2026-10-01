# Workspace Folders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read/edit sibling folders in one chat with independent gates and explicit optional delegated file-edit approval.
**Architecture:** A private validated root registry addresses selected sibling directories by alias. Existing owners execute against the selected root; native user controls manage registration and approval preference.
**Tech Stack:** Python >=3.10, Textual1.0.0, existing standard-library/storage helpers.
**Spec:** docs/superpowers/specs/2026-10-01-workspace-folders.md

## Global Constraints
- Python >=3.10; Textual1.0.0; no new runtime dependencies.
- No shared parent boundary, grant inheritance, model-managed roots, commands/delete/move/commit auto-approval.
- Root-specific Authority, Sentinel, approvals, checkpoints and journals remain active.

## Review Focus
- Symlink or replaced root: reject registration/routing, never redirect a pending write.
- Malformed or unsafe private config: fail closed without resetting permissions.
- Unknown alias or unsupported tool: deny; never fall back to main.
- Revocation/removal during diff review: block apply and delegated approval.
- Read-only sibling with its own Classic preset: still reject writes through the attachment.

## Task 1: Registry and root capabilities
**Files:** isycode/workspace_folders.py; test_workspace_folders.py.
**Interfaces:** WorkspaceFolders(main).list()/add(alias,path,editable)/remove(alias)/resolve(alias,write=False)/auto_edit_allowed(alias)/set_auto_edit(alias,enabled).
- [ ] Add failing tests for persistence, exact-root grants, read-only caps, symlinks/non-siblings, removed/replaced roots, malformed config and root-scoped auto preferences.
- [ ] Run tests and inspect expected failures.
- [ ] Implement bounded private atomic config, stable directory identity, explicit exact-root read/write grants and user-only preference methods.
- [ ] Run tests; commit registry and evidence.

## Task 2: Native folder controls and tool routing
**Files:** isycode/tui.py; test_workspace_folders_tui.py; documentation and authority snapshot.
**Interfaces:** Consume Task1 registry; optional `folder` parameter only on read/write tool schemas. WriteApprovalScreen displays actual root; warning confirmation controls delegated approval.
- [ ] Add failing full-app tests for sibling read/edit+native approval, denied traversal/unsupported tools, warning cancellation/enabling/disabling, browser selection, removal during review and independent journals.
- [ ] Inspect failures; implement folder management UI, browser-root separation and selected-root owner routing.
- [ ] Add root-aware write capability checks and optional per-root auto-edit delegation; recheck registry before apply; preserve approval semantics for other effects.
- [ ] Verify focused tests, Python3.10 local suite, real sandbox workflow and fresh screenshots. Regenerate authority snapshot.
- [ ] Request independent whole-branch review, fix important findings with regression tests, commit and push the feature branch.
