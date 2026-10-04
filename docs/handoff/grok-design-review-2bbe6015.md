## Design Document Review: Multi Harness: a semantic options graph for ISyCode Classic

### Summary

Needs revision. Issues 1–18 stay addressed. The thirteen-harness catalog, `--version` probe, secret and bypass boundary, N >= 4 rule, separate `web_fetch` / `web_search` nodes, session-list path, provider-copy contract, roots schema, and edge labels match this checkout. The design is not ready to implement until the transcript copy is attached to the open chat's real stores. Painting the column and calling `record` with `state=None` does not, by itself, make the text part of the conversation the model sends or that resume reloads.

### Issue 1: `reasoning_effort` is both joined and not counted

- **Severity**: major
- **Section**: Edges from observed files; Gap rule
- **Description**: The Grok edge maps a real field onto the node, and the worked example then ignores that harness. The edge row says `sessions/*/*/summary.json` allowlists `reasoning_effort` and "`reasoning_effort` → `reasoning_effort`". The gap table says N=3 from Codex `model_reasoning_effort`, Hermes `agent.reasoning_effort`, and FX `settings.json` `effort`, status `WATCH`, and only calls out Kimi `default_effort` as excluded. FX session `effort` is explicitly "not a second user default"; the Grok summary field is not given that exclusion. Counting Grok makes N=4. The target is not `absent` ("Partial: `Provider.reasoning_effort`..."), transfer is `display_only`, and the condition table then says `ALIGNED`, not `WATCH`. `gap_status` compares `isycode_target == "absent"`. The seed cell is the prose "Partial: ...", which is neither `"absent"` nor `src/isycode/...:symbol`. PR 3's map list also omits this field, so the edge table, the N table, and the reader PR disagree. `Provider.reasoning_effort` itself is real (`ISYCODE_REASONING_EFFORT` / `ISYMOTRON_REASONING_EFFORT` / the preset in `providers.py`).
- **Suggestion**: Pick one. Either count Grok, set N=4, and set status to `ALIGNED` with no copy, or stop the edge from joining `reasoning_effort` the way FX session `effort` is excluded, and say so in the edge row and in PR 3. Store `isycode_target` as the literal `absent` or a symbol, not the prose in the table. The same literal rule is what keeps `user_skills` on the `ADD` branch.
- **Status**: addressed
- **Response**: Grok `summary.json` `reasoning_effort` and FX `session.json` `effort` stay per-session and do not join the user-default node. N stays 3 and `WATCH` in the edge table, the gap table, and PRs 3 and 10. `isycode_target` for that node is the symbol `src/isycode/providers.py:Provider.reasoning_effort`. `gap_status` compares only `absent` or a symbol. Verified against the current draft.

### Issue 2: The Sessions button does not open `ChatSessionsScreen`

- **Severity**: major
- **Section**: Background & Motivation; Algorithm step 1
- **Description**: The doc says "The Sessions button opens `ChatSessionsScreen`" and patterns Multi Harness on that class. `ChatSessionsScreen` exists at `src/isycode/tui.py` and is a `ModalScreen`, but nothing in `src/` constructs it. `#sessions-button` calls `_show_chat_sessions`, which hides `#chat` and shows `WorkList` (`src/isycode/work_list.py`). The live list path is `ChatSessionOwner.list_conversations` inside `_refresh_work_list`. A modal can still be the right shell for Multi Harness, because `#command-bar` is outside `#side-panel` and `_set_rail_view` does force the rail visible. The precedent cited for how Sessions works is the wrong screen.
- **Suggestion**: Say the Sessions control opens the in-place work list, and that `ChatSessionsScreen` is an unused modal in the same file. Pattern the new screen on `ModalScreen` without claiming it is the live Sessions UI.
- **Status**: addressed
- **Response**: Background and algorithm step 1 now say `#sessions-button` opens `WorkList` through `list_conversations`. `ChatSessionsScreen` is unused. Multi Harness is a new `ModalScreen` on the command bar, not the live Sessions UI. Verified: `sessions-button` calls `_show_chat_sessions`, and nothing under `src/` constructs `ChatSessionsScreen`. `#command-bar` is under `#composer`, not `#side-panel`.

### Issue 3: `ChatSessionStore.list_sessions` from a `tui.py` screen is a Secure bypass

