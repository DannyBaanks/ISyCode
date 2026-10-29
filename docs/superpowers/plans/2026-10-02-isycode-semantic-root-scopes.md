# Alcances de filesystem con ancla semántica — Plan de implementación

> **Para agentes de implementación:** SUBHABILIDAD REQUERIDA: usar `superpowers:subagent-driven-development` (recomendado) o `superpowers:executing-plans` para implementar este plan tarea por tarea. Los pasos usan casillas (`- [ ]`) para registrar el avance.

**Objetivo:** Permitir descubrir ancestros y proyectos visibles desde un workspace y conceder acceso local, explícito y revocable a rutas exactas sin convertir `.isyroot` en un candado.

**Arquitectura:** `.isyroot` seguirá identificando el workspace semántico. Un registro privado por workspace conservará alcances externos y sus capacidades; Workspace Authority y las Systembilities resolverán cada petición contra ese registro y el owner correspondiente. La TUI pedirá permisos de una vez o recordados, y el sandbox montará únicamente las raíces exactas autorizadas.

**Tecnologías:** Python 3.10+, pytest, Textual 8.2.8, picker nativo existente (Tk en Windows; Zenity/KDialog en Linux), Bubblewrap en Linux. No se agregan dependencias.

**Especificación:** `docs/superpowers/specs/2026-10-02-isycode-semantic-root-scopes-design.md`

## Restricciones globales

- `.isyroot` identifica el proyecto lógico activo; no es una frontera de descubrimiento ni concede acceso.
- Descubrir rutas revela metadatos básicos; no habilita leer contenido ni ejecutar comandos.
- Leer, inyectar contexto, editar o ejecutar requiere autorización explícita.
- Los grants recordados viven en estado privado de ISyCode para ese usuario y equipo; no se sincronizan ni se exportan.
- No se crean ni modifican `.isyroot`, configuración del proyecto ni archivos Git al conceder permisos.
- Cada acción sigue pasando por Workspace Authority, ISySentinel y su execution owner.
- Lectura/contexto, edición y ejecución son capacidades separadas; denegar y cancelar no mutan el workspace.
- IsyMotron y el sistema operativo son capas de permisos separadas; sus grants no se infieren.
- Enlaces simbólicos, secretos, contenido sensible y errores de aislamiento siguen denegados.
- Ningún fallo del sandbox permite ejecutar el comando directamente como fallback.
- Los cambios de código deben preservar los cambios locales que ya existan en el árbol.
- El árbol ya contiene cambios locales previos en README, CI y módulos de ISyCode; antes de implementar se registra su diff base y no se stagea/commitea un archivo completo si eso incorpora hunks previos fuera de la tarea.

## Enfoque de revisión

- **Ruta reemplazada entre consentimiento y uso:** la identidad del directorio cambia; el owner vuelve a validar y deniega la acción.
- **Symlink en un ancestro o dentro del alcance:** la resolución no sigue el enlace y no expone contenido externo.
- **Registro privado inválido o permisos débiles:** no se carga parcialmente ni se convierte en grant permisivo.
- **Carpeta con `.isyroot` anidado:** conserva identidad/configuración propias y no hereda grants del workspace activo.
- **Comando con varias raíces/capacidades:** el digest vincula rutas y permisos exactos; máscaras sensibles se recalculan en cada raíz.

## Mapa de archivos

- `src/isycode/path_scopes.py` — registro privado versionado, identidad de directorios y grants persistentes/de una sola petición.
- `src/isycode/path_discovery.py` — navegación de ancestros y enumeración superficial de candidatos visibles, sin leer contenido.
- `src/isycode/security.py`, `workspace_authority.py`, `action_runtime.py` — enlace inmutable entre workspace semántico, scope, acción y Sentinel.
- `src/isycode/file_picker.py`, `folder_screens.py`, `tui.py` — selección humana, confirmación del agente, lista/revocación y recorrido por carpetas.
- `src/isycode/workspace_folders.py` — compatibilidad de las adjunciones actuales durante migración a scopes centrales.
- `src/isycode/workspace_write.py`, `git_owner.py` — operaciones bajo raíz autorizada manteniendo approval y journal del owner.
- `src/isycode/command_runner.py` — mounts Bubblewrap exactos y máscaras de datos sensibles para cada raíz.
- `tests/test_path_scopes.py`, `test_path_discovery.py`, `test_workspace_authority.py`, `test_security_contract.py`, `test_workspace_root.py`, `test_workspace_folders.py`, `test_workspace_folders_tui.py`, `test_file_picker.py`, `test_workspace_write.py`, `test_git_owner.py`, `test_tool_protocol.py`, `test_action_coverage.py`, `test_command_runner.py`, `test_command_runner_tui.py` — pruebas de contrato por componente.
- `README.md`, `docs/daily-use-readiness.md` — guía de usuario y descripción de límites actualizadas en español.

