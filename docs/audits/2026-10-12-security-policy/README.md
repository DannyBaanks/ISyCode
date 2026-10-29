# Security research policy documentation

Prepared 2026-10-12 from local base `204aa75d2be880d51145f740ac53449fecd27d01`.
Scope: root SECURITY.md and navigation from README, CONTRIBUTING, the product
reference and public bug-report form. No execution policy or release gate changed.

The user requested a research-friendly security policy and supplied background
text distinguishing software licensing from authorization to test deployments.
The policy welcomes local, isolated adversarial testing; defines relevant
boundary failures; requests private vulnerability details and coordinated
disclosure; and limits third-party/production testing to separately authorized
targets. It does not claim an MIT license, a completed audit, paid rewards or
response-time guarantees.

GitHub's read-only private-reporting endpoint returned `enabled: false`.
SECURITY.md therefore describes the reporting button conditionally and supplies
a minimal public contact-request fallback containing no vulnerability details.
This follows [GitHub's reporting guidance](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).
No email address or active private channel was invented. No setting, issue,
advisory, push or merge was performed on GitHub.

`evidence/` preserves the API response, command/timestamp/base revision, local
link and whitespace results, and YAML validation. Application tests were not
run for this documentation-only change. `SHA256SUMS.txt` pins the changed
documents and this task's evidence. Older audits remain historical snapshots
of their recorded source revisions; their hashes were not rewritten.
