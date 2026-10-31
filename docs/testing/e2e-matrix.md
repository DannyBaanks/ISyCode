# Matriz E2E — freeze 2026-10-24

Definición: `docs/handoff/gus-mk6-freeze-2026-10-23.md` §3.4, punto 4.
Durante el freeze solo entran arreglos, pruebas y documentación; cada bug
arreglado trae su prueba.

Estados:

- **COVERED** — una prueba automatizada ejerce el flujo real (TUI, autoridad y
  owner) y corre en CI.
- **PARTIAL** — hay evidencia ejecutada de una parte (transporte, diálogo o una
  sola plataforma), no del flujo completo.
- **NOT_DEMONSTRATED** — no hay evidencia ejecutada.

## Resumen

| Dimensión | Valores | Estado |
|---|---|---|
| Modos | Security, Classic, Flow | COVERED |
| Proveedores | nube y uno local (Ollama) | COVERED |
| Plataformas | Linux, Windows | COVERED |
| Plataformas | macOS (suite completa; sandbox, `prlimit`, `sun_path` y las medidas del soak sin demostrar) | PARTIAL |
| Idiomas | en, es, zh | COVERED |
| Tamaños | 80×24, 100×30, 140×40 | COVERED |
| Fallas de red | 429, 503, stream parcial, DNS, redirect, proxy | COVERED |
| Carpetas adicionales | adjuntar, solo lectura, raíz reemplazada | COVERED |

## Modos

La misma edición (`workspace_edit` sobre `app.py`) recorre la TUI real en los
tres modos:

| Modo | Comportamiento esperado | Evidencia |
|---|---|---|
| Classic | muestra el diff y espera aprobación | `tests/test_e2e_matrix.py::test_the_same_edit_asks_in_classic_runs_quiet_in_flow_and_is_denied_in_security[classic-asks]` |
| Flow | aplica el trabajo local recuperable sin preguntar | `... [flow-quiet]`; `tests/test_flow_mode.py::test_recoverable_local_work_by_profile` |
| Security | no ofrece la herramienta y corta el request al proveedor | `... [security-denied]`; `tests/test_workspace_modes.py::test_security_mode_still_denies_everything_without_grants` |

Contratos de autoridad por modo:

- `tests/test_workspace_modes.py::test_classic_reads_the_workspace_and_still_journals_it`
- `tests/test_workspace_modes.py::test_classic_edits_still_need_the_diff_approval`
- `tests/test_workspace_modes.py::test_classic_talks_only_to_known_provider_hosts`
- `tests/test_workspace_modes.py::test_classic_preset_is_ready_for_coding_but_never_written_to_policy`
- `tests/test_flow_mode.py::test_flow_is_a_mode_with_the_classic_preset_including_turn_undo`
- `tests/test_flow_mode.py::test_flow_keeps_every_other_boundary`
- `tests/test_flow_mode.py::test_flow_in_a_broad_folder_asks_again`
- `tests/test_flow_mode.py::test_flow_without_a_sandbox_runs_no_command`
- `tests/test_daily_security_regressions.py` (revocación explícita, undo y
  delete forjados, autoridad de otro workspace, named pipe)

## Proveedores

| Valor | Evidencia | Estado |
|---|---|---|
| Presets cableados (incluye Ollama, llama.cpp, LM Studio) | `tests/test_provider_catalog.py::test_provider_screen_lists_wired_presets_and_unwired_names` | COVERED |
| Ollama local: endpoint, autoridad y host exacto | `tests/test_daily_provider_regressions.py::test_classic_ollama_custom_endpoint_matches_transport` | COVERED |
| Transporte SSE real con proveedor `local` | `tests/test_stream_proxy.py::test_provider_usage_options_and_final_usage_over_local_sse` (parametrizado `openai`, `nvidia`, `local`, `nebius`) | COVERED |
| TUI + proveedor local por HTTP/SSE real | `tests/test_e2e_matrix.py::test_a_local_provider_answers_through_the_real_tui_transport` | COVERED |
| TUI + proveedores de nube | `tests/test_daily_tui.py` (mock de `provider_complete`); el protocolo real lo cubren los tests de transporte | COVERED |

## Plataformas

| Plataforma | Evidencia | Estado |
|---|---|---|
| Linux | CI `Tests (Linux)` y `Tests (Linux, Textual 8)`: suite completa | COVERED |
| Windows | CI `Tests (Windows)`: suite completa; `platform-parity` agrega contratos nativos y el sandbox de Windows | COVERED |
| macOS | CI `Tests (macOS)`: suite completa en `macos-latest` (Python 3.12), con los huecos de la tabla de abajo; `platform-parity` y `Package (macos-arm64)` corren además | PARTIAL |

