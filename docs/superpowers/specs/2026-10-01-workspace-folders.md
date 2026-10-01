# Additional workspace folders and delegated file-edit approval

The user wants sibling project folders available for reading and editing in the same chat, with each edit reviewed, and an explicit dangerous-mode option to always allow file edits without disabling ISySentinel.

Primary workspace identity, provider grants and sessions remain unchanged. Additional roots are direct sibling directories selected by the user, addressed with a stable alias (`folder` parameter on read/write tools). Each uses its own WorkspaceAuthority, existing read/write owners and action journal. No shared parent boundary, symlink escape, root-to-root move, commands or automatic grant inheritance. Maximum eight additional roots; aliases are bounded ASCII identifiers, excluding `main`.

User-only Folder controls add, browse, remove and configure each root. Adding explicitly grants list/read/search and optionally write for that exact root only. Existing permission state remains separate; removing an attachment removes access from this chat, not unrelated standalone workspace settings. Persisted private attachment metadata is validated and root directory identity rechecked before dispatch. Read-only attachments cap writes even when that folder has a Classic preset.

An always-allow option is limited to creating/editing files, scoped to a selected root and disabled by default. A native warning explains that model mistakes or injected content can overwrite files without diff review; commands/deletes/moves/commits still ask. Enabling requires an explicit confirmation. Disabling is immediate. Automatic execution still mints a fresh short-lived approval bound to the owner's exact immutable request, rechecks current root membership/permission, runs Sentinel and preserves receipts/checkpoints. Results distinguish individual review from delegated approval.

Python >=3.10, Textual1.0.0, existing dependencies only. Model output never manages roots, grants or auto-edit preference. File browser selection does not change primary session/provider/context authority. Optional LSP diagnostics stay on the primary root until explicitly supported per root.
