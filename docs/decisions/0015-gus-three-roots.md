# ADR 0015: GUS en cualquier workspace — tres raíces, lectura de máquina y memoria de usuario

- **Estado:** aceptado. Excepción al freeze del [ADR 0014](0014-freeze.md) aprobada por Danny el 2026-10-24 junto con el plan de implementación; el cambio L0 lo revisó y aprobó esa misma aprobación (ADR 0013).
- **Fecha:** 2026-10-24
- **SHA de partida:** `main` en `b2bd4bf`; implementado en la rama local `gus-three-roots` (`2b6cf5a`, `5104b81`, `b2645d7`).
- **Referencia:** [ADR 0011](0011-gus-maintainer.md) (GUS mantenedor), [ADR 0012](0012-gus-context.md) (contexto fijo), [ADR 0013](0013-gus-l1-l0.md) (L1/L0 y activación por merge).

## Contexto

Hasta este ADR, GUS vivía encerrado en el checkout: el botón de la TUI solo
aparecía cuando el workspace visible era un checkout de ISyCode
(`is_isycode_checkout`), `/gus` se negaba en cualquier otra carpeta y todo el
runtime (journal, huella L0, autoridad, rama) usaba la raíz visible. Abrir
ISyCode en `~/Development/ISyCo` hacía desaparecer el botón.

Danny pidió:

1. GUS disponible en cualquier workspace o worktree, con o sin sandbox ya
   establecido, junto al chip de modo/Flow y con su propia ventana de chat.
2. Lectura de todos los archivos de la computadora **menos credenciales**.
3. Edición solo del checkout ISyCode configurado, en una rama `gus/*` y nunca
   de L0.
4. Memoria de usuario estilo ChatGPT, entre workspaces, con modo explícito o
   automático y UI para verla y borrarla.

El freeze del ADR 0014 prohíbe features nuevas; Danny aprobó una excepción
explícita para esta feature el 2026-10-24. El resto del freeze sigue vigente.

## Decisión

### 1. Tres raíces, nunca confundidas

| Raíz | Uso de GUS | Permiso |
|---|---|---|
| visible (`visible`) | workspace donde se abrió la TUI | lectura; escritura **solo** si además es el target |
| target (`target`) | checkout ISyCode configurado | edición, comandos y git, solo L1 y solo en `gus/*`, con sandbox |
| máquina (`read_scope`) | `/`, `$HOME` o carpetas elegidas | lectura, lista, búsqueda y grep; solo lectura |
| estado de usuario (`<state>/gus`) | conversación, memoria y settings | privado, fuera del machine scope |

`GusRoots` (`gus_roots.py`) reúne las raíces de una sesión. El target por
defecto es el checkout que ejecuta la app (`running_checkout()`); si no hay
ninguno, GUS conversa y lee pero no edita hasta que Settings fije uno
validado con `validate_target`.

El target tiene su propia autoridad, `GusTargetAuthority` (marcador
`gus_target = True`), creada únicamente por el consentimiento de GUS y escrita
con grants explícitos y auditables: `mode="security"`, las acciones de
`QUIET_FLOW_ACTIONS` con `path_prefixes=[target]`, `workspace.command.run`
con `executables=[sandbox]` solo si el sandbox existe, y
`git.status`/`git.diff`/`git.commit`/`git.branch.create`. No incluye sesiones,
memoria de workspace, credenciales ni push. `quiet_gus` acepta el marcador
`gus_target` sin relajar los checks para una `WorkspaceAuthority` en Security.

Las llamadas al modelo usan una autoridad distinta, `provider_authority()`,
enraizada en el estado de usuario, con un único grant `provider.request` para
los hosts de proveedor conocidos. Así GUS conversa incluso en un workspace en
Security y sin target; el target solo concede edición.

### 2. Vista de máquina: leer todo menos credenciales

`machine_view.py` define cuatro acciones de solo lectura —
`machine.files.list`, `machine.files.read`, `machine.files.search` y
`machine.files.grep`— con efecto `read` y `approval_required=False`. Pasan por
`ProductActionGate` con `MachineReadBoundary` como Systembility adicional, de
modo que también las cubre IsySentinel, el journal y los receipts.

- El path debe ser absoluto y canónico (`resolve(strict=True)`); debe quedar
  bajo un root permitido. El target y el workspace visible son roots
  implícitos; el scope elegido se suma.
- El chequeo de nombres sensibles es relativo al root contenedor más
  específico, para que `.isycode` como componente del checkout instalado no
  bloquee sus propios archivos.
- Se rechazan symlinks y hardlinks que salgan del root, devices, FIFOs,
  sockets, binarios (NUL), archivos de más de 256 KiB y directorios en `read`.
- La denylist cubre `/proc`, `/sys`, `/dev`, `/run`, `/root`, `/boot`,
  `/lost+found`, `/var/lib`, `/var/run`, `/var/cache`, `/etc/shadow`,
  `/etc/gshadow`, `/etc/sudoers*`, `/etc/ssl/private`, `/etc/pki/private`,
  `/etc/ssh`, el state root de ISyCode, los homes de otros usuarios bajo
  `/home/*` cuando el scope es `/`, y nombres de credenciales, perfiles de
  navegador, keyrings, historiales de shell y configuraciones de nube/registro
  ya listados en `sensitive_paths.py`.
- Presupuestos: 256 KiB por archivo, 2 MiB y 64 archivos por turno, 200
  entradas por lista, 200 coincidencias por grep, 20k entradas de búsqueda y
  profundidad 6. El presupuesto por turno se reinicia al comenzar el turno.