---

### Tarea 1: Registro privado de alcances

**Archivos:**
- Crear: `src/isycode/path_scopes.py`
- Crear: `tests/test_path_scopes.py`
- Consultar: `src/isycode/workspace_setup.py` para `state_root()` y los patrones de persistencia atómica.

**Interfaces:**
- Produce `FilesystemScope(scope_id: str, root: Path, actions: frozenset[str], identity: tuple[int, int], persistent: bool)`.
- Produce `WorkspaceScopeRegistry(workspace_root: Path, *, state_directory: Path | None = None)` con `list_scopes() -> tuple[FilesystemScope, ...]`, `grant(path: Path, actions: set[str], *, remember: bool) -> FilesystemScope`, `resolve(scope_id: str, action_id: str, target: Path) -> FilesystemScope`, `revoke(scope_id: str) -> None`.
- `remember=False` permanece solo en memoria del registro actual; `remember=True` se guarda en estado privado.
- El scope `main` representa la identidad activa, pero sus acciones siguen necesitando los grants de Workspace Authority ya existentes; el registro no lo convierte en acceso implícito.

- [ ] **Paso 1: Escribir pruebas fallidas** `test_scope_registry_keeps_one_shot_grants_in_memory`, `test_scope_registry_persists_exact_actions_and_revokes` y `test_scope_registry_rejects_changed_identity_symlink_and_unsafe_state`. Afirmar que una concesión de una vez no sobrevive a recrear el registro, que guardar/revocar persiste acciones exactas y que cambiar inode/enlace/estado privado da DENY.
- [ ] **Paso 2: Ejecutar las pruebas enfocadas para confirmar el fallo inicial**.

  Ejecutar: `pytest tests/test_path_scopes.py -q`

  Esperado: FAIL porque no existe `WorkspaceScopeRegistry`.

- [ ] **Paso 3: Implementar `FilesystemScope` y `WorkspaceScopeRegistry`** en `src/isycode/path_scopes.py` con JSON versionado, archivo 0600/directorio 0700 en POSIX, escritura atómica, esquema acotado y fallo cerrado.
- [ ] **Paso 4: Completar `test_scope_registry_rejects_changed_identity_symlink_and_unsafe_state`** con ruta malformada, archivo de estado enlazado, permisos inseguros y política corrupta; afirmar que `resolve()` deniega cada caso sin reescritura permisiva.
- [ ] **Paso 5: Ejecutar la suite enfocada y revisar el diff**.

  Ejecutar: `pytest tests/test_path_scopes.py -q`

  Esperado: PASS; no se crean archivos dentro de las carpetas registradas.

- [ ] **Paso 6: Confirmar solo los archivos de esta tarea**.

  Ejecutar: `git add src/isycode/path_scopes.py tests/test_path_scopes.py && git commit -m "feat: add private filesystem scope registry" -- src/isycode/path_scopes.py tests/test_path_scopes.py`

### Tarea 2: Vincular scopes con Authority y Sentinel

**Archivos:**
- Modificar: `src/isycode/security.py`
- Modificar: `src/isycode/workspace_authority.py`
- Modificar: `src/isycode/action_runtime.py`
- Modificar: `tests/test_workspace_authority.py`, `tests/test_security_contract.py`, `tests/test_workspace_root.py`

**Interfaces:**
- `ActionRequest` agrega `scope_id: str = "main"`; su `digest` incluye el ID y conserva compatibilidad de llamadas existentes.
- `WorkspaceAuthority(root, *, scope_registry: WorkspaceScopeRegistry | None = None)` resuelve grants persistentes existentes y scopes nuevos con `resolve(scope_id, action_id, target)`.
- `WorkspaceReadSystembility` y `WorkspaceWriteSystembility` validan el mismo scope y mantienen filtros de sensibles/enlaces simbólicos.

