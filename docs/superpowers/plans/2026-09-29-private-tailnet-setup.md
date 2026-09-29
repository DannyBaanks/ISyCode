# Private Tailnet Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional Settings wizard that lets a user inspect, install, log in to Tailscale, and expose only the local ISyCo Gateway through private tailnet Serve, with each system mutation explicitly previewed and approved.

**Architecture:** Keep Tailscale as an optional local integration. A read adapter reports bounded structured state. Separate execution owners perform a fixed package install, login, and exact private Serve mapping operations. Every action is registered in `ACTION_CATALOG`, Workspace Authority, IsySentinel, owner coverage, and the durable receipt journal. The TUI sequences the owners and issues a one-use approval only after showing the exact operation. A private state record tracks only the mapping ISyCode created; live Tailscale state remains the source of truth.

**Tech Stack:** Python 3.10+, Textual, pytest, subprocess with fixed argument vectors, existing Workspace Authority / IsySentinel / ActionApprovalStore / ActionAuditJournal.

**Spec:** `docs/superpowers/specs/2026-09-29-private-tailnet-setup-design.md`

## Global Constraints

- Preserve all existing dirty/uncommitted work. Do not reset, stash, or reformat unrelated files.
- `.isyroot` remains an identity boundary, never a filesystem or network grant. Do not add Tailscale state, tokens, or receipts to the workspace or Bridge.
- The Gateway remains bound to `127.0.0.1`; only private Tailscale Serve may proxy to its existing loopback port. Funnel, public tunnels, public listeners, and automatic Mobile Host startup are out of scope.
- No `shell=True`, shell command strings, `curl | sh`, reusable auth keys, password prompts, OAuth-token persistence, or arbitrary package names. Only fixed, typed arguments reach subprocesses.
- A discovered executable or installed dependency is not permission. Every protected read or mutation must pass its exact registered owner, explicit workspace action grant, all applicable Systembilities, and a request-bound one-use approval for actions marked approval-required.
- Never overwrite or reset an existing Serve configuration. Enable/disable only an ISyCode-owned mapping whose identity can be proven; otherwise show a conflict and fail closed.
- Keep install/login/Serve status distinct from Gateway API-key scopes, provider credentials, workspace filesystem grants, MCP grants, and Mobile Host pairing.
- Keep each task small; add a focused failing test first, implement only enough to pass it, then run the named focused test and the existing action-frontier/TUI checks before moving on.
- Tailscale's CLI documents `serve reset` as clearing the entire Serve configuration. Never call it. Prefer `serve get-config --all` for inventory and only a documented per-service update/removal path; if a route cannot be changed independently, surface a conflict and stop. See [Tailscale Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve).

## Review Focus

1. **No mutation on startup, preflight, or cancel.** Covered by `test_inspect_runs_read_commands_only` in Task 1 and `test_tui_remote_access_does_not_execute_on_open_or_cancel` in Task 7.
2. **No arbitrary command or unverified package source.** Covered by `test_package_owner_accepts_only_official_ubuntu_debian_recipe` and `test_runner_never_uses_shell_or_dynamic_arguments` in Task 4.
3. **No implicit authority or stale approval.** Covered by `test_tailscale_actions_require_exact_grant_owner_and_fresh_approval` in Task 3 and `test_approval_is_bound_to_exact_serve_delta` in Task 6.
4. **Never expose Gateway publicly or disturb another Serve service.** Covered by `test_serve_preview_is_private_loopback_only` and `test_enable_disable_preserve_unowned_routes` in Task 6.
5. **Persist no login secrets and redact process output.** Covered by `test_login_url_and_cli_output_are_redacted_from_state_and_receipts` in Task 5 and `test_tailscale_state_is_private_and_contains_no_auth_material` in Task 2.

---

## Task 1: Add a bounded, read-only Tailscale inventory adapter

**Files:**
- Create `isycode/tailscale.py`
- Create `test_tailscale.py`

