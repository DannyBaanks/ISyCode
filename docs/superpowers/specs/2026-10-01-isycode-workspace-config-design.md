# ISyCode Workspace Configuration

## Status

Design approved and implemented on 2026-10-01. See
`docs/superpowers/plans/2026-10-01-isycode-workspace-config.md` for the
implementation record and remaining full-suite verification.

## Goal

Give each ISyCode workspace a private, project-local configuration directory
that is selected by that workspace's nearest valid .isyroot. Initialize and
ignore that directory safely while preserving the existing Authority, IsySentinel,
and workspace-boundary contracts.

## User intent

- A workspace with its own .isyroot gets its own .isycode/.
- Different workspaces can use different non-security preferences and prompt
  commands.
- ISyCode adds .isycode/ to that workspace's .gitignore so it is not committed
  accidentally.
- Existing .isycode-commands/ projects keep working.
- The new directory must not become a way for workspace files to grant
  permissions or bypass IsySentinel.

## Workspace identity and placement

discover_workspace_identity() remains the source of workspace identity. The
nearest regular, zero-byte .isyroot selects the canonical workspace root.
Only that root's .isycode/ is loaded; a nested .isyroot begins an independent
configuration scope. No parent, sibling, or other workspace configuration is
merged into the active workspace.

Persistent workspace configuration is created only for identities whose source
is .isyroot. A launch that falls back to its current directory remains
ephemeral and does not silently create .isycode/.

## Directory contents

Version 1 has a deliberately small, non-sensitive surface:

    .isycode/
      config.json
      commands/
        <command-name>.md

config.json stores workspace-level preferences that already exist as
non-authority product defaults, initially default_role, agent_steps,
answer_tokens, and chat_token_budget. It does not store workspace mode,
Authority grants, Sentinel policies, provider credentials, API keys, session
transcripts, receipts, operational state, or caches. Those remain in the
existing private user/runtime storage. New fields require an explicit schema
change and review.

Workspace commands are plain prompt templates. They grant no capabilities;
every action prompted by a command still passes through its normal owner,
Workspace Authority, IsySentinel, and approvals.

## Configuration precedence and validation

For supported preference fields, effective values resolve in this order:

1. ISyCode product defaults.
2. User-wide preferences from UserDefaultsStore.
3. Valid workspace values from .isycode/config.json.
4. Explicit overrides for the current session or request.

Workspace mode, action grants, path scopes, network hosts, executable scopes,
approvals, and Sentinel results are not preferences and cannot be overridden by
this order.

The JSON schema is versioned and bounded. Version 1 validates every supported
field against the same choices and types as UserDefaultsStore. Unknown keys
produce a warning and are ignored. Malformed JSON, invalid values, symlinks,
non-regular files, and unsupported schema versions disable the workspace
configuration as a whole and fall back to product/user defaults; they never
weaken Authority or Sentinel behavior. Schema migration is explicit and
version-to-version, not an opportunistic rewrite during load.

## Authority, Sentinel, and filesystem access

.isyroot continues to set only the maximum filesystem boundary. It is not a
grant.

Reads of .isycode/config.json and workspace command files, and writes that
initialize .isycode/ or update .gitignore, must use existing ISyCode
filesystem owners. Each operation must be represented by its normal immutable
action request and pass Workspace Authority and IsySentinel; writes also retain
the existing fresh-approval requirements. No direct filesystem shortcut,
configuration value, or successful Git-ignore operation may create a grant or
change the boundary.

When reading is denied or the local workspace is unreadable, ISyCode uses only
product and user defaults and reports that workspace settings were unavailable.
When initialization writes are denied, it leaves the workspace unchanged and
continues without persistent workspace settings. It never silently grants
workspace.files.read or workspace.files.write.

All paths are canonicalized beneath the active .isyroot. .isycode/ and its
files must be real directories/regular files, not symlinks. File sizes and
command counts use explicit limits consistent with the existing command
loader.

## Initialization and Git ignore

Initialization is offered for a new or existing marked workspace through the
workspace setup/settings flow. A user must confirm initialization through the
existing workspace write path; opening a project does not silently expand its
permissions.