- **Severity**: major
- **Section**: Display of ISyCode's current value; Where the code lives
- **Description**: The `prior_transcript` row says "Count from `ChatSessionStore.list_sessions`". `secure_tui_direct_api_bypasses` flags `list_sessions`, `load`, `save`, and `import_json` on `ChatSessionStore` when the call is in `TUIApp` or in a `Screen` / `ModalScreen` in `tui.py` that the app constructs. A call on `self.session_store` or `self._chat_sessions` matches the `session_store` / `chat_session` receiver markers. `ChatSessionsScreen` already calls `list_sessions`, and it stays unscanned only because it is never constructed. Pushing a new modal that copies that call fails the gate and changes `docs/security/m15-authority-coverage.json` even if no `ActionRequest` line moves. The owned read is `ChatSessionOwner.list_conversations` (`session.resume`), which is not in that denylist. `list_sessions` also loads message bodies; the row only needs a count.
- **Suggestion**: From the modal, call `ChatSessionOwner.list_conversations` on a worker thread and display `len(sessions)` only. Do not call `ChatSessionStore.list_sessions`, `.load`, `.save`, or `.import_json` in `tui.py`. If the owner is missing or the decision is not `ALLOW`, show that sessions are off instead of reading the store directly.
- **Status**: addressed
- **Response**: The display row, the TUI PR, and PR 20 call `ChatSessionOwner.list_conversations` on a worker thread and show `len` only. A missing owner or a decision other than `ALLOW` shows that sessions are off. The modal does not call the store methods the bypass scanner flags. Verified: `list_conversations` is the covered `session.resume` owner, and `ChatSessionStore.list_sessions` remains on the direct-API denylist.

### Issue 4: Copying `default_model` only through `save_provider_selection` does not change the selection the TUI reads

- **Severity**: major
- **Section**: Seed nodes (`copy_requires`); Display of ISyCode's current value; PR 19
- **Description**: The only writer is `save_provider_selection`, and the row reads `selected_provider_name()` and `selected_model_name()`. Both functions prefer `ISYCODE_PROVIDER` and `ISYCODE_MODEL` over `preferences/provider.json`. The Providers UI sets those variables and then calls `save_provider_selection` (`TUIApp._select_provider`, and the slash path around the same env assignment). A copy that only writes the file leaves this process on the old selection, and the Multi Harness row still shows the old value, while the confirm text says "as ISyCode's selection". The doc also says the open chat's `state.model` stays on the Providers control. Those two stories disagree. Separately, `Provider.__init__` calls `load_provider_key`. Copying `_select_provider` would load a key and can construct a client object. PR 19 does not forbid that. `save_provider_selection` itself is real, casefolds the provider, checks `PRESETS`, and writes `0600` via `O_NOFOLLOW`. It does not apply the `validate_state` model regex; that check has to stay in front of the call, as the doc says.
- **Suggestion**: Say which value the row shows: the process selection (`selected_*`) or the file. If the button is only a persisted default, the confirm text must say the open chat does not switch, and the row must show the saved file when it differs from the env. If the button should switch this process, set `ISYCODE_PROVIDER` and `ISYCODE_MODEL` without constructing `Provider` and without calling `load_provider_key`. Keep the `PRESETS` and `validate_state` checks. Do not write `state.model`.
- **Status**: addressed
- **Response**: The button sets `ISYCODE_PROVIDER` and `ISYCODE_MODEL`, then calls `save_provider_selection`. It does not construct `Provider` or call `load_provider_key`, and it does not write `state.model`. The confirm text says the open chat does not switch. The row shows `selected_*` and the saved file when they differ. `copy_requires` still fails for every live edge, so this machine has no copy button. Open question 5 matches that contract. Verified against `selected_provider_name`, `selected_model_name`, `save_provider_selection`, and `Provider.__init__`.

### Issue 5: Crush and Qwen readers are specified as pick-only