- [ ] **Paso 1: Escribir pruebas fallidas** `test_action_request_digest_binds_scope_id`, `test_authority_rejects_ungranted_or_wrong_scope_action` y `test_read_systembility_denies_scope_escape_and_sensitive_path`. Afirmar que el digest cambia, scope/acción/target no coincidentes deniegan y el permiso raíz actual sigue dependiendo del grant de acción.
- [ ] **Paso 2: Ejecutar pruebas de Authority/Sentinel para confirmar que fallan**.

  Ejecutar: `pytest tests/test_workspace_authority.py tests/test_security_contract.py tests/test_workspace_root.py -q`

  Esperado: FAIL en los casos nuevos por falta de soporte para `scope_id`.

- [ ] **Paso 3: Implementar resolución de scope en `ActionRequest` y `WorkspaceAuthority.evaluate()`**, sin confiar en parámetros elegidos por el modelo y sin eliminar el grant de acción existente.
- [ ] **Paso 4: Cambiar las Systembilities de lectura/escritura** para verificar `scope_id`, acción, canonicalización y target; mantener resultados puros y denegar ante registro no disponible.
- [ ] **Paso 5: Ejecutar las suites enfocadas y verificar que los controles existentes de root, symlink y digest siguen pasando**.

  Ejecutar: `pytest tests/test_workspace_authority.py tests/test_security_contract.py tests/test_workspace_root.py -q`

  Esperado: PASS.

- [ ] **Paso 6: Confirmar solo los archivos de esta tarea**.

  Ejecutar: `git add src/isycode/security.py src/isycode/workspace_authority.py src/isycode/action_runtime.py tests/test_workspace_authority.py tests/test_security_contract.py tests/test_workspace_root.py && git commit -m "feat: authorize filesystem actions by scope" -- src/isycode/security.py src/isycode/workspace_authority.py src/isycode/action_runtime.py tests/test_workspace_authority.py tests/test_security_contract.py tests/test_workspace_root.py`

### Tarea 3: Descubrimiento superficial y selección de carpetas

**Archivos:**
- Crear: `src/isycode/path_discovery.py`
- Crear: `tests/test_path_discovery.py`
- Modificar: `src/isycode/file_picker.py`, `src/isycode/workspace_folders.py`
- Modificar: `tests/test_file_picker.py`, `tests/test_workspace_folders.py`

**Interfaces:**
- Produce `discover_ancestors(workspace_root: Path) -> tuple[Path, ...]` y `list_visible_directories(parent: Path) -> tuple[PathCandidate, ...]`; devuelven solo metadatos de directorios directos y no siguen enlaces.
- Produce `WorkspaceFolderPickerOwner(workspace_root: Path)` que acepta una carpeta visible existente fuera del root sin limitarse a hermanos directos; los permisos los concede después `WorkspaceScopeRegistry`, nunca el picker.
- `WorkspaceFolders` expone y valida registros históricos, pero deja de crear grants independientes al registrar nuevas carpetas.
- El scope principal continúa consultando los `path_prefixes` del grant de acción existente; solo una ruta externa usa su registro de scope.

- [ ] **Paso 1: Escribir pruebas fallidas** `test_discover_ancestors_is_shallow_and_ordered`, `test_list_visible_directories_omits_symlinks_and_private_state` y `test_folder_picker_accepts_visible_non_sibling_without_grant`. Afirmar que la lista solo contiene ancestros/candidatos de un nivel, sin leer archivos, y que la selección no crea grants.
- [ ] **Paso 2: Ejecutar las pruebas enfocadas y confirmar los fallos nuevos**.

  Ejecutar: `pytest tests/test_path_discovery.py tests/test_file_picker.py tests/test_workspace_folders.py -q`

  Esperado: FAIL en funciones/clases nuevas; las protecciones existentes se mantienen.

- [ ] **Paso 3: Implementar descubrimiento de solo metadatos** con navegación acotada a la cadena de ancestros y enumeración de un nivel bajo demanda; no recorrer recursivamente el home.
- [ ] **Paso 4: Generalizar el picker de carpetas** para seleccionar una ruta existente en el filesystem visible, rechazando raíces privadas de ISyCode y enlaces simbólicos.
- [ ] **Paso 5: Ejecutar las suites enfocadas y verificar que seleccionar un path no escribe ni concede ningún permiso**.

  Ejecutar: `pytest tests/test_path_discovery.py tests/test_file_picker.py tests/test_workspace_folders.py -q`

  Esperado: PASS.