- [ ] Add failing tests for structured states: missing CLI, unsupported OS, daemon unavailable, signed out, signed in, malformed status JSON, timeout, oversized output, and existing/conflicting Serve config. Name the read-only boundary test `test_inspect_runs_read_commands_only`; assert inspection never calls a mutating subcommand.
- [ ] Define immutable records `TailscaleSnapshot`, `ServeRoute`, and `TailscaleCommandResult`; define `TailscaleAdapter(runner=..., platform=..., gateway_probe=...)` with the read-only method `inspect() -> TailscaleSnapshot`. Keep preview generation in the Serve owner added in Task 6.
- [ ] Restrict discovery to fixed executable candidates resolved with `shutil.which`, then canonicalize and record the resolved executable identity. Invoke only fixed read commands (`tailscale status --json`, `tailscale serve get-config --all`, and `tailscale serve status --json` when supported) using argv arrays, a minimal environment, and bounded timeout/output. Reconcile both Serve views; do not infer route ownership from `serve status --json` alone because that output does not provide the complete configuration needed to preserve unrelated routes.
- [ ] Parse JSON defensively with size/type limits. Represent unsupported CLI versions and non-JSON output as explicit unavailable/conflict states; never guess that Serve is disabled when it cannot be inspected.
- [ ] Probe only the configured local Gateway health endpoint on loopback. Reject any non-loopback Gateway bind or any port other than the configured Gateway port.
- [ ] Run `pytest -q test_tailscale.py`; all cases pass without a real Tailscale daemon or network.

## Task 2: Add private, non-secret ownership state for the ISyCode Serve route

**Files:**
- Create `isycode/private_access.py`
- Create `test_private_access.py`

- [ ] Add failing tests for atomic creation, mode `0600` file / `0700` parent on POSIX, symlink rejection, malformed/oversized JSON, wrong owner/version, and recovery when the file is absent.
- [ ] Define `PrivateAccessStateStore(state_directory=None)` in the existing XDG state root with `load() -> PrivateAccessState` and `record_owned_route(route: OwnedServeRoute) -> None` / `clear_owned_route(route_id: str) -> None`.
- [ ] Persist only adapter version, route ID and exact route identity (loopback target, tailnet path, creation time, last verified status). Reject fields that could contain auth URLs, auth keys, credentials, command output, or tokens. State is an ownership hint only; live `tailscale serve get-config --all` must independently match before removal.
- [ ] Make writes atomic with restrictive permissions and no-follow regular-file checks, following the established state-file patterns in `isycode/workspace_setup.py` and `isycode/workspace_authority.py`.
- [ ] Run `pytest -q test_private_access.py`.

## Task 3: Register Tailscale actions and fail-closed security contracts

**Files:**
- Modify `isycode/actions.py`
- Modify `isycode/action_runtime.py`
- Modify `isycode/action_coverage.py`
- Modify `docs/security/m15-authority-coverage.json`
- Modify `test_action_coverage.py`
- Create `test_tailscale_authority.py`

- [ ] Add failing contract tests for these action IDs and effects: `tailscale.inspect` (read), `tailscale.install` (process, approval required), `tailscale.login` (process, approval required), `tailscale.serve.enable` (process, approval required), and `tailscale.serve.disable` (process, approval required). All effects must have exactly one registered owner and a named effect callsite. Bind the Gateway endpoint and private route identity in the immutable request parameters and the applicable Systembilities; do not invent a compound effect string that Workspace Authority does not understand.
- [ ] Add closed owner entries `tailscale_read`, `tailscale_package_install`, `tailscale_login`, and `tailscale_serve`; register their exact actions and required Systembilities. Do not reuse `provider_network`, `broker_management`, or Mobile Host owners.
- [ ] Add Systembilities that validate canonical executable identity, supported OS and official package recipe, Gateway loopback target and port, private-only Serve mode, and exact owned-route identity. Keep checks pure; they inspect requests and supplied immutable adapter facts without performing effects.
- [ ] Add each owner/action/callsite to `KNOWN_EFFECT_CALLSITES`; update action-frontier expectations so no new action is silently unclassified and no formerly explicit-denied action changes classification accidentally.
- [ ] Regenerate `docs/security/m15-authority-coverage.json` from `authority_coverage_snapshot()` and keep `test_checked_in_snapshot_matches_live_catalog_and_owners` passing; this also repairs the pre-existing baseline drift found before implementation.
- [ ] Verify cross-owner requests, missing grants, wrong executable, public/Funnel parameters, altered port, forged route ownership, expired/replayed approval, and approval for a different request all deny in `test_tailscale_actions_require_exact_grant_owner_and_fresh_approval`.
- [ ] Run `pytest -q test_tailscale_authority.py test_action_coverage.py test_security_contract.py`.