If Git is available for the workspace, initialization:

1. Checks whether .isycode/ is already tracked through a read-only GitOwner
   path-inspection operation authorized as git.status. If GitOwner cannot prove
   the path is untracked, initialization stops with a warning.
2. If tracked, warns and does not initialize persistent files or change the
   index. It offers a manual remediation explanation; it never runs
   git rm --cached, stages files, commits, or rewrites history.
3. Otherwise, appends this managed block to a regular UTF-8 .gitignore no larger
   than 1 MiB at the workspace root, creating that file if it does not exist:

       # >>> ISYCODE managed block >>>
       .isycode/
       # <<< ISYCODE managed block <<<

   Before appending, it preserves existing bytes/line endings and detects an
   existing exact .isycode/ ignore line so it does not add a duplicate. A
   malformed or duplicate managed block is left untouched and reported.
4. Creates .isycode/config.json with version 1 defaults and the commands/
   directory. Writes use the existing atomic workspace-write path.

If the .gitignore is a symlink, not valid UTF-8, too large, unsafe to update,
or the ignore write is denied, ISyCode does not write the configuration and
reports why. If Git is available and the workspace is a repository but the
read-only tracked-path check is denied or fails, initialization stops rather
than guessing. If the workspace is not a Git repository or Git is unavailable,
initialization may still create .isycode/ after its normal write authorization
and reports that Git ignore could not be installed.

The engine does not modify .git/info/exclude: it can live outside .isyroot
and therefore outside the authority boundary. .gitignore reduces accidental
tracking; it is not represented as protection against git add -f, deletion of
the rule, or other deliberate repository changes. ISyCode therefore never puts
secrets or security grants in .isycode/. If .isycode/ is already tracked,
the engine warns instead of attempting to untrack it.

## Command compatibility

New workspace prompt commands live at .isycode/commands/<name>.md. Existing
.isycode-commands/<name>.md files continue to load during a compatibility
period. Resolution order is:

1. User-wide command with the requested name, preserving current behavior.
2. Workspace command from .isycode/commands/.
3. Legacy workspace command from .isycode-commands/.

The new path wins over the legacy path when both workspace directories define
the same command. Migration is user-invoked and non-destructive: it copies only
validated command text through workspace owners and leaves the source file in
place. There is no automatic move or deletion.

## Non-goals

- Moving Authority grants or IsySentinel policies into the workspace tree.
- Persisting sessions, full action receipts, credentials, tokens, or arbitrary
  operational state in .isycode/.
- Automatic modification of .git/info/exclude.
- Automatic untracking, staging, committing, or migration that deletes legacy
  files.
- Loading settings from another workspace or making repository configuration a
  security policy source.

## Acceptance criteria

1. Two marked workspaces load only their own .isycode/config.json; a nested
   .isyroot isolates settings from its parent.
2. A directory without .isyroot does not gain persistent .isycode/
   configuration through normal launch.
3. All configuration reads/writes are rejected when the applicable owner,
   Authority, Sentinel, or approval denies them; no implicit grant is created.
4. A workspace configuration cannot enable a provider, action, executable,
   host, tool, role capability, or wider filesystem boundary.
5. Schema validation rejects unsafe/malformed files and falls back without
   changing grants, policies, or project contents.
6. Initialization inserts one managed .gitignore block when needed, preserves
   unrelated bytes/line endings, and is idempotent even when .isycode/ is
   already ignored by an existing rule.
7. Tracked .isycode/, read-only paths, symlinks, absent Git, and unsafe
   .gitignore states produce explicit non-destructive outcomes.
8. Existing .isycode-commands/ files continue to work; collisions follow the
   stated precedence and migration never removes a source file.
9. Tests use temporary workspace roots, .isyroot markers, and local Git
   repositories; they do not contact external providers or GitHub.

## Rollout

Implementation will be split into workspace config loading/validation,
owner-gated initialization and Git-ignore management, then TUI integration and
legacy command compatibility. Each stage must keep .isyroot, Workspace
Authority, and IsySentinel tests as explicit security controls. No user
workspace is migrated automatically as part of deployment.