- [ ] **Paso 6: Confirmar solo los archivos de esta tarea**.

  Ejecutar: `git add src/isycode/path_discovery.py src/isycode/file_picker.py src/isycode/workspace_folders.py tests/test_path_discovery.py tests/test_file_picker.py tests/test_workspace_folders.py && git commit -m "feat: discover and select external project paths" -- src/isycode/path_discovery.py src/isycode/file_picker.py src/isycode/workspace_folders.py tests/test_path_discovery.py tests/test_file_picker.py tests/test_workspace_folders.py`

### Tarea 4: Solicitud del agente, confirmación, lectura, edición y revocación

**Archivos:**
- Modificar: `src/isycode/folder_screens.py`, `src/isycode/tui.py`, `src/isycode/file_picker.py`
- Modificar: `src/isycode/action_runtime.py`, `src/isycode/workspace_write.py`, `src/isycode/git_owner.py`
- Modificar: `tests/test_workspace_folders_tui.py`, `tests/test_workspace_write.py`, `tests/test_workspace_write_tui.py`, `tests/test_git_owner.py`, `tests/test_tool_protocol.py`

**Interfaces:**
- La TUI abre `WorkspaceAccessRequestScreen(path, actions, identity)` y recibe únicamente `AccessChoice(actions, remember)` o cancelación.
- `request_workspace_access` solicita una ruta y acciones concretas; el handler del agente no puede mutar el registro y solo el resultado afirmativo del diálogo llama a `WorkspaceScopeRegistry.grant()`.
- Los owners reciben `scope_id` y validan cada ruta con Workspace Authority y Sentinel antes de leer, escribir o consultar Git.

- [ ] **Paso 1: Escribir pruebas fallidas** `test_access_dialog_cancel_does_not_grant`, `test_agent_access_request_requires_human_confirmation`, `test_remembered_scope_keeps_only_selected_actions`, `test_scope_identity_change_during_dialog_denies` y `test_revocation_invalidates_pending_request`. Afirmar además que argumentos incompletos de `request_workspace_access` se rechazan y no modifican el registro.
- [ ] **Paso 2: Ejecutar pruebas TUI/owners para confirmar fallos de los nuevos flujos**.

  Ejecutar: `pytest tests/test_workspace_folders_tui.py tests/test_workspace_write.py tests/test_workspace_write_tui.py tests/test_git_owner.py tests/test_tool_protocol.py -q`

  Esperado: FAIL solo en los comportamientos nuevos.

- [ ] **Paso 3: Implementar el diálogo reutilizable** con ruta completa, alcance por capacidad sin selección predeterminada, opción de recordar en este equipo y cancelar sin cambios.
- [ ] **Paso 4: Registrar `request_workspace_access` en `action_runtime.py`, el dispatcher de la TUI y las instrucciones de herramientas**, conectando el selector y la solicitud del agente al mismo diálogo. La respuesta humana queda ligada a ruta, acciones e identidad presentadas.
- [ ] **Paso 5: Pasar `scope_id` por los owners de lectura, contexto, escritura y Git**, manteniendo diffs, approvals, receipts y restricciones de root independientes.
- [ ] **Paso 6: Añadir `test_nested_isyroot_keeps_its_own_identity_and_grants`**, confirmando que el scope anidado no hereda configuración, sesiones ni grants del workspace activo.
- [ ] **Paso 7: Ejecutar suites enfocadas y revisar el journal** para confirmar que el receipt contiene la misma request aprobada.

  Ejecutar: `pytest tests/test_workspace_folders_tui.py tests/test_workspace_write.py tests/test_workspace_write_tui.py tests/test_git_owner.py tests/test_tool_protocol.py -q`

  Esperado: PASS.

- [ ] **Paso 8: Confirmar solo los archivos de esta tarea**.

  Ejecutar: `git add src/isycode/folder_screens.py src/isycode/tui.py src/isycode/file_picker.py src/isycode/action_runtime.py src/isycode/workspace_write.py src/isycode/git_owner.py tests/test_workspace_folders_tui.py tests/test_workspace_write.py tests/test_workspace_write_tui.py tests/test_git_owner.py tests/test_tool_protocol.py && git commit -m "feat: request scoped access from chat and file owners" -- src/isycode/folder_screens.py src/isycode/tui.py src/isycode/file_picker.py src/isycode/action_runtime.py src/isycode/workspace_write.py src/isycode/git_owner.py tests/test_workspace_folders_tui.py tests/test_workspace_write.py tests/test_workspace_write_tui.py tests/test_git_owner.py tests/test_tool_protocol.py`

