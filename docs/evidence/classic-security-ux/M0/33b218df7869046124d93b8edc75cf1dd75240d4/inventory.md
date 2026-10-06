# Inventario M0 — owners, callsites y tests

SHA medido: `33b218df7869046124d93b8edc75cf1dd75240d4`.
Una clase cuenta como mapeada cuando un test nombra la clase.
Las Systembility no se nombran en tests; se construyen todas en `ProductActionGate.__init__` y se ejercen a través del owner de su acción.
Generado por `inventory_probe.py` en esta misma carpeta.

| Clase | Definición | Callsites (fuera de su archivo) | Tests que nombran la clase |
| --- | --- | --- | --- |
| `ActionApprovalStore` | `isycode/approvals.py` | action_runtime.py, broker.py, command_runner.py, credential_owner.py, git_owner.py, inspection_cli.py, l1.py, mcp_local.py… | test_action_approvals.py, test_audit_recovery.py, test_authority_view.py, test_bridge_presence_owner.py, test_broker_preview.py, test_command_runner.py, test_connected_owner_receipts.py, test_credential_owner.py… |
| `BridgePresenceOwner` | `isycode/bridge_presence.py` | action_coverage.py, tui.py | test_bridge_presence_owner.py |
| `BridgePresenceSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `BrokerManagementOwner` | `isycode/broker.py` | action_coverage.py, tui.py, tui_app_remote.py | test_broker_preview.py |
| `BrokerManagementSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `BrokerPreviewOwner` | `isycode/broker.py` | tui.py | test_broker_preview.py |
| `BrokerPreviewSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `BrokerProvisionOwner` | `isycode/broker.py` | action_coverage.py, tui.py | test_broker_preview.py |
| `BrokerProvisionSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `ChatSessionOwner` | `isycode/session_owner.py` | action_coverage.py, harness_graph.py, inspection_cli.py, tui.py | test_daily_sessions.py, test_session_owner.py, test_session_title_window.py, test_work_list.py |
| `ClipboardOwner` | `isycode/clipboard_owner.py` | action_coverage.py, file_preview.py, tui.py, tui_app_rail.py | test_clipboard_owner.py, test_image_attachments.py, test_secure_tui_surfaces.py |
| `ClipboardSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `CommandProcessSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `CommandRunOwner` | `isycode/command_runner.py` | action_coverage.py, l1.py, tui_app_workspace.py | test_command_cards.py, test_command_runner.py, test_effect_ledger.py, test_egress.py, test_shell_box.py, test_staging.py, test_turn_control.py, test_workspace_trust.py |
| `ContextFilePickerOwner` | `isycode/file_picker.py` | tui.py, tui_app_tools.py, tui_app_workspace.py | test_file_picker.py, test_secure_tui_surfaces.py |
| `CredentialBoundarySystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `CredentialOwner` | `isycode/credential_owner.py` | action_coverage.py, tui.py, tui_app_providers.py | test_action_coverage.py, test_credential_owner.py |
| `CredentialUseOwner` | `isycode/credential_owner.py` | action_coverage.py, headless.py, tui.py | test_credential_owner.py |
| `GatewayMCPInvocationOwner` | `isycode/action_runtime.py` | action_coverage.py, tui.py, tui_app_authority.py, tui_app_remote.py | test_connected_owner_receipts.py |
| `GatewaySemanticOwner` | `isycode/action_runtime.py` | action_coverage.py, tui.py, tui_app_remote.py | test_connected_owner_receipts.py |
| `GatewaySemanticSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `GitOwner` | `isycode/git_owner.py` | action_coverage.py, headless.py, publish.py, tui_app_workspace.py, workspace_config_owner.py | test_egress.py, test_git_owner.py |
| `GitSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `IterationOwner` | `isycode/iteration.py` | action_coverage.py, tui_app_sessions.py, tui_app_tools.py | test_iteration.py, test_iteration_ui.py |
| `LPSSymbolOwner` | `isycode/action_runtime.py` | action_coverage.py, tui.py, tui_app_remote.py, tui_app_workspace.py | test_connected_owner_receipts.py, test_lsp_diagnostics.py |
| `LSPStartSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `LocalMCPOwner` | `isycode/mcp_local.py` | action_coverage.py, tui.py, tui_app_tools.py | test_mcp_local.py |
| `LocalMCPSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `LocalWorkspaceReadOwner` | `isycode/action_runtime.py` | action_coverage.py, file_picker.py, headless.py, prompt_expansion.py, tui.py, tui_app_chat.py, tui_app_tools.py, tui_app_workspace.py… | test_config_revocation.py, test_daily_security_regressions.py, test_gate_equivalence.py, test_owner_fail_closed_witness.py, test_prompt_expansion.py, test_winfs.py, test_workspace_config_owner.py, test_workspace_grep.py… |
| `MCPInvocationSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `MobileHostOwner` | `isycode/mobile_host.py` | action_coverage.py, tui.py, tui_app_remote.py | test_action_coverage.py, test_mobile_host_secure_scopes.py, test_mobile_pair_issue.py |
| `MobileHostSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `ProductActionGate` | `isycode/action_runtime.py` | bridge_presence.py, broker.py, clipboard_owner.py, command_runner.py, credential_owner.py, dry_run.py, git_owner.py, iteration.py… | test_action_audit_segments.py, test_action_coverage.py, test_authority_view.py, test_command_runner.py, test_credential_owner.py, test_daily_provider_regressions.py, test_daily_security_regressions.py, test_file_delete_move.py… |
| `ProviderAuthOwner` | `isycode/provider_auth.py` | action_coverage.py, tui_app_providers.py | test_provider_auth_methods.py |
| `ProviderAuthSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `ProviderNetworkOwner` | `isycode/action_runtime.py` | action_coverage.py, agent_loop.py, anthropic_provider.py, chat_transport.py, headless.py, iteration.py, runtime.py, tui.py… | test_connected_owner_receipts.py, test_diagnostics.py, test_egress.py, test_vision_probe.py |
| `ProviderNetworkSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `PublishOwner` | `isycode/publish.py` | action_coverage.py | test_egress.py, test_turn_control.py |
| `PublishSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `RemoteReadSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `SessionDeleteOwner` | `isycode/action_runtime.py` | action_coverage.py, inspection_cli.py, iteration.py, tui.py, tui_app_sessions.py | test_iteration.py, test_secure_tui_surfaces.py |
| `SessionDeleteSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `SessionStoreSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `SiblingFolderPickerOwner` | `isycode/file_picker.py` | tui.py | test_workspace_folders_tui.py |
| `Systembility` | `isycode/security.py` | action_runtime.py, command_runner.py, git_owner.py, isysentinel.py, lsp.py, staging.py, tui_app_authority.py, workspace_write.py | test_gate_equivalence.py, test_security_contract.py |
| `TailscaleExecutableSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `TailscaleGatewaySystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `TailscaleLoginOwner` | `isycode/tailscale_login.py` | action_coverage.py, tui.py, tui_app_remote.py | test_tailscale_login.py, test_tailscale_tui.py |
| `TailscalePackageInstallOwner` | `isycode/tailscale_install.py` | action_coverage.py, tui.py, tui_app_remote.py | test_tailscale_install.py, test_tailscale_tui.py |
| `TailscalePackageSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `TailscalePrivateServeSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `TailscaleReadOwner` | `isycode/tailscale_read.py` | action_coverage.py, tailscale_login.py, tailscale_serve.py, tui.py, tui_app_remote.py | test_private_tailnet_witness.py, test_tailscale_read.py, test_tailscale_tui.py |
| `TailscaleServeOwner` | `isycode/tailscale_serve.py` | action_coverage.py, tui.py, tui_app_remote.py | test_private_tailnet_witness.py, test_tailscale_serve.py, test_tailscale_serve_hostport.py, test_tailscale_tui.py |
| `WebFetchOwner` | `isycode/web_fetch.py` | action_coverage.py, harness_graph.py, headless.py, tui_app_tools.py | test_harness_graph.py, test_web_fetch.py |
| `WorkspaceConfigBoundary` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `WorkspaceConfigOwner` | `isycode/workspace_config_owner.py` | action_coverage.py, tui.py, tui_app_chat.py | test_action_coverage.py, test_workspace_config_owner.py |
| `WorkspaceReadSystembility` | `isycode/action_runtime.py` | command_runner.py, git_owner.py, lsp.py, staging.py, workspace_write.py | — (vía ProductActionGate) |
| `WorkspaceWriteOwner` | `isycode/workspace_write.py` | action_coverage.py, tui.py, tui_app_workspace.py, workspace_config_owner.py | test_audit_recovery.py, test_daily_security_regressions.py, test_effect_ledger.py, test_file_delete_move.py, test_gate_equivalence.py, test_staging.py, test_winfs.py, test_workspace_config_owner.py… |
| `WorkspaceWriteSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |

Clases inventariadas: 59. Sin test directo: 0.
