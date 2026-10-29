# Security Policy

## Security research is welcome

We welcome source review, fuzzing and adversarial testing of ISyCode in
disposable environments you own or have explicit permission to test. Try to
find where its boundaries fail, and help us turn reproducible findings into
fixes and regression tests.

Publishing source code is not proof that the application is secure or has
received an independent audit. This research invitation is separate from the
software license and does not authorize testing other people's installations
or infrastructure.

## Research scope

Use a local checkout, isolated application state, test workspaces, synthetic
data and dummy credentials. Local mock providers, MCP servers and other
services you control are appropriate for reproductions.

We are particularly interested in:

- Effects that bypass Workspace Authority, IsySentinel or the registered
  execution owner, including when a capability is disabled or explicitly denied.
- Escaping workspace/path boundaries, symlink handling, sandbox isolation or
  network destination restrictions.
- Replaying or changing an approved request, single-use approval failures,
  or races between review and execution.
- Leaking credentials, private state or data to an unintended recipient.
- Untrusted file, model or tool content acquiring authority it was not granted.
- Invalid results appearing verified, or action-journal/receipt integrity
  checks accepting modified or missing evidence.
- Authentication, pairing or scope failures in ISyCode-owned integration code,
  reproduced against isolated services you control.

Classic and Security have different intended permissions. Explicitly trusted
Classic workflows can allow ordinary coding effects without a prompt at every
step. A finding should identify the actual unauthorized effect or broken
boundary, and include the mode, grants and folder-trust state.

### Outside this invitation

This invitation does not cover third-party deployments, hosted providers,
production Gateways, other users' workspaces, devices or accounts. An enabled
integration or a credential is not authorization to test its operator's
infrastructure. Obtain separate permission for each external target.

Do not use real user data, extract secrets, disrupt shared services or perform
destructive tests outside your disposable environment. A test of ISyCode's
client does not authorize an attack on the remote service.

## Reporting a vulnerability

**Send security-sensitive details privately.** Do not put a working exploit,
credentials or private data in a public issue, pull request or discussion.

1. Check the repository's [Security advisories page](https://github.com/DannyBaanks/ISyCode/security/advisories).
   If **Report a vulnerability** is available, use GitHub's private reporting
   form.
2. If that button is unavailable, open a
   [minimal contact request](https://github.com/DannyBaanks/ISyCode/issues/new?title=Private%20security%20reporting%20channel%20request)
   asking the maintainer for a private reporting channel. Include **no
   technical details, affected-user information or proof of concept** there.
   Wait for a private channel before sending the report.

A `SECURITY.md` file does not enable GitHub private reporting. See
[GitHub's reporting instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately)
for how to check availability. Reports in English or Spanish are welcome.

### What to include in the private report

- The affected commit or version, OS and relevant runtime/integration versions.
- The workspace mode, effective permissions and explicit folder-trust state.
- The expected boundary and the effect you observed instead.
- Minimal reproduction steps using synthetic data and services you control.
- Sanitized logs, request/receipt identifiers and relevant configuration,
  without real keys, tokens or private file contents.
- Impact, prerequisites, any workaround and your disclosure timeline, if applicable.

Ordinary usability bugs and feature requests can use public issues. When
uncertain whether a finding could expose users, request private contact first.

## Triage and coordinated disclosure

The intended process is to reproduce the report, assess impact, prepare a fix
or mitigation, verify it and coordinate an advisory with the reporter. Please
agree on a disclosure date rather than exposing affected users while a fix is
being prepared. Include any proposed timeline in your initial private report.

There is no guaranteed response time, paid bounty program or promise of
backports under this policy. Security fixes target the latest `main` source;
please include the original affected revision and, where practical, check
whether the finding also reproduces there. A fixed revision is not a general
security certification.

## Architecture and verification

Workspace identity, grants, approvals and execution are separate boundaries.
Provider credentials, MCP scopes, Skills and Bridge leases do not replace local
authority. The remote Gateway also has its own perimeter.

- [Authority and integration reference](docs/reference/authority-and-integrations.md)
- [Security boundary design](docs/design/isysentinel-security-boundaries.md)
- [Verification and outstanding limits](docs/reference/verification.md)
- [Contribution guide](CONTRIBUTING.md)

This policy invites research and defines reporting expectations. It does not
enable runtime capabilities, waive execution checks or approve release gates.
