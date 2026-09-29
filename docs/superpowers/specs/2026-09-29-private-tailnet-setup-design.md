# ISyCode private tailnet setup — design

**Status:** Draft for user review; no implementation authorized yet  
**Date:** 2026-09-29  
**Scope:** Guided private access to the locally running ISyCo Gateway from a
user's own tailnet, managed from ISyCode Settings.

## Goal

Let a user follow a clear, observable setup flow in the TUI to install or
detect Tailscale, authenticate this PC into their own tailnet, and privately
serve the local Gateway to their other authorized devices. Each PC remains its
own host. ISyCode does not need a central public server.

Automation is welcome for installations, tunnel setup, MCP setup, and future
integrations. It never overrides the user's final approval: every state
changing step goes through the action catalog, Workspace Authority,
IsySentinel, a concrete preview, and a fresh one-use approval where required.

## User flow

Entry point: **Settings → Remote access → Private access (Tailscale)**.

1. **Preflight — read only.** Detect OS/distribution, Tailscale CLI and daemon,
   login state, local Gateway health, listener address, existing Serve config,
   and whether the proposed route conflicts. Show findings without starting,
   installing, or changing anything.
2. **Install Tailscale — explicit system change.** For the first supported
   target (Ubuntu/Debian), show the package/repository source and exact planned
   package-manager action. Let the user review and approve it, then invoke a
   narrow package-install owner, never a shell string or downloaded install
   script. Other distributions show official installation steps until their
   installer owners are implemented.
3. **Join the user's tailnet.** If Tailscale is installed but signed out, show
   the exact login action and ask for approval. Start the official CLI login
   flow, present its URL in the TUI, and wait for the user to finish browser
   authentication. ISyCode never asks for, stores, or logs the user's Tailscale
   password, OAuth token, or reusable auth key.
4. **Preview private Serve.** Show the local Gateway target, resulting
   tailnet-only hostname, TLS state, and the exact Serve configuration delta.
   If the existing Serve configuration is incompatible or cannot be safely
   preserved, stop and explain the conflict instead of replacing it.
5. **Enable.** After a fresh approval, configure Serve in the background for
   the Gateway's loopback listener. Keep the Gateway bound to loopback; do not
   bind it to all network interfaces. Funnel/public sharing remains disabled.
6. **Verify and show status.** Confirm the Serve configuration and local
   Gateway health, then display `Private / Online`, the tailnet URL, target,
   and last verification time. This checks connectivity only; it does not
   claim that a semantic operation passed local Authority or approval.
7. **Disable.** Show which ISyCode-owned Serve mapping will be removed and ask
   for approval. Remove only that mapping; preserve unrelated Serve services,
   Tailscale login, firewall settings, packages, and other user configuration.

At every step the user can cancel. Failures leave the last verified state
visible and include a next step; cancellation does not attempt rollback of
unrelated system state.

## Architecture and authority

- Add a Tailscale adapter that reports structured preflight/status data and
  supports only fixed operations such as `status`, `up`/login, Serve enable,
  Serve status, and removal of the exact ISyCode-owned mapping.
- Add narrow execution owners for package installation and Tailscale/Serve
  process operations. Owners accept typed values, validate executable paths,
  enforce output/time limits, and do not invoke an arbitrary shell.
- Register every operation in the ISyCode action catalog and owner coverage
  report. Add applicable Systembilities for package source, executable
  identity, local endpoint, tailnet state, route ownership, and private-only
  exposure. No action becomes available merely because a dependency is
  detected or a grant exists.
- Persist only non-secret setup state in the user-private ISyCode state
  directory: adapter version, owned mapping identity, last-known status, and
  receipts. Never put tokens in the workspace, `.isyroot`, Bridge, logs, or
  action receipts.
- Keep all API key scopes, Gateway workspace IDs, `.isyroot` boundaries,
  filesystem grants, Mobile Host pairing credentials, and MCP permissions
  separate. A Tailscale login or Serve route grants network reachability only;
  it is not an ISyCode action grant.
- Tailscale identity headers may be recorded as untrusted request metadata;
  they must not replace Gateway authentication, device pairing, Workspace
  Authority, Sentinel, or approvals.
- MCP and other tunnel providers can later implement the same guided
  integration pattern, but each needs its own typed contract, owner,
  Systembilities, user preview, and tests. They are not silently included in
  this first adapter.