### Tarea 5: Montajes Bubblewrap para alcances autorizados

**Archivos:**
- Modificar: `src/isycode/command_runner.py`, `src/isycode/tui.py`
- Modificar: `tests/test_command_runner.py`, `tests/test_command_runner_tui.py`

**Interfaces:**
- `CommandPreview` contiene `mounts: tuple[ScopeMount, ...]`, donde `ScopeMount` fija `scope_id`, raíz canónica, identidad y modo `read-only`/`read-write`.
- Produce `ScopeMount(scope_id: str, root: Path, identity: tuple[int, int], writable: bool)` en `command_runner.py`.
- `sandbox_command(...)` recibe las mounts revisadas; la request digest incluye los IDs, identidades y modos.
- `sensitive_entries(root)` se ejecuta para cada raíz antes de revisar y vuelve a ejecutarse antes de lanzar el proceso.

- [ ] **Paso 1: Escribir pruebas fallidas** `test_command_mounts_read_scopes_read_only`, `test_command_mounts_write_scope_only_when_requested`, `test_command_rejects_changed_or_unregistered_mount` y `test_command_masks_sensitive_entries_in_every_scope`. Afirmar `--ro-bind` para lectura, escritura solo con scope writable + request aprobada, y máscaras independientes por raíz.
- [ ] **Paso 2: Ejecutar las pruebas enfocadas del command runner para confirmar fallos**.

  Ejecutar: `pytest tests/test_command_runner.py tests/test_command_runner_tui.py -q`

  Esperado: FAIL en los nuevos casos multi-root.

- [ ] **Paso 3: Extender `CommandPreview` y la request inmutable** para fijar la lista exacta de mounts, permisos e identidades revisadas.
- [ ] **Paso 4: Construir mounts Bubblewrap solo desde scopes resueltos** y aplicar máscaras a cada raíz; denegar sin fallback si un mount no se puede aislar.
- [ ] **Paso 5: Volver a derivar y comparar scopes, programa y máscaras inmediatamente antes de ejecutar**.
- [ ] **Paso 6: Ejecutar suites enfocadas y confirmar que las pruebas previas de red bloqueada, secretos ocultos, approvals y receipts no regresan**.

  Ejecutar: `pytest tests/test_command_runner.py tests/test_command_runner_tui.py -q`

  Esperado: PASS.

- [ ] **Paso 7: Confirmar solo los archivos de esta tarea**.

  Ejecutar: `git add src/isycode/command_runner.py src/isycode/tui.py tests/test_command_runner.py tests/test_command_runner_tui.py && git commit -m "feat: sandbox commands with authorized path scopes" -- src/isycode/command_runner.py src/isycode/tui.py tests/test_command_runner.py tests/test_command_runner_tui.py`

### Tarea 6: Migración no elevadora, revocación visible y documentación

**Archivos:**
- Modificar: `src/isycode/path_scopes.py`, `src/isycode/workspace_folders.py`, `src/isycode/tui.py`
- Modificar: `tests/test_path_scopes.py`, `tests/test_workspace_folders.py`, `tests/test_workspace_folders_tui.py`
- Modificar: `README.md`, `docs/daily-use-readiness.md`

**Interfaces:**
- `WorkspaceScopeRegistry.import_legacy(folder_record) -> FilesystemScope` conserva únicamente capacidades demostradas por el registro histórico.
- La UI de scopes permite `list_scopes()` y `revoke(scope_id)`; no ofrece cambios silenciosos de alcance.

- [ ] **Paso 1: Escribir pruebas fallidas** `test_legacy_readonly_folder_migrates_without_write_or_run`, `test_legacy_editable_folder_migrates_only_existing_actions` y `test_corrupt_legacy_folder_does_not_migrate`. Afirmar que la migración conserva exactamente las capacidades legibles del registro y nunca inventa run/write.
- [ ] **Paso 2: Implementar importación idempotente** que mantenga los registros legacy hasta confirmar la carga del nuevo scope y no elimine archivos durante migración.
- [ ] **Paso 3: Escribir `test_scope_settings_lists_and_revokes_grants`**, incluyendo una acción en espera que queda denegada al revocar.
- [ ] **Paso 4: Implementar UI para inspeccionar y revocar scopes recordados** y distinguir descubierto, pendiente, concedido, revocado y bloqueo del anfitrión.
- [ ] **Paso 5: Actualizar README y guía diaria en español** para describir `.isyroot` semántico, descubrimiento superficial, consentimiento por equipo, capacidades independientes y límites del filesystem remoto.
- [ ] **Paso 6: Ejecutar las suites enfocadas y revisar que la migración no crea archivos en carpetas externas ni eleva grants**.

  Ejecutar: `pytest tests/test_path_scopes.py tests/test_workspace_folders.py tests/test_workspace_folders_tui.py -q`

  Esperado: PASS.

