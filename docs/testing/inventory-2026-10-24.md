# Inventario de módulos ISyCode — estado de pruebas

Generado: 2026-10-24  |  Rama: `origin/main` (fab2d1a, tras PR #95)  |  Worktree: `/tmp/opencode/isycode-refactor` (c1a41ce, PR #96 pendiente de CI)

## Resumen

- Módulos fuente totales: **225**
- Líneas de código totales: **63,375**
- Estable (pruebas directas, CI verde): **95**
- Frágil (solo pruebas flaky/plataforma o cobertura muy baja): **0**
- Sin pruebas (sin archivo de prueba directo): **130**
- Archivos de prueba: **285**  |  Pruebas recolectadas: **2 682**

## Criterios de clasificación

- **estable**: tiene archivo de prueba directa (`tests/test_<modulo>.py`) con ≥1 prueba recolectada.
- **frágil**: tiene pruebas pero son flaky (bloqueo de archivo en Windows, timing de scroll) o módulo grande (>500 líneas) con <5 pruebas.
- **sin pruebas**: no existe archivo de prueba directa para el módulo. Puede tener cobertura indirecta a través de pruebas de TUI o integración, pero no hay pruebas de unidad dedicadas.

> Nota: `tui.py` (2 809 líneas) y los módulos `tui_app_*` no tienen pruebas de unidad directas; se ejercitan indirectamente mediante pruebas de TUI (p. ej. `test_daily_tui.py`, `test_quiet_classic_diff.py`).

## Detalle por módulo

| Módulo | Líneas | Prueba directa | # pruebas | Estado |
|---|---:|---|---:|---|
| `src/isycode/__main__.py` | 6 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/action_audit.py` | 620 | `test_action_audit.py` | 19 | ✅ estable |
| `src/isycode/action_coverage.py` | 835 | `test_action_coverage.py` | 21 | ✅ estable |
| `src/isycode/action_runtime.py` | 2979 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/actions.py` | 116 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/agent_events.py` | 290 | `test_agent_events.py` | 9 | ✅ estable |
| `src/isycode/agent_loop.py` | 139 | `test_agent_loop.py` | 8 | ✅ estable |
| `src/isycode/agent_panel.py` | 119 | `test_agent_panel.py` | 4 | ✅ estable |
| `src/isycode/agent_polling.py` | 87 | `test_agent_polling.py` | 3 | ✅ estable |
| `src/isycode/agent_questions.py` | 62 | `test_agent_questions.py` | 2 | ✅ estable |
| `src/isycode/agent_tasks.py` | 86 | `test_agent_tasks.py` | 13 | ✅ estable |
| `src/isycode/anthropic_provider.py` | 306 | `test_anthropic_provider.py` | 8 | ✅ estable |
| `src/isycode/approvals.py` | 87 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/asyncio_compat.py` | 31 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/authority.py` | 126 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/authority_view.py` | 141 | `test_authority_view.py` | 5 | ✅ estable |
| `src/isycode/bridge.py` | 236 | `test_bridge.py` | 2 | ✅ estable |
| `src/isycode/bridge_contract.py` | 58 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/bridge_coordination.py` | 196 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/bridge_presence.py` | 134 | `test_bridge_presence.py` | 5 | ✅ estable |
| `src/isycode/bridge_tools.py` | 113 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/broker.py` | 947 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/broker_proxy.py` | 113 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/browser_read.py` | 259 | `test_browser_read.py` | 30 | ✅ estable |
| `src/isycode/browser_read_benchmark.py` | 236 | `test_browser_read_benchmark.py` | 7 | ✅ estable |
| `src/isycode/capability_observations.py` | 88 | `test_capability_observations.py` | 3 | ✅ estable |
| `src/isycode/cat_activity.py` | 285 | `test_cat_activity.py` | 7 | ✅ estable |
| `src/isycode/catalog.py` | 153 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/chat_sessions.py` | 514 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/chat_transport.py` | 58 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/cli.py` | 224 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/clipboard_owner.py` | 97 | `test_clipboard_owner.py` | 10 | ✅ estable |
| `src/isycode/codex_connector.py` | 725 | `test_codex_connector.py` | 48 | ✅ estable |
| `src/isycode/command_runner.py` | 484 | `test_command_runner.py` | 33 | ✅ estable |
| `src/isycode/config.py` | 321 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/context_meter.py` | 126 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/continuity_capsule.py` | 248 | `test_continuity_capsule.py` | 14 | ✅ estable |
| `src/isycode/continuity_recovery.py` | 108 | `test_continuity_recovery.py` | 21 | ✅ estable |
| `src/isycode/contracts.py` | 117 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/conversation_lane.py` | 154 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/credential_owner.py` | 186 | `test_credential_owner.py` | 19 | ✅ estable |
| `src/isycode/credentials.py` | 227 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/dataflow.py` | 304 | `test_dataflow.py` | 17 | ✅ estable |
| `src/isycode/decision_view.py` | 23 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/diagnostics.py` | 67 | `test_diagnostics.py` | 4 | ✅ estable |
| `src/isycode/diff_view.py` | 112 | `test_diff_view.py` | 5 | ✅ estable |
| `src/isycode/dry_run.py` | 63 | `test_dry_run.py` | 3 | ✅ estable |
| `src/isycode/effect_fs.py` | 13 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/effect_ledger.py` | 514 | `test_effect_ledger.py` | 10 | ✅ estable |
| `src/isycode/effect_policy.py` | 105 | `test_effect_policy.py` | 4 | ✅ estable |
| `src/isycode/egress.py` | 181 | `test_egress.py` | 8 | ✅ estable |
| `src/isycode/file_picker.py` | 320 | `test_file_picker.py` | 5 | ✅ estable |
| `src/isycode/file_preview.py` | 188 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/folder_screens.py` | 101 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/gateway_client.py` | 127 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/gateway_mcp.py` | 220 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/git_owner.py` | 678 | `test_git_owner.py` | 28 | ✅ estable |
| `src/isycode/grit.py` | 230 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/grok_auth.py` | 96 | `test_grok_auth.py` | 4 | ✅ estable |
| `src/isycode/grok_session.py` | 186 | `test_grok_session.py` | 5 | ✅ estable |
| `src/isycode/gus_context_pack.py` | 165 | `test_gus_context_pack.py` | 12 | ✅ estable |
| `src/isycode/gus_generation.py` | 189 | `test_gus_generation.py` | 17 | ✅ estable |
| `src/isycode/gus_l0.py` | 342 | `test_gus_l0.py` | 43 | ✅ estable |
| `src/isycode/gus_role.py` | 123 | `test_gus_role.py` | 27 | ✅ estable |
| `src/isycode/gus_seam.py` | 541 | `test_gus_seam.py` | 5 | ✅ estable |
| `src/isycode/gus_session.py` | 326 | `test_gus_session.py` | 9 | ✅ estable |
| `src/isycode/gus_slot.py` | 124 | `test_gus_slot.py` | 17 | ✅ estable |
| `src/isycode/harness_copy.py` | 22 | `test_harness_copy.py` | 6 | ✅ estable |
| `src/isycode/harness_graph.py` | 236 | `test_harness_graph.py` | 10 | ✅ estable |
| `src/isycode/harness_probe.py` | 223 | `test_harness_probe.py` | 8 | ✅ estable |
| `src/isycode/harness_readers/_shared.py` | 208 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/claude.py` | 102 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/codex.py` | 46 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/commandcode.py` | 50 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/copilot.py` | 31 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/crush.py` | 41 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/cursor.py` | 56 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/fx.py` | 88 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/grok.py` | 116 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/hermes.py` | 91 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/kilo.py` | 20 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/kimi.py` | 97 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/openclaw.py` | 64 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/opencode.py` | 67 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/pi.py` | 37 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/qwen.py` | 42 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_readers/transcript.py` | 134 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/harness_store.py` | 92 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/headless.py` | 247 | `test_headless.py` | 7 | ✅ estable |
| `src/isycode/hive/guard.py` | 103 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/hive/hook_server.py` | 180 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/hive/hook_shim.py` | 198 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/hive/manager.py` | 810 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/hive/router.py` | 196 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/hive/safe_io.py` | 72 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/hive/spawn.py` | 42 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/hive/types.py` | 208 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/hive_bridge.py` | 174 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/idea_box.py` | 58 | `test_idea_box.py` | 5 | ✅ estable |
| `src/isycode/image_attachments.py` | 99 | `test_image_attachments.py` | 5 | ✅ estable |
| `src/isycode/inspection_cli.py` | 248 | `test_inspection_cli.py` | 3 | ✅ estable |
| `src/isycode/instruction_queue.py` | 202 | `test_instruction_queue.py` | 8 | ✅ estable |
| `src/isycode/integration_tools.py` | 128 | `test_integration_tools.py` | 8 | ✅ estable |
| `src/isycode/isysentinel.py` | 373 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/iteration.py` | 396 | `test_iteration.py` | 21 | ✅ estable |
| `src/isycode/l1.py` | 262 | `test_l1.py` | 5 | ✅ estable |
| `src/isycode/launcher.py` | 158 | `test_launcher.py` | 11 | ✅ estable |
| `src/isycode/localization.py` | 191 | `test_localization.py` | 15 | ✅ estable |
| `src/isycode/lsp.py` | 655 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/mcp_local.py` | 417 | `test_mcp_local.py` | 27 | ✅ estable |
| `src/isycode/mcp_presets.py` | 49 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/mobile_host.py` | 568 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/model_card.py` | 107 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/model_catalog.py` | 56 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/model_presentation.py` | 30 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/notification_sounds.py` | 9 | `test_notification_sounds.py` | 1 | ✅ estable |
| `src/isycode/openisy_client.py` | 211 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/operation_style.py` | 44 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/pasted_text.py` | 26 | `test_pasted_text.py` | 4 | ✅ estable |
| `src/isycode/platform_clipboard.py` | 11 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_git.py` | 22 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_posix_clipboard.py` | 66 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_posix_effect_fs.py` | 129 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_posix_sandbox.py` | 174 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_posix_storage.py` | 78 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_sandbox.py` | 15 | `test_platform_sandbox.py` | 6 | ✅ estable |
| `src/isycode/platform_storage.py` | 51 | `test_platform_storage.py` | 13 | ✅ estable |
| `src/isycode/platform_windows_clipboard.py` | 104 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_windows_effect_fs.py` | 93 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_windows_git.py` | 93 | `test_platform_windows_git.py` | 5 | ✅ estable |
| `src/isycode/platform_windows_sandbox.py` | 188 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_windows_sandbox_process.py` | 244 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_windows_sandbox_recovery.py` | 174 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_windows_sandbox_registry.py` | 134 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_windows_sandbox_resources.py` | 302 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_windows_sandbox_volume.py` | 125 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_windows_sandbox_volume_api.py` | 337 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/platform_windows_storage.py` | 194 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/plugins.py` | 64 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/private_access.py` | 234 | `test_private_access.py` | 16 | ✅ estable |
| `src/isycode/prompt_expansion.py` | 119 | `test_prompt_expansion.py` | 8 | ✅ estable |
| `src/isycode/provider_auth.py` | 193 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/provider_auth_screens.py` | 79 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/provider_errors.py` | 81 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/providers.py` | 718 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/publish.py` | 123 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/reasoning_options.py` | 205 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/receipts.py` | 66 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/rtk_integration.py` | 345 | `test_rtk_integration.py` | 17 | ✅ estable |
| `src/isycode/rtk_tui.py` | 136 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/runtime.py` | 212 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/safety.py` | 235 | `test_safety.py` | 10 | ✅ estable |
| `src/isycode/search.py` | 43 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/security.py` | 199 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/semantic_gateway.py` | 195 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/sensitive_paths.py` | 21 | `test_sensitive_paths.py` | 43 | ✅ estable |
| `src/isycode/sentinel_rail.py` | 131 | `test_sentinel_rail.py` | 6 | ✅ estable |
| `src/isycode/session.py` | 372 | `test_session.py` | 5 | ✅ estable |
| `src/isycode/session_owner.py` | 386 | `test_session_owner.py` | 11 | ✅ estable |
| `src/isycode/shortcuts.py` | 41 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/skill_catalog.py` | 49 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/staging.py` | 570 | `test_staging.py` | 14 | ✅ estable |
| `src/isycode/startup_art.py` | 54 | `test_startup_art.py` | 6 | ✅ estable |
| `src/isycode/state_index.py` | 90 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/streaming.py` | 491 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/subagent_screen.py` | 102 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/subagents.py` | 54 | `test_subagents.py` | 7 | ✅ estable |
| `src/isycode/tailscale.py` | 373 | `test_tailscale.py` | 23 | ✅ estable |
| `src/isycode/tailscale_install.py` | 939 | `test_tailscale_install.py` | 28 | ✅ estable |
| `src/isycode/tailscale_login.py` | 308 | `test_tailscale_login.py` | 10 | ✅ estable |
| `src/isycode/tailscale_read.py` | 85 | `test_tailscale_read.py` | 2 | ✅ estable |
| `src/isycode/tailscale_serve.py` | 427 | `test_tailscale_serve.py` | 23 | ✅ estable |
| `src/isycode/terminal_art.py` | 133 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/terminal_safety.py` | 53 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/throughput.py` | 78 | `test_throughput.py` | 1 | ✅ estable |
| `src/isycode/tool_history.py` | 97 | `test_tool_history.py` | 37 | ✅ estable |
| `src/isycode/tui.py` | 2809 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_app_authority.py` | 957 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_app_chat.py` | 1216 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_app_gus.py` | 231 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_app_menu.py` | 1324 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_app_providers.py` | 1319 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_app_rail.py` | 992 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_app_remote.py` | 840 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_app_sessions.py` | 1577 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_app_tools.py` | 1303 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_app_workspace.py` | 926 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_composer.py` | 214 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_copy.py` | 236 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_dialog.py` | 140 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_effort_slider.py` | 167 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_presentation.py` | 45 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_protocols.py` | 82 | `test_tui_protocols.py` | 2 | ✅ estable |
| `src/isycode/tui_screens_approval.py` | 797 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_screens_grants.py` | 657 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_screens_gus.py` | 173 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_screens_harness.py` | 885 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_screens_help.py` | 94 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_screens_mcp.py` | 468 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_screens_sessions.py` | 739 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_theme.py` | 236 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/tui_widgets.py` | 964 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/turn_control.py` | 340 | `test_turn_control.py` | 11 | ✅ estable |
| `src/isycode/turn_events.py` | 69 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/turn_journal.py` | 297 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/turn_resume.py` | 20 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/updater.py` | 903 | `test_updater.py` | 40 | ✅ estable |
| `src/isycode/usage.py` | 142 | `test_usage.py` | 83 | ✅ estable |
| `src/isycode/user_defaults.py` | 209 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/village_art.py` | 35 | `test_village_art.py` | 4 | ✅ estable |
| `src/isycode/vision_probe.py` | 118 | `test_vision_probe.py` | 7 | ✅ estable |
| `src/isycode/web_fetch.py` | 198 | `test_web_fetch.py` | 22 | ✅ estable |
| `src/isycode/windows_sandbox_storage_cli.py` | 138 | `test_windows_sandbox_storage_cli.py` | 9 | ✅ estable |
| `src/isycode/winfs.py` | 247 | `test_winfs.py` | 6 | ✅ estable |
| `src/isycode/work_list.py` | 355 | `test_work_list.py` | 11 | ✅ estable |
| `src/isycode/workspace.py` | 348 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/workspace_authority.py` | 445 | `test_workspace_authority.py` | 8 | ✅ estable |
| `src/isycode/workspace_config.py` | 93 | `test_workspace_config.py` | 17 | ✅ estable |
| `src/isycode/workspace_config_owner.py` | 243 | `test_workspace_config_owner.py` | 19 | ✅ estable |
| `src/isycode/workspace_folders.py` | 253 | `test_workspace_folders.py` | 22 | ✅ estable |
| `src/isycode/workspace_memory.py` | 668 | `test_workspace_memory.py` | 7 | ✅ estable |
| `src/isycode/workspace_pack.py` | 289 | `test_workspace_pack.py` | 7 | ✅ estable |
| `src/isycode/workspace_setup.py` | 165 | `-` | 0 | ❌ sin pruebas |
| `src/isycode/workspace_trust.py` | 365 | `test_workspace_trust.py` | 14 | ✅ estable |
| `src/isycode/workspace_write.py` | 1254 | `test_workspace_write.py` | 38 | ✅ estable |

---
*Fuente: `src/isycode/` rastreado con `pytest --collect-only` sobre `tests/`. Estados basados en evidencia de disco, no en memoria.*