El job `native-contracts` corre en `ubuntu-latest`, `windows-latest` y
`macos-latest`. `test-macos` se sumó en este PR y ejecuta
`python -m pytest -q -m "not integration"`: en macOS ya se ejercitan la TUI, la
autoridad, el transporte SSE, los idiomas y el storage nativo. Quedan cuatro
huecos afirmados, cada uno con su marca y su razón escrita en el código:

| Hueco en macOS | Por qué | Dónde está la marca |
|---|---|---|
| Sandbox de comandos | `sandbox_executable()` exige `resource.setrlimit`, `bwrap`, `libseccomp` y `/usr/bin/python3`; sólo Linux los tiene. Sin sandbox no hay comando que revisar y el producto no tiene fallback sin sandbox. | `tests/sandbox_gate.py`: `skipif(sandbox_missing())` con la razón `NOT_DEMONSTRATED:`, aplicado en `test_command_runner.py`, `test_staging.py`, `test_staging_budget.py`, `test_rtk_authority.py`, `test_rtk_integration.py`, `test_flow_mode.py`, `test_gus_guard.py`, `test_grit_peers.py`, `test_turn_control.py`, `test_effect_ledger.py`, `test_workspace_trust.py`, `test_everyday_flows.py`. La auditoría SEAM lo pregunta al propio producto dentro del caso (`HostCannotRunCase` en `src/isycode/gus_seam.py`) y `seam-02-command-l0` queda en `SKIP` esperado, no en `ERROR`. |
| LSP bajo sandbox | `lsp.py` pide `resource.prlimit`, que no existe en macOS; el servidor queda `installed_unavailable`, que es el comportamiento correcto del producto allí. | `tests/test_native_toolkit.py::test_native_lsp_catalog_and_read_only_runtime` |
| Nombre del socket de hook | `sun_path` es de 104 bytes en macOS (108 en Linux); con un `TMPDIR` largo el socket del Hive no cabe y el servidor ni siquiera arranca. | `tests/test_hive_regressions.py::test_hook_server_denies_and_logs_security_violation` |
| Memoria y descendientes del soak | Script que se corre a mano, no en CI. Sin `/proc` no hay RSS actual (en macOS la stdlib sólo da un pico) ni lista de hijos de un proceso; el soak guarda `null` y sus checks `rss` y `no_orphans` quedan en FAIL. | `scripts/soak_g9.py`: `sample_rss()` / `sample_orphans()`; `tests/test_soak_g9_validation.py::test_a_host_that_reports_nothing_about_memory_or_children_claims_nothing` |

Los marcadores anteriores preguntaban por el sistema operativo (`os.name !=
"posix"`), y macOS responde "posix": pedían el sandbox con una capacidad que
este SO no tiene. Ahora preguntan por la capacidad.

`TMPDIR` de macOS llega a la carpeta temporal a través de `/var`, que es un
enlace, y los chequeos de estado privado rechazan una ruta con enlaces. Las
pruebas usan ahora un nombre sin enlaces (`tests/temp_tree.py`: `fresh_tree()` /
`temporary_tree()`); dos lugares del producto hacen lo mismo antes de entregar
el folder a la capa de estado: `gus_seam._temporary_base()` y
`scripts/soak_g9.py`. Los chequeos estrictos no se relajaron.

## Idiomas

| Idioma | Evidencia | Estado |
|---|---|---|
| en | `tests/test_localization.py::test_english_catalog_selection` | COVERED |
| es | `tests/test_localization.py::test_spanish_contextual_message`; `::test_spanish_chrome_and_first_run_options_render`; `::test_spanish_authority_and_palette_options_render` | COVERED |
| zh | `tests/test_localization.py::test_chinese_catalog_selection`; `::test_chinese_chrome_and_approval_buttons_render` | COVERED |
| TUI por idioma | `tests/test_role_cycle.py::test_shift_tab_cycles_roles_and_frames_the_composer` (parametrizado `en`, `es`, `zh`) | COVERED |
| Cobertura del catálogo | `tests/test_localization.py::test_every_literal_ui_message_has_a_catalog_entry` | COVERED |

La prueba nueva de modos corre en `en`; no se repite la edición completa en
`es` y `zh`. Lo que sí está demostrado en esos idiomas es el chrome, las
aprobaciones y el ciclo de roles en la TUI.

## Tamaños

