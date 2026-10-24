# Roadmap: GUS, el modelo mantenedor de ISyCode

Fecha: 2026-10-23. Estado: **[ADR 0011](decisions/0011-gus-maintainer.md) aceptado (D1–D4); MK1 en curso; ninguna puerta aprobada.**
Este documento define el destino y sus puertas; publicarlo no implementa nada ni supera ninguna puerta.
Los IDs `MK0`–`MK6` y `GK-*` son locales a este roadmap. GUS de ISyCode y GUS de ISyCo-Worlds comparten nombre (D4), no código ni estado.

## 1. Objetivo y límites

**Un modelo dedicado a mantener, actualizar y reparar ISyCode**, con un contexto del proyecto ya establecido, al que se le pueda pedir «agrega esto a ISyCode» y lo haga sin romper nada.
Es un rol, como GUS en ISyCo-Worlds, no un nuevo nivel de autoridad. Solo trabaja en el repo de ISyCode (D3).
Tiene su propio proveedor/modelo (o modelo local) y su propia conversación.

Referencia: GUS (`src/main/agents/gus.md` y `worldHelperRoleEngine.ts` en ISyCo-Worlds) declara sus permisos en el frontmatter, el loader se niega a cargar un rol que exceda su política, guarda proveedor/modelo/key aparte y su salida es inerte hasta que una persona la aprueba.
Se toma el patrón, no el código.

| Dimensión | Baseline inspeccionado: `e5ab364` | Objetivo |
| --- | --- | --- |
| Roles | Roles de catálogo (`catalog.py`) enviados como contrato de guía con cada mensaje; no conceden nada | Rol GUS declarado en un archivo con permisos verificados al cargar |
| Modelo dedicado | Un único slot opcional, `small` (`providers.model_slot`), usado para compactar | Slot `gus` con proveedor/modelo propios, local incluido, ventana ≥32k |
| Credenciales | API keys por proveedor, no por slot (`load_provider_key`) | Sin cambios (D2): otro proveedor o modelo local |
| Contexto | Compactación en tres capas (ver §2); nada queda fijado | Paquete de contexto fijo que nunca se compacta |
| Cambios | Owners, Sentinel, journal, aprobaciones por modo; Flow silencioso para acciones recuperables; Git sin acción de rama | Edita solo en ramas `gus/*` (D1), tests en sandbox, L0 fuera de su alcance (ADR 0013) |

No objetivos:

- Que GUS parchee el proceso de ISyCode en ejecución o recargue código en caliente.
- Que GUS tenga una autoridad propia: sigue Workspace Authority, IsySentinel, owners, journal y aprobaciones del modo activo.
- Hacer push, publicar, tocar credenciales, cambiar la autoridad o el modo por su cuenta.
- Requerir IsyMotron, el Bridge o el Gateway.
- Reescribir el sistema de lanes/steering (P1 del registro `vicios-tecnicos`; decisión aparte).

## 2. Lo que ya existe y hay que reutilizar

**Compactación (ADR 0009).**

1. *Dentro de un turno:* `agent_loop.compact_turn` reemplaza los resultados de herramientas más viejos por un texto corto cuando el turno supera 160k caracteres. Conserva los 4 más nuevos y los ids de llamada.
2. *Entre turnos, automática:* `TUIApp._plan_turn_context` reparte la mitad de la ventana del modelo al historial (≈3 caracteres por token, mínimo 24k caracteres).
   - Lo que no cabe se resume con el slot `small`, solo si es del proveedor del chat.
   - Si no hay resumen, entra la cápsula de continuidad (`continuity_capsule.py`): determinista, sin tokens, como máximo el 25% del presupuesto.
3. *Manual:* `/compact [instrucciones]` resume todo menos el último intercambio con el slot `small`.

Resumen y cápsula son contexto, nunca autoridad. La conversación guardada conserva siempre la transcripción completa.

| Área | Código existente | Pruebas a extender |
| --- | --- | --- |
| Roles y contrato de rol | `catalog.py`, `tui_app_chat.py` (contrato de rol por mensaje) | `test_role_cycle.py`, `test_conversation_agents.py` |
| Slots de modelo | `providers.py` (`model_slot`, `save_model_slot`) | pruebas de providers/slots |
| Compactación y cápsula | `agent_loop.py`, `continuity_capsule.py`, `tui_app_chat.py` | `test_agent_loop.py`, pruebas de la cápsula |
| Lectura con recibo | `LocalWorkspaceReadOwner`, `WorkspaceConfigOwner` | pruebas de owners de lectura |
| Cambios recuperables | owners de escritura, `TurnJournal`, Flow (ADR 0010) | `test_flow_mode.py`, `test_turn_undo.py` |
| Credenciales | `credential_owner.py`, `credentials.py` (ADR 0006) | `test_credential_owner.py` |