- **Severity**: major
- **Section**: PR 7; PR 8; Catalog and unlock
- **Description**: Unlock says a process that answers `--version` and has a real dot directory unlocks that one folder, and "No response means no automatic folder". PR 7 says "Read Crush options from a user-picked folder only" and "No read unless a picked root is set, because a missing executable must not unlock `~/.crush`". PR 8 says "Picked-root only". That freezes today's missing binaries into the reader. A later `crush` or `qwen` that answers would unlock `~/.crush` or `~/.qwen`, and these readers would still refuse the automatic root. The "Not automatic" table is this machine's probe result, not a second contract. OpenCode's PR does the opposite and correctly handles an automatic root that has no settings.
- **Suggestion**: Both readers accept whatever unlocked root the probe or the pick stored. Tests for a missing executable expect no automatic root. Do not add a code path that ignores an automatic root after a later successful probe. The allowlists stay the ones in the seed.
- **Status**: addressed
- **Response**: PR 7 and PR 8 now read the root the probe or the pick stored. A missing executable still has no automatic root. A later successful probe is not ignored. The allowlists are unchanged.

### Issue 6: `roots.json` is two different schemas

- **Severity**: major
- **Section**: Data model; Data Model Changes
- **Description**: The prose says picked roots live in `roots.json` "as `{harness_id, path}` only". The table says "version 1, map of harness id to one absolute path". A list of objects and a versioned map are not the same file. PR 17 says "Persist `roots.json` mode `0600`" and does not pick one. Overrides are similarly thin: they "may set an edge to `non_equivalent` or mark a semantic id ignored", while the table only says "version 1, edge tightenings only". `gap_status` has no ignored-id input.
- **Suggestion**: Pick one document shape, including `version`, and state that unknown harness ids are rejected. Define the override object and that an ignored id drops out of `N` without flipping `non_transferable` or `secret_skip` to `copyable`.
- **Status**: addressed
- **Response**: Both the prose and the data-model table now use `{"version": 1, "roots": {harness id: absolute path}}`. Overrides are `{"version": 1, "tighten": [...], "ignored": [...]}` and may only tighten an edge to `non_equivalent`. Unknown ids are rejected. An ignored id drops out of `N` and is not a `Gap`. `gap_status` takes that ignored set.

### Issue 7: The edge label `missing here` has no producer

- **Severity**: major
- **Section**: Goals; Algorithm step 6; API / Interface Changes
- **Description**: Rows must say `same`, `missing here`, `not the same`, or `secret, skipped`. `HarnessSetting.edge` is only `same`, `non_equivalent`, or `unmapped`. `SkippedFile` covers secrets. Nothing says which edge becomes `missing here`, or how that differs from the gap string `Missing in ISyCode` (status `ADD`) and `Not an ISyCode setting` (other gaps). `unmapped` is also used both as "no semantic id" and as "points at `permission_mode` until a fixture".
- **Suggestion**: Give a one-line map: `same` → `same`, `non_equivalent` → `not the same`, `SkippedFile(reason="secret")` → `secret, skipped`, and say when `missing here` is used, or drop it. State that `unmapped` does not increment `N`. Keep `Missing in ISyCode` as the `ADD` cell, not as an edge kind.
- **Status**: addressed
- **Response**: Algorithm step 6 and the API strings now use that map. `missing here` is only when this unlocked reader has no setting for an id another unlocked harness returned. `unmapped` does not increment `N`. `Missing in ISyCode` is only the `ADD` cell.

### Issue 8: OpenCode `plugin[]` is three edges at once

- **Severity**: major
- **Section**: Edges from observed files (picked roots); PR 6
- **Description**: The `opencode.jsonc` `plugin[]` cell says "`unmapped` or `enabled_plugins` only as a list of strings, `display_only`. Not the same shape as Claude's bool map; edge `non_equivalent` if both are shown." PR 6 allowlists `plugin` and does not choose. `enabled_plugins` is N=3 from Claude, Codex, and OpenClaw only if OpenCode does not join. Joining it changes that count once the folder is picked.
- **Suggestion**: One edge. Prefer `non_equivalent` to `enabled_plugins` so a string list does not increment that id, and say a picked OpenCode folder does not raise N=3.
- **Status**: addressed
- **Response**: The picked-root row and PR 6 now have one edge: `plugin[]` is `non_equivalent` to `enabled_plugins` and does not increment it. `enabled_plugins` stays N=3 from Claude, Codex, and OpenClaw.

### Issue 9: Transcript copy does not say how the open chat shows it