## Security invariants

1. Default state is disabled; no install, login, Serve, Funnel, or MCP
   mutation occurs during startup or preflight.
2. Every mutation has an exact user-visible plan and final user approval.
3. No implicit `sudo`, `curl | sh`, arbitrary command, or broad package-manager
   execution path.
4. Tailscale Serve is private to the user's tailnet. Funnel and public tunnel
   providers are not offered in this flow.
5. The Gateway remains on loopback; the approved proxy path is the only added
   network reachability.
6. Existing non-ISyCode Serve routes and tailnet configuration are preserved.
   If safe ownership cannot be proved, disable is unavailable and the UI
   explains how to resolve the conflict manually.
7. Tailscale account login, Gateway API keys, provider OAuth, Mobile Host
   pairing, and local workspace grants are distinct identities and controls.
8. Every execution records a redacted, durable receipt. Secrets and auth URLs
   containing credentials are never written to logs or receipts.
9. `.isyroot` remains an empty identity/boundary marker; it does not grant
   filesystem or network access.

## Errors and recovery

- **Missing package privilege:** report the exact package action and let the
  user rerun through the OS authorization prompt; never fall back to an
  unprivileged shell installer.
- **Tailscale daemon unavailable:** report install/service state and offer a
  bounded start action only if its owner and OS privilege contract are
  implemented.
- **Login pending or cancelled:** retain the wizard state without saving
  credentials; provide retry and cancel.
- **Serve conflict:** do not reset all Serve configuration. Show the conflict
  and leave the existing service untouched.
- **Gateway unavailable:** do not enable Serve; show the local health failure.
- **Serve enable succeeds but verification fails:** report the exact owned
  route and offer its approved disable action. Do not claim remote reachability.
- **Tailscale missing or unsupported OS:** keep private access disabled and
  show the official instructions for that platform.

## Out of scope for the first adapter

- Funnel, Cloudflare public tunnels, public DNS, or any Internet-accessible
  endpoint.
- A hosted ISyCo control plane or shared ISyCo Tailscale account.
- Automatically enrolling mobile devices or generating reusable Tailscale
  auth keys.
- Starting the incomplete Mobile Host runtime/session API. This flow serves
  the already-running local Gateway only; Mobile Host requires its own owner
  and secure runtime contract.
- Automatically approving Gateway semantic calls, file access, MCP tools, or
  provider requests.
- Installing MCP servers or configuring MCP credentials in this change.

## Acceptance criteria

- Fresh install, installed-but-signed-out, signed-in, already-served,
  conflicting Serve config, and unsupported distribution are shown as
  distinct preflight states.
- No system mutation occurs from opening Settings, running preflight, or
  cancelling any screen.
- Package install, tailnet login, Serve enable, and Serve disable each require
  the proper owner and explicit request-bound approval.
- Package installation is restricted to supported official repositories and
  exact package names; no dynamic command or shell interpolation is accepted.
- Serve maps only the Gateway loopback endpoint and is confirmed tailnet-only;
  Funnel remains off.
- Enabling and disabling preserve unrelated Serve entries and are idempotent.
- Restart/relaunch status is read from Tailscale and the local Gateway rather
  than inferred from ISyCode's saved preference.
- A real tailnet device can reach the Gateway over Serve; an outside device
  cannot. Gateway key/scope and ISyCode grants remain independently enforced.
- Cancellation, denied privilege, stale approval, wrong executable, route
  drift, timeout, malformed CLI output, and service loss fail closed with a
  durable redacted receipt.

## Implementation phases

1. **Read-only wizard and inventory:** Tailscale/Gateway discovery, settings
   screens, step state, supported-OS guidance, and conflict display.
2. **Action contracts:** catalog entries, Systembilities, approvals, typed
   owners, and receipts for package install and login.
3. **Private Serve lifecycle:** owned mapping, enable/disable, status, and
   preservation of other Serve configuration.
4. **Real-device witness:** pair one tailnet client, verify private URL,
   Gateway auth/scope, cancellation, disable, and outside-tailnet denial.
5. **Future adapters:** add each additional tunnel or MCP manager only after
   its own owner/security design and user-reviewed scope.

**Review note:** Approval of this design authorizes writing a sequenced
implementation plan, not implementation or privileged installation. Each
future install/login/tunnel/MCP change still requires the final user approval
described above.