### 3. Memoria de usuario y conversación compartida

`gus_memory.py` mueve el estado conversacional fuera del checkout:

- `GusConversation` guarda `<state>/gus/conversation.json` con entradas
  `{role, text, at, workspace}` (80 entradas / 32k caracteres). Es compartida
  entre workspaces; no se migra el transcript viejo por workspace.
- `GusMemoryStore` guarda `<state>/gus/memories.json`, privado (0600), acotado
  (500 entradas / 256 KiB), con `add`, `update`, `delete`, `clear`, `list` y
  `texts`.
- `redact_memory` reutiliza `sanitize_historical_text` y añade bloques PEM,
  tokens (`sk-…`, `ghp_…`, `AKIA…`) y JWT. Si tras redactar no queda contenido
  útil, la escritura se rechaza.
- Modos: `explicit` (por defecto) exige una aprobación de un solo uso por cada
  recuerdo; `automatic` usa el consentimiento del modo. Borrar y vaciar
  siempre exigen aprobación humana y no son herramientas del modelo.
- El modelo solo recibe `memory_remember`. La memoria se inyecta como un
  bloque de **datos** no confiables, después del rol y antes del pack, con tope
  de 8k caracteres; nunca cambia el rol, la política ni una aprobación.
- Toda escritura o borrado pasa por `ProductActionGate` con
  `GusMemoryBoundary`, `GusMemoryAuthority`, journal y receipt.

### 4. SEAM

El roster fijo de SEAM crece de 13 a 16 casos: aislamiento de target
(escritura al workspace visible denegada), replay de una aprobación de memoria
entre dos state roots y envenenamiento de memoria (la instrucción recordada
sigue siendo un bloque de datos y no toca rol, techo ni pack). Los 16 casos
terminan en `DENY`.

## Archivos L0 de esta decisión

Modificados: `gus_l0.py`, `gus_role.py`, `gus_session.py`,
`gus_context_pack.py`, `gus_seam.py`, `workspace_trust.py`, `action_runtime.py`,
`actions.py`, `git_owner.py`, `tui_screens_gus.py`, `tui_app_gus.py`,
`agents/gus.md` y `tests/test_gus_seam.py`. Nuevos: `gus_roots.py`,
`gus_dispatch.py`, `machine_view.py`, `gus_memory.py`,
`tui_screens_gus_settings.py` y sus pruebas (`test_gus_roots.py`,
`test_gus_dispatch.py`, `test_machine_view.py`, `test_gus_memory.py`).

`L0_FILES` incluye todos ellos; el cambio de manifiesto es intencional y su pin
nuevo es
`659f57bb201161f2ef4e1427a8c3eb0cbce17ece914e1a7f50e27161fde12181`.
El snapshot `docs/security/m15-authority-coverage.json` se regeneró con
`authority_coverage_snapshot()` (92 acciones, `secure_closed`, `secure_tui_closed`
y `authority_frontier_pass` en verdadero).

## Verificación registrada (2026-10-24)

- Suite enfocada: 165 pruebas en verde (`test_gus_roots`, `test_gus_dispatch`,
  `test_machine_view`, `test_gus_memory`, `test_gus_session`, `test_gus_work`,
  `test_gus_seam`, `test_gus_l0`, `test_localization`,
  `test_localization_coverage`, `test_action_coverage`, `test_tui_protocols`,
  `test_secure_tui_surfaces`).
- Roster SEAM ejecutado a mano (`python -m isycode.gus_seam`): 16/16 `DENY`,
  exit 0; roster
  `e1cb998c3b3a08168e4e3451c1e5ecc76320a5eb003ea7723f1eac416322d60c`.
- Las cadenas nuevas de la UI están en los catálogos en/es/zh y
  `test_localization_coverage.py` pasa.

## Riesgos residuales

- **Secretos semánticos:** la frontera de máquina es por nombre y prefijo. Un
  secreto dentro de un archivo con nombre inocente no se detecta:
  `NOT_DEMONSTRATED`. Mitigación: consentimiento, redacción en memoria y el rol
  que trata lo leído como datos.
- **Inyección de prompt desde archivos leídos:** el rol y el contexto declaran
  que el contenido es dato, pero una obediencia del modelo no es demostrable
  al 100%: `NOT_DEMONSTRATED`.
- **Proveedor:** todo lo que GUS lee puede enviarse a su modelo; está en el
  consentimiento y en el bloque de raíces del pack.
- **TOCTOU:** entre canonicalizar y abrir se mitiga con `O_NOFOLLOW` + `fstat`
  + comparación de `st_dev`/`st_ino`, como ya hace `WorkspaceAuthority.policy()`;
  la ventana residual no se elimina por completo.
- **Windows:** "toda la computadora" no se ofrece; Home y carpetas elegidas sí.
- **`/` como scope** es amplio por diseño; Settings permite Home o carpetas.
- **Memoria:** las notas son texto redactado, no una verdad verificada; el
  bloque de memoria es no confiable y el modelo no puede borrar nada.

## Consecuencias

- GUS deja de depender del checkout donde se abrió la TUI, pero la edición
  sigue confinada a un checkout ISyCode limpio, en `gus/*` y fuera de L0.
- El chat normal conserva sus modos y permisos: esta decisión no ensancha
  ninguna herramienta fuera de GUS.
- Activar el trabajo de GUS sigue siendo el merge de Danny (ADR 0013, L2). No
  hay push automático.
- El freeze sigue vigente para todo lo demás; esta excepción no se repite sin
  una aprobación nueva de Danny.