- **Severity**: major
- **Section**: Algorithm step 9; PR 20
- **Description**: The copy is "into the current ISyCode chat" and the first appended message is "the visible copy line", but the only write named is `ChatSessionOwner.record`. `record` updates the store. The chat column is painted separately (`_mount_user_turn` and `ChatArea`). `_persist_chat_message` also no-ops when `_sessions_enabled()` is false (no owner, or `session.create` / `session.resume` not granted), which is every temporary workspace. `record` rejects any role other than `user` or `assistant`, so the line "Tool or system text was not imported." still needs a role. Passing `state=` replaces `session.state` (`record` assigns `clean_state`). Two hundred `record` calls are two hundred `session.create` receipts. The cap staying under `MAX_MESSAGE_BYTES` (1_000_000) is accurate; the role and paint path are not specified. The "last PR" and "labeled copy" requirements themselves are met.
- **Suggestion**: Paint the label and the capped messages in the open chat column, and call `record` only when sessions are enabled, with `state=None` and role `user` or `assistant` named in the doc. If sessions are off, say whether the copy stays in the in-memory chat or is refused. On `DENY`, show `outcome.reason` and stop. Do not pass a foreign state dict.
- **Status**: addressed
- **Response**: Algorithm step 9 and PR 20 paint the chat column, call `record` only when `_sessions_enabled()` is true, pass `state=None`, and use role `user` or `assistant`. The skipped-role line is one user-role display message. If sessions are off, the copy stays in memory and is not persisted. `DENY` shows `outcome.reason` and stops. No foreign state dict is passed. The remaining live-chat identity gap is Issue 19, not a failure of this paint and `state=None` contract.

### Issue 10: The gap threshold sentence still says "4 or 5"

- **Severity**: minor
- **Section**: Gap rule
- **Description**: "`Danny's threshold is 4 or 5`. Do not lower it to 2. Do not raise it because the catalog is now 13." Every other site, including `gap_status` (`n >= 4`) and Key Decision 6, fixes the threshold at 4. "4 or 5" plus "do not raise it" leaves 5 looking allowed. The worked examples use 4. This is not a lowered threshold.
- **Suggestion**: Delete "or 5". Say the threshold is N >= 4 and is not raised to 5 or to 13.
- **Status**: addressed
- **Response**: The sentence "4 or 5" is gone. The gap rule, Key Decision 6, and PR 1 say the threshold is `N >= 4` and is not raised to 5 or to 13.

### Issue 11: The condition table skips the live `default_model` case

- **Severity**: minor
- **Section**: Gap rule
- **Description**: `ALIGNED` is specified for "`copyable` and `copy_requires` passes" and for "a target exists but transfer is not `copyable`". There is no row for `copyable` when `copy_requires` fails. That is `default_model` on this machine (N=5, no edge pre-declared as passing). The worked example and PR 19 say there is no copy button. The condition table does not.
- **Suggestion**: Add the row: N >= 4, target exists, transfer `copyable`, `copy_requires` fails → `ALIGNED`, show values, no copy button.
- **Status**: addressed
- **Response**: The condition table has that row. The worked `default_model` line is N=5, `ALIGNED`, and has no copy button because every live edge fails `copy_requires`. `gap_status` takes `copy_requires_passes`.

### Issue 12: `permission_mode` is a node, an unmapped edge, and absent from N

- **Severity**: minor
- **Section**: Seed nodes; Edges from observed files; Gap rule
- **Description**: The seed defines `permission_mode` as `display_only`, target `absent`, `NON_EQUIVALENT` to `shell_approval` and `approval_bypass`. The Grok edge is "`unmapped` → `permission_mode` until a fixture." The worked N table has no row. Open question 1 says stay unmapped unless the string is a bypass. An implementer cannot tell whether one Grok field increments N.
- **Suggestion**: State that this edge stays `unmapped`, N=0, until a reviewed fixture assigns it, and that a deny-listed value becomes `approval_bypass` without printing the raw string. Add that row to the worked table or say unmapped ids are omitted on purpose.
- **Status**: addressed
- **Response**: The Grok edge is `unmapped` with `semantic_id` `None`. It does not increment `permission_mode`. The worked table omits unmapped ids on purpose, and the gap-rule notes say so. A deny-listed value becomes `approval_bypass` without printing the string. Open question 1 matches that contract.

### Issue 13: PR 3's map list drops seed edges the N table uses

