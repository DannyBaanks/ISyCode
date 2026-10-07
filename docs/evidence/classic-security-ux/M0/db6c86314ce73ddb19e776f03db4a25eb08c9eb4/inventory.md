# Inventario M0 — owners, callsites y tests

SHA medido: `db6c86314ce73ddb19e776f03db4a25eb08c9eb4`.
Un owner cuenta como mapeado cuando un test nombra la clase.
Las Systembility no se nombran en tests; se construyen todas en `ProductActionGate.__init__` y se ejercen a través del owner de su acción.

| Clase | Definición | Callsites (fuera de su archivo) | Tests que nombran la clase |
| --- | --- | --- | --- |
| `WorkspaceReadSystembility` | `isycode/action_runtime.py` | git_owner.py, lsp.py, workspace_write.py, command_runner.py | — (vía ProductActionGate) |
| `WorkspaceWriteSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `WorkspaceConfigBoundary` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `CommandProcessSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `GitSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `LocalMCPSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `ClipboardSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `ProviderAuthSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `ProviderNetworkSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `RemoteReadSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `CredentialBoundarySystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `SessionStoreSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `SessionDeleteSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `MCPInvocationSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `GatewaySemanticSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `LSPStartSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `BrokerPreviewSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `BrokerProvisionSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `BrokerManagementSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `TailscaleExecutableSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `TailscalePackageSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `TailscaleGatewaySystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `TailscalePrivateServeSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `MobileHostSystembility` | `isycode/action_runtime.py` | — | — (vía ProductActionGate) |
| `ProductActionGate` | `isycode/action_runtime.py` | clipboard_owner.py, broker.py, mobile_host.py, git_owner.py, tui.py, workspace_authority.py, mcp_local.py, tailscale_read.py | test_action_audit_segments.py, test_action_coverage.py, test_authority_view.py, test_command_runner.py, test_credential_owner.py, test_daily_provider_regressions.py |
| `SessionDeleteOwner` | `isycode/action_runtime.py` | tui.py, action_coverage.py | test_secure_tui_surfaces.py |
| `GatewayMCPInvocationOwner` | `isycode/action_runtime.py` | tui.py, action_coverage.py | test_connected_owner_receipts.py |
| `GatewaySemanticOwner` | `isycode/action_runtime.py` | tui.py, action_coverage.py | test_connected_owner_receipts.py |
| `LPSSymbolOwner` | `isycode/action_runtime.py` | tui.py, action_coverage.py | test_connected_owner_receipts.py, test_lsp_diagnostics.py |
| `ProviderNetworkOwner` | `isycode/action_runtime.py` | runtime.py, tui.py, headless.py, anthropic_provider.py, chat_transport.py, agent_loop.py, action_coverage.py | test_connected_owner_receipts.py, test_diagnostics.py |
| `LocalWorkspaceReadOwner` | `isycode/action_runtime.py` | tui.py, headless.py, prompt_expansion.py, file_picker.py, workspace_config_owner.py, action_coverage.py | test_config_revocation.py, test_owner_fail_closed_witness.py, test_prompt_expansion.py, test_winfs.py, test_workspace_config_owner.py, test_workspace_grep.py |
| `ActionApprovalStore` | `isycode/approvals.py` | broker.py, mobile_host.py, git_owner.py, tui.py, action_runtime.py, l1.py, workspace_authority.py, mcp_local.py | test_action_approvals.py, test_authority_view.py, test_broker_preview.py, test_command_runner.py, test_connected_owner_receipts.py, test_credential_owner.py |
| `BrokerPreviewOwner` | `isycode/broker.py` | tui.py | test_broker_preview.py |
| `BrokerProvisionOwner` | `isycode/broker.py` | tui.py, action_coverage.py | test_broker_preview.py |
| `BrokerManagementOwner` | `isycode/broker.py` | tui.py, action_coverage.py | test_broker_preview.py |
| `ClipboardOwner` | `isycode/clipboard_owner.py` | tui.py, file_preview.py, action_coverage.py | test_clipboard_owner.py, test_secure_tui_surfaces.py |
| `CommandRunOwner` | `isycode/command_runner.py` | tui.py, l1.py, action_coverage.py | test_command_runner.py |
| `CredentialOwner` | `isycode/credential_owner.py` | tui.py, action_coverage.py | test_action_coverage.py, test_credential_owner.py |
| `CredentialUseOwner` | `isycode/credential_owner.py` | tui.py, headless.py, action_coverage.py | test_credential_owner.py |
| `ContextFilePickerOwner` | `isycode/file_picker.py` | tui.py | test_file_picker.py, test_secure_tui_surfaces.py |
| `SiblingFolderPickerOwner` | `isycode/file_picker.py` | tui.py | test_workspace_folders_tui.py |
| `GitOwner` | `isycode/git_owner.py` | tui.py, headless.py, workspace_config_owner.py, action_coverage.py | test_git_owner.py |
| `L1Store` | `isycode/l1.py` | — | test_l1.py |
| `LocalMCPOwner` | `isycode/mcp_local.py` | tui.py, action_coverage.py | test_mcp_local.py |
| `MobileHostOwner` | `isycode/mobile_host.py` | tui.py, action_coverage.py | test_action_coverage.py, test_mobile_host_secure_scopes.py, test_mobile_pair_issue.py |
| `ProviderAuthOwner` | `isycode/provider_auth.py` | tui.py, action_coverage.py | test_provider_auth_methods.py |
| `Systembility` | `isycode/security.py` | tui.py, isysentinel.py | — (vía ProductActionGate) |
| `IsySentinel` | `isycode/security.py` | clipboard_owner.py, mobile_host.py, git_owner.py, tui.py, action_runtime.py, headless.py, workspace_authority.py, mcp_local.py | test_secure_tui_surfaces.py, test_security_contract.py |
| `ChatSessionOwner` | `isycode/session_owner.py` | tui.py, action_coverage.py | test_daily_sessions.py, test_session_owner.py |
| `TailscalePackageInstallOwner` | `isycode/tailscale_install.py` | tui.py, action_coverage.py | test_tailscale_install.py, test_tailscale_tui.py |
| `TailscaleLoginOwner` | `isycode/tailscale_login.py` | tui.py, action_coverage.py | test_tailscale_login.py, test_tailscale_tui.py |
| `TailscaleReadOwner` | `isycode/tailscale_read.py` | tui.py, tailscale_serve.py, tailscale_login.py, action_coverage.py | test_private_tailnet_witness.py, test_tailscale_read.py, test_tailscale_tui.py |
| `TailscaleServeOwner` | `isycode/tailscale_serve.py` | tui.py, action_coverage.py | test_private_tailnet_witness.py, test_tailscale_serve.py, test_tailscale_serve_hostport.py, test_tailscale_tui.py |
| `WorkspaceAuthority` | `isycode/workspace_authority.py` | clipboard_owner.py, broker.py, mobile_host.py, git_owner.py, runtime.py, tui.py, action_runtime.py, headless.py | test_action_approvals.py, test_action_audit_segments.py, test_action_coverage.py, test_audit_config_diagnostics.py, test_authority_view.py, test_broker_preview.py |
| `WorkspaceConfigOwner` | `isycode/workspace_config_owner.py` | tui.py, action_coverage.py | test_action_coverage.py, test_workspace_config_owner.py |
| `CheckpointStore` | `isycode/workspace_write.py` | — | test_daily_security_regressions.py |
| `WorkspaceWriteOwner` | `isycode/workspace_write.py` | tui.py, workspace_config_owner.py, action_coverage.py | test_daily_security_regressions.py, test_file_delete_move.py, test_winfs.py, test_workspace_config_owner.py, test_workspace_modes.py, test_workspace_write.py |

Owners sin test que nombre la clase: 0.

Gate de construcción de checks: `src/isycode/action_runtime.py`, `ProductActionGate.__init__`.