## Task 4: Implement the narrowly scoped Ubuntu/Debian installer owner

**Files:**
- Create `isycode/tailscale_install.py`
- Create `test_tailscale_install.py`
- Modify `isycode/action_coverage.py` only for concrete owner callsites discovered during implementation

- [ ] Add failing tests for supported Ubuntu/Debian release detection, unsupported distributions, official repository/keyring verification, exact package name, apt lock/failure, privilege cancellation, timeout, command output redaction, and request-bound disclosure of package-maintainer service effects.
- [ ] Define `TailscalePackageInstallOwner.install(request: ActionRequest, approval: ActionApproval) -> ActionOutcome` and a typed `UbuntuDebianInstallPlan` containing the exact repository URI, signing-key identity, package `tailscale`, and fixed package-manager steps.
- [ ] Require the exact `tailscale.install` request to pass `WorkspaceAuthority`, `IsySentinel`, `ActionApprovalStore`, and the durable action journal before executing. Show repository source and exact package changes in the UI before issuing approval.
- [ ] Use a fixed, non-shell package owner. Validate the supported release, official HTTPS package source, pinned Tailscale signing-key identity, and repository/package signature before installation. Use the distribution-specific package setup documented by Tailscale rather than its convenience `curl | sh` script. Invoke only the exact configured package manager operation; privilege escalation must be an explicit OS authorization prompt. Never fall back to an installer script or a shell. Source: [Tailscale Linux installation](https://tailscale.com/docs/install/linux) and [Tailscale stable packages](https://pkgs.tailscale.com/stable/).
- [ ] Bound runtime/output, redact URLs and secrets from diagnostics, record success/failure receipt, and re-run read-only inventory afterward. The official package's maintainer script may start or restart `tailscaled`; show this effect in the exact install preview, bind it into the immutable request and Systembility, and require the user's fresh approval before installation. Do not issue an additional explicit service-manager start or log in as a side effect. The TUI must also offer official manual instructions with no local mutation. Do not offer automated "keep service stopped" until a separately reviewed and safely scoped service-suppression owner exists.
- [ ] Run `pytest -q test_tailscale_install.py test_tailscale_authority.py`.

**Reviewed staged contract (2026-09-29):** `tailscale.install.prepare` requires its own
approval and writes only isolated XDG private key, source, signed index, and
downloaded package files. It records a one-package simulation. A separate
`tailscale.install.stage` approval binds the exact file manifest and a unique
root-owned path under `/var/lib/isycode/tailscale`; fixed bounded copies are
checked with privileged ownership, mode, size, and SHA256 observations.
The stage request and preview bind every permitted fixed privilege argv,
artifact source and destination, byte cap, final mode, verification operation,
and conditional directory creation. Stage and final install each have one
monotonic wall-clock deadline spanning every privilege prompt and subprocess;
each call receives only its remaining budget.
`tailscale.install` needs a third fresh approval bound to that verified stage,
rechecks the stage and transaction, and sets `DEBIAN_FRONTEND=noninteractive`.
The final apt process reads only the root-owned stage. Unsupported transactions
go to the later TUI manual-instructions path. Apt simulation does not enumerate
all host dpkg triggers or package maintainer-script behavior; the approval
discloses that official package scripts and triggers run as root and may start
or restart `tailscaled`.

## Task 5: Implement explicit interactive login without collecting credentials

**Files:**
- Create `isycode/tailscale_login.py`
- Create `test_tailscale_login.py`
- Modify `isycode/action_runtime.py` / `isycode/action_coverage.py` only for login Systembility and audited owner callsites

- [x] Add failing tests for approval-before-launch, fixed executable/argv, pending login, completed login, user cancellation, timeout, malformed login output, credential-like output redaction, and restart without saved auth material.
- [x] Define `TailscaleLoginOwner.begin_login(request, approval) -> ActionOutcome` and `poll(attempt_id) -> LoginStatus`; retain only an in-memory attempt ID and sanitized login URL while active.
- [x] Provide a fixed-operation preview naming the official authorization destination; the user completes sign-in in their browser. Do not ask for or persist account passwords, reusable auth keys, OAuth tokens, raw Tailscale status JSON, or the full raw login output.
- [x] Require a fresh one-use `tailscale.login` approval for launch. Poll through bounded read-only inventory and expose only final non-secret identity status. On cancel or restart, discard the in-memory attempt and never try to roll back the user's tailnet enrollment.
- [x] Run `pytest -q test_tailscale_login.py test_tailscale_authority.py`.

## Task 6: Implement private Serve preview, enable, verify, and disable

**Files:**
- Modify `isycode/tailscale.py`
- Create `isycode/tailscale_serve.py`
- Create `test_tailscale_serve.py`
- Modify `test_private_access.py` if state needs a typed route identity field

- [x] Add failing tests for an empty Serve config, compatible existing routes, a conflicting route, unknown CLI schema, wrong Gateway bind/port, public Funnel mode, route drift after preview, repeated enable/disable, and preservation of unrelated routes. Include exact delta-binding and unowned-route preservation cases.
- [x] Define `ServePreview` and `TailscaleServeOwner` with the exact source loopback endpoint, private tailnet destination, route ID, and serialized configuration delta. Only allow the approved local Gateway address and configured port. Reject public/Funnel flags and any bind address except loopback.
- [x] Require the same immutable preview/request and fresh approval. Re-fetch live Serve state after approval and compare the exact digest before any write.
- [x] Use only fixed typed Tailscale Serve operations supported by the detected CLI version. Never use a reset/clear-all command. Refuse unknown or incomplete configuration.
- [x] Verify the exact private mapping, Gateway health, and preservation of every other node/service config. The adapter retains canonical raw node and Services configuration; owner compares it after projecting out only `/isycode`. Persist an ownership hint only after seeing the mapping live; disable requires that hint and exact live route.
- [x] Run focused route, authority, adapter, state, journal, and coverage suites; `124 passed`. `git diff --check` passed.

**Task 6 evidence (2026-09-29):** Offline fake-runner witnesses demonstrate exact `/isycode` enable/disable, one-use approval, route ownership, preservation of unrelated Web routes, TCP listeners and Services, fail-closed drift, redacted receipts, and no reset/Funnel. The full suite reached 307 passed before the final coverage snapshot refresh; focused suite after refresh passed 124. Tailscale daemon/device behavior and real tailnet reachability remain **NOT_DEMONSTRATED**. `pyright isycode/tailscale_serve.py` is clean; `action_runtime.py` still reports 11 existing optional-fact type errors in package-install/Gateway contracts (none in the new private-Serve boundary).

## Task 7: Add the Settings wizard and explicit approval screens

**Files:**
- Modify `isycode/tui.py`
- Create `test_tailscale_tui.py`
- Modify `test_secure_tui_surfaces.py`

- [ ] Add failing Textual tests for Settings entry, preflight-only open, missing/unsupported Tailscale, signed-out login, install-choice menu (official automated install with disclosed service effect, or manual instructions), Serve preview, conflict display, online status, disable preview, and cancel. Show automated "keep service stopped" as unavailable with a reason until it has a safely scoped owner. Opening the wizard and cancelling each modal must run no mutating owner.
- [ ] Add **Settings → Remote access → Private access (Tailscale)** with explicit wizard states. Display installation/login/Gateway/Serve facts separately and distinguish `not configured`, `conflict`, `private online`, and `verification unavailable`.
- [ ] Add focused confirmation screens showing the exact package source/action, login launch, Serve mapping, or mapping removal. Issue `ActionApprovalStore.issue()` only after confirmation; pass that same immutable request and approval to the matching owner. Ensure target/parameters in the request are exactly those rendered to the user.
- [ ] Add an Authority section showing per-action grants for the four owner families. An Authority grant does not enable a route by itself; every state change still needs an owner, Sentinel allow, a fresh one-use approval, and receipt. The wizard may guide the user to create a narrowly scoped grant, but must not create one silently.
- [ ] Keep Tailscale state refresh read-only and bounded. Do not start Mobile Host, alter MCP settings, or add a public tunnel from this screen.
- [ ] Extend the static direct-API audit to forbid TUI direct calls to package manager or Tailscale mutation methods; only the four registered owners may call them.
- [ ] Run `pytest -q test_tailscale_tui.py test_secure_tui_surfaces.py test_action_coverage.py`.

## Task 8: Add end-to-end security witnesses and user-facing documentation

**Files:**
- Create `test_private_tailnet_witness.py`
- Modify `README.md`
- Modify `ROADMAP.md`
- Modify `docs/superpowers/specs/2026-09-29-private-tailnet-setup-design.md`

- [ ] Add offline end-to-end witnesses using fake Tailscale/Gateway runners: preflight → explicit grant → preview → approval → Serve enable → verified status → disable. Assert each transition has a distinct receipt and cancellation/failure leaves unrelated routes unchanged.
- [ ] Add a marked manual witness for a real, already-owned tailnet: verify another logged-in tailnet device reaches the Gateway URL, verify Gateway API key/workspace scope remains enforced, and verify a non-tailnet device cannot reach it. Never print credentials in test output and never enable Funnel.
- [ ] Document minimum supported Linux distro, what each approval changes, what remains unavailable on other systems, how to revoke access, and that Tailscale reachability does not grant Gateway/filesystem/MCP authority.
- [ ] Update the design status to approved/implemented only for what evidence demonstrates; retain `NOT_DEMONSTRATED` for the real-device witness until manually completed. Do not claim a Tailscale integration is complete before the real witness passes.
- [ ] Run the focused suite plus `pytest -q test_action_coverage.py test_secure_tui_surfaces.py test_tailscale*.py test_private_access*.py`; record results and any `NOT_DEMONSTRATED` items in the docs.

## Final acceptance checklist

- [ ] Opening the TUI, Settings, or preflight changes no system, network, or workspace state.
- [ ] Ubuntu/Debian install, user login, Serve enable, and Serve disable each show the exact requested effect, pass Authority and IsySentinel, consume one fresh matching approval, and write a durable redacted receipt.
- [ ] Unsupported distributions, unavailable privilege, unknown CLI output, changed Serve state, missing Gateway, and route ownership uncertainty fail closed.
- [ ] Only an ISyCode-owned private route to the existing Gateway loopback listener can be added or removed; other routes remain byte-for-byte/config-equivalent.
- [ ] No credential is stored in `.isyroot`, workspace files, Bridge, logs, receipts, or persistent ISyCode state.
- [ ] `pytest -q test_action_coverage.py test_secure_tui_surfaces.py test_tailscale*.py test_private_access*.py` passes.
- [ ] TUI smoke witness launches and confirms the settings flow renders at the supported terminal size.
- [ ] Real tailnet-device and outside-tailnet witnesses are reported separately as `DEMONSTRATED` or `NOT_DEMONSTRATED`.

## Official references

- [Tailscale Linux installation](https://tailscale.com/docs/install/linux)
- [Tailscale stable packages](https://pkgs.tailscale.com/stable/)
- [Tailscale Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve)