## 3. Reglas de avance

- No se avanza un hito con puertas pendientes, fallidas o reabiertas de sus dependencias.
- GUS es autonomía de Classic/Flow: aplica también [el roadmap de Classic/Security](roadmap-classic-security-ux.md).
- PRs chicos. Si un PR pasa de ~30 archivos, se parte (registro `vicios-tecnicos`, vicio global #1).
- El cuerpo de `TUIApp` no crece. Ya está en 88 métodos, por encima de su contrato de 80; lo nuevo va a mixins o módulos propios.
- Estado nuevo va por `StateIndex`; menú nuevo entra al enum `MenuAction`; cada texto visible tiene entradas en/es/zh.
- La implementación no es una aprobación de puerta. Evidencia en `docs/evidence/gus/<hito>/<sha>/`.

## 4. Decisiones del owner (resueltas el 2026-10-23)

| ID | Pregunta | Decisión |
| --- | --- | --- |
| D1 | Alcance | Edita y corre tests en el sandbox sin preguntar, solo dentro de una rama `gus/*`; L0 queda fuera de su alcance (ADR 0013) |
| D2 | Credencial | Otro proveedor o modelo local, con las keys por proveedor existentes; sin key por slot |
| D3 | Workspace | Solo el repo de ISyCode |
| D4 | Nombre | GUS |

## 5. Hitos

### MK0 — Decisiones y baseline

Trabajo: registrar D1–D4 en [ADR 0011](decisions/0011-gus-maintainer.md).
Medir: tamaño en tokens del paquete de contexto candidato, presupuesto que deja a cada modelo objetivo, métodos de `TUIApp` y suite actual.
Dependencias: ninguna.

- `GK0-01`: ADR aceptado por Danny con D1–D4.
- `GK0-02`: medición del paquete de contexto contra las ventanas de los modelos elegidos; si no cabe en el más chico, se recorta antes de MK3.

### MK1 — Rol declarativo con permisos verificados

Trabajo: `src/isycode/agents/gus.md` con frontmatter (`id`, `name`, permisos) y cuerpo con el contrato.
Un loader que rechaza el rol si declara más que la política aprobada en D1 (como `resolveGusRole`).
Los permisos son un subconjunto de Systembilities existentes, nunca acciones nuevas.
Dependencias: MK0.

- `GK1-01`: un rol que pida push, credenciales, autoridad o modo no carga y la TUI lo dice (el loader está en `gus_role.py`; mostrar el error en la TUI llega con MK4).
- `GK1-02`: el contrato de rol no concede grants: con el rol activo, Sentinel decide exactamente igual que sin él.

### MK2 — Slot de modelo `gus`

Trabajo: extender `model_slot`/`save_model_slot` con `gus` y agregar su selector en Configuración.
Admite proveedor y modelo local, con las keys por proveedor existentes (D2). Rechaza un modelo con ventana conocida menor de 32 000 tokens (ADR 0011) y uno que el catálogo marca sin tool calls, porque GUS no podría editar. Solo se ofrece en el repo de ISyCode (D3).
Dependencias: MK1.

- `GK2-01`: con el slot vacío, GUS no arranca y explica por qué; no cae al modelo del chat sin avisar.
- `GK2-02`: un modelo con ventana conocida menor de 32k no se puede asignar al slot y la TUI dice por qué.

### MK3 — Contexto fijo y compactación

Trabajo: un paquete de contexto (AGENTS.md, `SKILL.md` de diseño, estándar visual e índice de ADRs; el registro privado no entra, D3) leído por un owner de lectura con recibo y digest.
Se envía en cada turno como el contrato de rol y se descuenta del presupuesto de historial antes de compactar.
La compactación y la cápsula solo tocan la conversación. Si un archivo del paquete cambia, se relee por su digest.
Dependencias: MK2.

Implementación: `gus_context_pack.py`. `ContextPackReader` lee cada archivo con `workspace.files.read` (recibo en el journal) y lo relee solo si cambian su tamaño o su fecha. Lista `docs/decisions` por nombre y lee cada ADR para sacar su título. `plan_gus_request` arma el rol y el paquete enteros y pasa solo el historial por `plan_context`. Medido en `claude/gus-mk3-context`: 16 172 caracteres (≈4.0k–5.4k tokens) en 14 archivos; con una ventana de 32k quedan 31 828 caracteres de historial.

- `GK3-01`: tras forzar compactación automática y `/compact`, el paquete sigue completo en la petición.
- `GK3-02`: con el paquete puesto, ninguna petición excede la ventana del modelo en la matriz de modelos de MK0. `plan_context` mantiene cada pregunta con su respuesta y puede pasarse de su presupuesto por un mensaje (ADR 0009); ese margen queda dentro de la ventana. Un solo mensaje más grande que la ventana es un caso del ADR 0009, no de este hito.
- `GK3-03`: texto inyectado dentro de esos archivos se trata como datos y no cambia permisos.

### MK4 — Superficie en la TUI

Trabajo: entrada a GUS desde la TUI, visible solo en el repo de ISyCode (D3), (comando y rol), con su propia conversación guardada aparte como la de GUS y su color de rol.
No se crea un sistema de lanes nuevo.
Diseño según `.agents/skills/isycode-design`.
Dependencias: MK3.

Implementación:
- `gus_session.py`: habilitación por workspace (`GusState`, registros privados ligados a la ruta resuelta), transcripción propia con tope de 80 entradas y `gus_reply`.
  - `gus_reply` revisa el checkout, la habilitación, el rol, el slot y el paquete, y arma la petición con `plan_gus_request`.
  - La manda por `ProviderNetworkOwner` (autorización y recibo).
  - Si la petición planeada no deja un 25 % de la ventana para la respuesta, no la manda; así se cubre un mensaje más grande que la ventana.
  - En este hito GUS no tiene herramientas: lee su contexto fijo y responde. Las ediciones llegan en MK5.
- `tui_screens_gus.py` (ventana) y `tui_app_gus.py` (`/gus`, «GUS en este workspace» y «Hablar con GUS» en Configuración). GUS usa el color del rol `maintainer`.

- `GK4-00`: GUS se habilita por workspace solo con una confirmación explícita de la persona, guardada por la identidad de ese workspace en `StateIndex`. `is_isycode_checkout` (dos marcadores) solo decide si se ofrece la entrada en Configuración; nunca habilita GUS. Otro proyecto que copie esos archivos ve la entrada, pero GUS no actúa hasta que la persona lo habilite ahí.
- `GK4-03`: las peticiones de GUS se presupuestan con `gus_slot.planning_window`: la ventana conocida o, si es desconocida, 32 000 tokens. Ninguna petición supera esa ventana.
- `GK4-01`: abrir, conversar, cerrar y retomar GUS sin mezclar su transcripción con la del chat.
- `GK4-02`: en/es/zh a 80×24, 100×30 y 140×40.

### MK5 — Flujo de cambio seguro (L1/L0, [ADR 0013](decisions/0013-gus-l1-l0.md))

Trabajo: GUS trabaja en L1 y conoce L0. L0 no pide revisión: queda fuera del alcance de GUS (decisión L1). Un cambio de GUS es una generación en una rama `gus/<tema>` que activa el merge de Danny (decisión L2). Nunca push, nunca recarga en caliente.
Dependencias: MK4, D1 y ADR 0013. Se entrega en cuatro PRs apilados:

- **MK5a — manifiesto y huella de L0.** `gus_l0.py` lista L0 de forma explícita (`L0_FILES`, `L0_DIRECTORIES`) y `touches_l0` también marca las carpetas que contienen L0: mover o borrar `src/isycode` toca L0. La huella es un SHA-256 por archivo, con CRLF normalizado para que sea igual en todas las plataformas. Un archivo cambiado por un enlace cuenta como cambio. El paquete de contexto incluye el manifiesto, la regla y la huella: medido en 19 287 caracteres con 15 archivos.
- **MK5b — rama `gus/*`.** La acción `git.branch.create` del owner de Git crea `gus/<tema>` en el commit actual y cambia a ella con `git switch -c`, sin tocar el árbol de trabajo ni correr hooks. Es la única rama que ISyCode crea. GitBoundary rechaza otro nombre y exige el commit revisado; si HEAD se movió o la rama ya existe, no se crea. Siempre pide aprobación (`GusBranchApprovalScreen`, con Rechazar por defecto), también en Flow. Classic y Flow la conceden; Security no. Se abre con `/gus branch <tema>`.
- **MK5c-1 — la frontera del turno.** `gus_turn(root)` marca el trabajo de un turno de GUS con un ContextVar que heredan las tareas e hilos que nacen dentro. Mientras está puesto para ese workspace:
  - `GusL0Boundary` (en IsySentinel, para todo owner) rechaza cualquier acción fuera del rol de GUS y cualquier cambio que nombre una ruta de L0: escritura, restauración, borrado, movimiento (origen o destino) y commit. Leer L0 sigue permitido.
  - La promoción del staging de comandos rechaza el diff entero si toca L0.
  - `quiet_gus` deja que GUS actúe sin preguntar solo con la lista de Flow, en Classic o Flow, sin carpeta amplia, con comandos en sandbox y solo si `.git/HEAD` es una rama `gus/*`. Fuera de esa rama pregunta como siempre.
- **MK5c-2 — turno de GUS con herramientas.** `gus_work` le da a GUS las herramientas de su rol solo en una rama `gus/*`: leer, editar, borrar, mover, comandos en sandbox y git status/diff/commit. Fuera de esa rama GUS conversa sin herramientas (GK5-04). Cada llamada corre dentro de `gus_turn`; las peticiones al modelo no. El turno tiene un tope de 24 pasos y de la ventana, y lo dice cuando se detiene. La TUI (`_run_gus_turn`) registra el turno en un `TurnJournal` en cualquier modo, así que `/undo` lo deshace (GK5-03). Toma la huella de L0 antes y después: si cambió, deshace el turno y nombra lo que no pudo restaurar. Classic concede `workspace.turn.undo` (enmienda al ADR 0010) y pregunta antes de cada deshacer.
- **MK5d — generaciones.** `gus_generation.py` (L0) arma la generación con lo que GUS commiteó en su rama desde el commit donde nació: `/gus branch` guarda ese commit y la huella de L0 en el estado privado. `PREPARADA → VALIDADA → PROBADA → SELLADA`, con salida a `RECHAZADA`:
  - **V:** árbol limpio, algo commiteado, ningún cambio (ni origen de un rename) en L0, el diff completo y la huella de L0 igual a la del inicio de la rama.
  - **T:** las pruebas de los archivos tocados. Un cambio que ninguna prueba cubre no pasa.
  - **A:** las pruebas del auditor de cobertura, de m15 y de L0.
  - **L:** `ruff check` como en CI o, si el sandbox no tiene ruff, una compilación de los archivos cambiados, y lo dice.
  - **S:** SHA-256 del rango, las rutas, el diff y la evidencia de V/T/A/L.

  T, A y L corren con el owner de comandos en el sandbox, dentro de `gus_turn`. Si el Python del sandbox no puede correr las pruebas, quedan `NOT_RUN` y no se sella. La suite completa la corre CI en el PR de la rama: el tope de un comando es 600 s. Se abre con `/gus seal` o con «Correr las puertas» en la ventana de GUS. Activar es el merge de Danny.

Puertas:
- `GK5-00`: el manifiesto está fijado por una prueba (`PINNED_MANIFEST`), cada entrada existe y todo módulo que define un owner (`class …Owner`) está en L0. El manifiesto y su prueba son L0.
- `GK5-01`: ningún turno de GUS escribe, mueve, borra ni promueve una ruta de L0, en ningún modo. La verificación también corre en la promoción del staging de comandos (`command_runner`, junto a `_revoked_effect`), no solo en `workspace.files.write`. Lo comprueba una prueba adversarial con un comando real.
- `GK5-04`: fuera de una rama `gus/*`, GUS no edita.
- `GK5-02`: un cambio que rompe la suite no se ofrece como listo; se reporta con la salida real.
- `GK5-03`: deshacer el trabajo de GUS con `/undo` o descartar su rama deja el repo como estaba.

### MK6 — SEAM de GUS y dogfood

Trabajo: la matriz adversarial es una auditoría con roster fijo y evidencia encadenada (ADR 0013, punto 5): inyección en archivos del repo, intento de tocar L0 (escritura, comando, enlace, movimiento o borrado), de leer credenciales y de salirse del workspace; agotamiento de presupuesto; cambio de modo durante un turno.
Dogfood: cambios reales a ISyCode hechos con GUS y revisados por Danny.
Dependencias: MK5.

- `GK6-01`: toda la matriz deniega o pregunta; ningún caso concede.
- `GK6-02`: al menos 5 cambios reales de dogfood con su evidencia y sin regresiones.

## 6. Siguiente paso

MK0: Danny revisa [ADR 0011](decisions/0011-gus-maintainer.md). La medición del paquete de contexto está en el ADR. Con el ADR aceptado se evalúa `GK0-01`/`GK0-02` y se empieza MK1.