| Tamaño | Evidencia | Estado |
|---|---|---|
| 80×24 | `tests/test_daily_tui.py::test_terminal_sizes_multiline_and_sidebar_shortcuts` | COVERED |
| 100×30 | el mismo test; `tests/test_workspace_folders_tui.py` | COVERED |
| 140×40 | el mismo test; `tests/test_mockup_decisions.py::test_long_command_review_scrolls_without_hiding_either_decision` | COVERED |
| Layout intermedio | `tests/test_integrated_layout.py::test_composer_and_idea_note_fit_beside_sidebar` (80×24 y 120×40) | COVERED |

## Fallas de red

| Falla | Evidencia | Estado |
|---|---|---|
| 429 / 503 / stream parcial en la TUI | `tests/test_daily_tui.py::test_failed_turn_recovers_original_prompt_without_replaying` | COVERED |
| Stream de herramientas desconectado | `tests/test_daily_transport_regressions.py::test_disconnected_tool_stream_is_not_a_successful_turn` | COVERED |
| Cuota y `Retry-After` reales | `tests/test_provider_error_diagnostics.py::test_quota_code_and_retry_after_survive_actual_http_error` | COVERED |
| Página de error que llega a medias (RST) | `tests/test_provider_error_diagnostics.py::test_sync_stream_reports_the_status_when_the_error_page_never_arrives` | COVERED |
| Redirect, proxy y rebind | `tests/test_egress.py::test_g5_02_redirect_proxy_and_rebind_do_not_widen_the_destination` | COVERED |
| DNS fijado a la dirección revisada | `tests/test_dns_pin.py::test_sync_stream_dials_the_reviewed_address` | COVERED |
| Proxy que no recibe la llave | `tests/test_stream_proxy.py::test_https_proxy_denial_never_sends_provider_key` | COVERED |

## Carpetas adicionales

| Caso | Evidencia | Estado |
|---|---|---|
| Adjuntar un hermano con grants exactos | `tests/test_workspace_folders.py::test_attached_folder_persists_with_exact_file_grants` | COVERED |
| Solo lectura limita Classic | `tests/test_workspace_folders.py::test_read_only_attachment_caps_a_classic_workspace` | COVERED |
| Raíz reemplazada o alias eliminado | `tests/test_workspace_folders.py::test_replaced_root_and_removed_alias_do_not_route` | COVERED |
| Security suspende la edición automática | `tests/test_workspace_folders.py::test_security_mode_suspends_saved_automatic_edits` | COVERED |
| Edición aprobada en la TUI usa su propio root | `tests/test_workspace_folders_tui.py::test_sibling_read_and_native_approved_edit_use_its_own_root` | COVERED |
| La carpeta desaparece con el diff abierto | `tests/test_workspace_folders_tui.py::test_folder_removed_while_diff_is_open_cannot_be_written` | COVERED |

## Huecos conocidos

- **macOS, capacidades del SO.** La suite completa corre en macOS, pero el
  sandbox de comandos, el LSP bajo `prlimit`, el socket de hook con un `TMPDIR`
  largo y las medidas del soak (RSS actual y descendientes, que viven en
  `/proc`) no son alcanzables allí; cada uno está marcado con su
  `NOT_DEMONSTRATED` en la tabla de arriba. La auditoría SEAM reporta su hueco
  como el `SKIP` que el roster espera, y el soak guarda `null`: ninguno de los
  dos afirma un verde que no midió. La paridad total con Linux no se afirma.
- **Idiomas en la edición completa.** El viaje de modos corre en `en`. La TUI
  por idioma está cubierta por chrome, aprobaciones y ciclo de roles.
- **Proveedores de nube con transporte real dentro de la TUI.** El protocolo
  real está cubierto a nivel transporte; la TUI usa un proveedor falso en esos
  casos. El proveedor local sí corre con transporte real en la TUI.

## Cómo correr la matriz

```bash
python3 -m pytest -q tests/test_e2e_matrix.py
python3 -m pytest -q tests/test_daily_tui.py tests/test_daily_provider_regressions.py \
  tests/test_stream_proxy.py tests/test_workspace_modes.py tests/test_flow_mode.py \
  tests/test_localization.py tests/test_role_cycle.py tests/test_workspace_folders.py \
  tests/test_workspace_folders_tui.py tests/test_daily_transport_regressions.py
```

En CI, Linux, Windows y macOS corren la suite completa. Las pruebas que
necesitan capacidades que un SO no tiene se saltan con su razón en el nombre
(`tests/sandbox_gate.py`); nada se salta por preguntar sólo el sistema
operativo.