- **Severity**: minor
- **Section**: PR 3
- **Description**: PR 3 maps `ui.yolo`, `current_model_id`, `ui.auto_dark_theme`, and `trusted`. The seed also maps `ui.vim_mode` → `vim_mode` (the gap table's N=2 is Grok plus Cursor), `sandbox_profile` → `sandbox_policy`, and `ui.fork_secondary_model`. A reader built only from the PR list leaves `vim_mode` at N=1.
- **Suggestion**: Say PR 3 implements every Grok seed pointer, and keep the short list as examples, not as the full map.
- **Status**: addressed
- **Response**: PR 3 now says it implements every Grok seed pointer. The short list includes `ui.vim_mode`, `sandbox_profile`, and `ui.fork_secondary_model`, and it says the summary `reasoning_effort` field does not join the default node.

### Issue 14: `project_instructions` is not "the file exists" when read from `context_path`

- **Severity**: minor
- **Section**: Display of ISyCode's current value
- **Description**: The row says whether the workspace root has `AGENTS.md`, "via the existing context state (`context_path`)". In `_session_state`, `context_path` is `"AGENTS.md"` only after `_agent_context` was loaded. Resume calls `_load_project_context` only when that key is already set. An `AGENTS.md` that was never injected looks absent. `validate_state` accepting only that exact path is accurate.
- **Suggestion**: Label the cell as "loaded in this chat" or stat the workspace file through the existing read owner. Do not dump the body.
- **Status**: addressed
- **Response**: The display cell is `Loaded in this chat` when `context_path` is exactly `AGENTS.md`. An unread file looks not loaded. The screen does not stat it and does not dump the body. Verified: `_session_state` sets `context_path` only when `_agent_context["path"] == "AGENTS.md"`.

### Issue 15: Probe scheduling can stall the modal for the sum of the timeouts

- **Severity**: minor
- **Section**: Algorithm step 2; Catalog and unlock
- **Description**: "Probe the thirteen catalog entries on a worker thread" is one thread. Timeout is 3.0 seconds each. A missing executable returns immediately. One hung binary that must be killed at 3 seconds blocks the other twelve if the thread runs them in order. The UI thread is safe only if the call stays in `asyncio.to_thread`. The modal still waits on the whole batch. No text says what the screen shows during the wait.
- **Suggestion**: Run the thirteen probes concurrently (`asyncio.gather` of `to_thread`), and show a per-harness pending line until that probe returns. Keep one `--version` argv and the 3 second kill.
- **Status**: addressed
- **Response**: Algorithm step 2 and PR 2 run the thirteen probes as `asyncio.gather` of `to_thread`. Each line shows `Checking {Harness}…` until that probe returns. The argv and the 3 second kill are unchanged.

### Issue 16: Two smaller API mismatches

- **Severity**: minor
- **Section**: Background (MCP path); API `gap_status`; picked-root validation
- **Description**: `mcp_local.config_path` is `$XDG_CONFIG_HOME/isycode/mcp.json` or `~/.config/isycode/mcp.json`, not always the home path in the background section. Env values are not printed in `_list_local_mcp` (names and argv only); the digest hash still includes env values. That display claim is close enough. `gap_status` returns `DO_NOT_MERGE` for `secret_skip`, while the gap table says a secret "is not a gap" and the label is `secret, skipped`. `validate_picked_root` rejects `~/.config` and relies on `broad_workspace_reason` for root, home, parents of home, the temp dir, and mount points. `broad_workspace_reason` does not treat `~/.config` as broad, so the extra reject is real and should stay. `~/.local` and `~/.local/share` are not in the reject list. Open question 7 asks about depth and does not close it. A pick is still allowlist-relative, so this is not a home walk.
- **Suggestion**: Cite `config_path()` rather than a single home path. Make `secret_skip` a skip row, not a `Gap`. Reject `~/.local` and `~/.local/share` the same way as `~/.config`, and allow only the named application directories after confirm.
- **Status**: addressed
- **Response**: Background and the MCP display row cite `config_path()`. `gap_status` returns `None` for `secret_skip`. `validate_picked_root` and PR 17 reject `~/.config`, `~/.local`, and `~/.local/share` themselves, and allow a named application directory under them after confirm. Open question 7 matches that rule. Verified: `config_path()` uses `XDG_CONFIG_HOME` or `~/.config`, `ServerConfig.digest` hashes env values, `_list_local_mcp` prints names and argv only, and `broad_workspace_reason` does not treat `~/.config` as broad.

### Issue 17: Copilot JSONC has no read algorithm

- **Severity**: nit
- **Section**: Copilot locked allowlist; PR 15
- **Description**: `config.json` "begins with comments and is not plain JSON." The reader is fixture-only until `copilot` answers, which is right, but the fixture still needs a defined JSONC read. No library or comment-stripping rule is named. A naive `json.loads` will fail the fixture the PR asks for.
- **Suggestion**: Name the JSONC rule in PR 15 (for example, strip comments without evaluating them, then `json.loads`) and keep the live folder unread.
- **Status**: addressed
- **Response**: PR 15 strips `//` line comments and `/* */` block comments without evaluating them, then calls `json.loads`. The live `~/.copilot` folder stays unread until `copilot --version` answers.

### Issue 18: Reusing the Linux picker keeps context-file error strings

- **Severity**: nit
- **Section**: API / Interface Changes
- **Description**: `choose_harness_folder` reuses `_run_picker`. That helper's timeout and OSError text say "Context-file selection" / "native context-file picker". `_choose_windows_directory` hardcodes title "Choose sibling project folder"; the doc correctly says a new title argument must default so the sibling picker does not change. The blocked `choose_workspace_directory` / `choose_workspace_file` message matches the quote in the doc, and both stay `BLOCKED_BY_DESIGN`.
- **Suggestion**: Pass a harness-specific failure string into the picker helper, or catch `FilePickerUnavailable` in `choose_harness_folder` and replace the context-file wording. Keep the Windows title default.
- **Status**: addressed
- **Response**: `choose_harness_folder` catches `FilePickerUnavailable` and replaces the context-file wording with folder-selection text for that harness. The Windows title argument still defaults to `Choose sibling project folder`. PR 17 says the same. Verified against `_run_picker`, `_choose_windows_directory`, and the blocked choosers.

### Issue 19: Transcript copy never joins the open chat's history or session id

- **Severity**: major
- **Section**: Algorithm step 9; PR 20
- **Description**: The copy is specified as paint plus `ChatSessionOwner.record(..., state=None)`. That does not land in the open chat. `TUIApp._run_chat` sends `self._history` to the model. `_mount_user_turn` and `_append` only mount widgets; neither appends to `_history`. Resume rebuilds `_history` from `session.messages` and then paints. `record` creates a new transcript when `session_id` is `None` and appends only when the caller passes an existing id. The returned id is what `_persist_chat_message` stores on `_active_chat_session_id`. The design never names that id. Two hundred calls with `session_id=None` are two hundred new transcripts. The sentence that two hundred `session.create` receipts are accepted does not pin this down: create and append both use action `session.create`. A new conversation from `_start_new_conversation` already has an id from `manage("state", ...)`. Recording with `None` leaves that id pointing at the empty session, so the next real turn persists there and the imported messages stay in a different file. `_persist_chat_message` cannot be reused as written: it passes `state=self._session_state()`, and `record` replaces `session.state` whenever `state` is not `None`. If sessions are off, "stays in memory" is also incomplete unless the messages are appended to `_history`. The model will not see widgets alone. `record` can also return `ERROR` or `NOT_VERIFIABLE`. The draft stops only on `DENY`.
- **Suggestion**: For each capped message, append `{role, content}` to `self._history`, paint a user role with `_mount_user_turn`, and paint an assistant role the way `_resume_chat_session` mounts `RichMarkdown` (not `_append`). Call `record(self._active_chat_session_id, role, content, state=None)` only when `_sessions_enabled()` is true, and set `_active_chat_session_id` to the returned id after the first `ALLOW`. Do not call `_persist_chat_message`. Do not pass `_session_state()` or a foreign state dict. If sessions are off, update `_history` and the widgets only. Stop unless `outcome.decision == "ALLOW"`; show `outcome.reason`. On `NOT_VERIFIABLE` the write may already have happened, so keep that one message and do not retry it into a second session. The first user message remains the visible copy line, in `_history` as well as on screen.
- **Status**: open

### Strengths

- The catalog is exactly `crush`, `qwen`, `opencode`, `claude`, `codex`, `grok`, `hermes`, `fx`, `openclaw`, `pi`, `kimi`, `cursor`, `copilot`. Gemini is excluded. `agent` is not a fourteenth harness and is not Copilot. Kimi unlocks `~/.kimi-code` only. Cursor probes `cursor-agent`, then `cursor`, one `--version`, and only `~/.cursor`. The `cursor` binary is described as absent while the harness still unlocks. No reader PR calls the Cursor reader fixture-only against the live home; PR 14 says the opposite, and tests stay on fixtures. Copilot stays locked, `gh copilot` is not the probe, and `trustedFolders` is not written into `WorkspaceTrust`.
- The probe is `[executable, "--version"]`, no shell. No response leaves the dot folder locked. The threshold is `N >= 4` in the gap rule, `gap_status`, Key Decision 6, and PR 1. It is not 5 and it is not 13. ISyCode is not part of N. A failed probe does not count. Checked automatic-root counts match the edge table for `user_skills` (4, `ADD`), `default_model` (5, `ALIGNED`, no copy button), `prior_transcript` (7), `ui_theme` (3, `WATCH`), `provider_endpoint` (4, `DO_NOT_MERGE`), `folder_trust` (3), `vim_mode` (2), `approval_bypass` (2), and `sandbox_policy` (2). Cursor `display.mode` is not a fourth theme. Cursor `exploreSubagentModel` does not join `default_model`.
- `web_fetch` and `web_search` are separate nodes. Both targets are `absent`. `CHAT_WORKSPACE_TOOLS` is `workspace_list`, `workspace_read`, `workspace_grep`, and `workspace_search`. `codex_connector.py` setting `web_search` to `"disabled"` is not an ISyCode tool. Hermes `web.backend` stays `unmapped` and does not increment either id. Kimi `services.moonshot_fetch` and `services.moonshot_search` stay `provider_endpoint` / `secret_skip`. Cursor `autoAcceptWebSearch` stays `auto_accept_web_search` and `non_transferable`. Both ids are N=0 `WATCH`, not `ADD`, and the click does not add a tool.
- Secrets, approval bypasses, sandbox modes, foreign base URLs, hooks, and trust bits stay `non_transferable` or `secret_skip` and are not copied into grants, Quiet Classic, or `WorkspaceTrust`. `copy_requires` refuses aliases (`gemini` is not `google`; `openai` is not `chatgpt`; `managed:kimi-code` is not a `PRESETS` key). Those `PRESETS` facts match `providers.py`.
- No subprocess is specified inside `tui.py`. `choose_workspace_directory` and `choose_workspace_file` stay blocked with the message that is in `file_picker.py`. No new Authority action is introduced. The idea box is a non-goal. Transcript import is a labeled copy and PR 20. `## Key Decisions` and `## PR Plan` are present, with one reader PR per harness.
- `save_provider_selection`, `ChatSessionStore.validate_state` (the eight keys, `AGENTS.md` only, and the model regex), `quiet_classic` / `QUIET_CLASSIC_ACTIONS`, `discover_servers`, `mcp_local.load_config` / `config_path`, `UserDefaultsStore`, `secure_tui_direct_api_bypasses`, `build_linux_directory_picker_command`, `state_root`, `broad_workspace_reason`, `sandbox_executable`, and the `updater.py` snapshot generator (`json.dumps(..., ensure_ascii=False, indent=2) + "\n"`, no `sort_keys`) match this checkout. Quiet Classic does not cover commits, secrets, credentials, provider calls, config, or authority, and a missing `bwrap` is not an unsandboxed fallback.

## Revision Summary

Issues 1–18 stay `addressed`. None are `wontfix`. Issue 19 is `open`.

The edge table, the N table, and the PR text agree. `reasoning_effort` is N=3 `WATCH` from Codex, Hermes, and FX `settings.json`. Grok's summary field and FX's session `effort` do not join it. `default_model` is N=5 `ALIGNED` with no copy button. `enabled_plugins` stays N=3 because OpenCode `plugin[]` is `non_equivalent`. `permission_mode` is omitted because the live edge is `unmapped`. `secret_skip` is not a `Gap`. The threshold sentence "4 or 5" is gone.

`web_fetch` and `web_search` stay separate, absent, and `WATCH` at N=0. They are not `ADD`. The catalog is still the same thirteen. Gemini is not added. `agent` is not a harness. Cursor stays unlocked through `cursor-agent`. Copilot stays locked until `copilot --version` answers. No ISyCode source was modified and nothing was committed.