- [ ] **Paso 7: Confirmar solo los archivos de esta tarea**.

  Ejecutar: `git add src/isycode/path_scopes.py src/isycode/workspace_folders.py src/isycode/tui.py tests/test_path_scopes.py tests/test_workspace_folders.py tests/test_workspace_folders_tui.py README.md docs/daily-use-readiness.md && git commit -m "feat: migrate local folder scopes and document permissions" -- src/isycode/path_scopes.py src/isycode/workspace_folders.py src/isycode/tui.py tests/test_path_scopes.py tests/test_workspace_folders.py tests/test_workspace_folders_tui.py README.md docs/daily-use-readiness.md`

### Tarea 7: Verificación transversal y auditoría de cobertura

**Archivos:**
- Modificar si hace falta: `src/isycode/action_coverage.py`, `docs/security/m15-authority-coverage.json`
- Test: `tests/test_action_coverage.py`
- Revisar: todos los archivos y pruebas anteriores.

- [ ] **Paso 1: Ejecutar las suites del área filesystem/security**.

  Ejecutar: `pytest tests/test_path_scopes.py tests/test_path_discovery.py tests/test_workspace_authority.py tests/test_security_contract.py tests/test_workspace_root.py tests/test_workspace_folders.py tests/test_workspace_folders_tui.py tests/test_file_picker.py tests/test_workspace_write.py tests/test_workspace_write_tui.py tests/test_git_owner.py tests/test_tool_protocol.py tests/test_action_coverage.py tests/test_command_runner.py tests/test_command_runner_tui.py -q`

  Esperado: PASS.

- [ ] **Paso 2: Regenerar el inventario de cobertura de acciones** y revisar los cambios exactos.

  Ejecutar: `PYTHONPATH=src python3 -c 'import json; from isycode.action_coverage import authority_coverage_snapshot; print(json.dumps(authority_coverage_snapshot(), indent=2, sort_keys=True))' > docs/security/m15-authority-coverage.json`

  Esperado: el JSON se regenera desde el catálogo/owners actuales y `tests/test_action_coverage.py::test_checked_in_snapshot_matches_live_catalog_and_owners` confirma igualdad.
- [ ] **Paso 3: Inspeccionar `git diff --check`, `git status --short` y todo el diff de implementación**; confirmar que solo se alteraron alcances solicitados y que no hay grants elevadas.
- [ ] **Paso 4: Ejecutar la suite completa del repositorio si el usuario aprueba verificación integral**; reportar por separado cualquier fallo preexistente.
- [ ] **Paso 5: Preparar un resumen de resultados PASS/FAIL y límites demostrados**; no afirmar que se probó otra máquina o un filesystem remoto.

## Orden y dependencias

Tarea 1 define el registro. Tarea 2 integra la autoridad. Tarea 3 ofrece descubrimiento/selección sin permiso implícito. Tarea 4 conecta consentimiento y owners. Tarea 5 amplía el sandbox. Tarea 6 migra permisos históricos y documenta. Tarea 7 verifica contratos de extremo a extremo. No paralelizar tareas que cambien conjuntamente `WorkspaceAuthority`, `action_runtime.py` o `tui.py`.

## Puntos de decisión para revisión

- La compatibilidad con los registros legacy debe preservar permisos previos sin elevarlos; esta versión no los borra automáticamente.
- El selector nativo puede elegir una ruta visible, pero Sentinel sigue denegando si el sistema anfitrión o IsyMotron no puede acceder a ella.
- Las pruebas de Bubblewrap verifican argv/mount policy con fixtures; la prueba de ejecución real depende de disponibilidad del sandbox Linux y debe declararse por separado.
- Antes de cualquier commit de implementación, comparar el diff contra la base local capturada; los comandos `git add` de cada tarea solo se ejecutan cuando el stage contiene exclusivamente cambios de esa tarea.
