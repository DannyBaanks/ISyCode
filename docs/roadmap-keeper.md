# Roadmap: modelo mantenedor de ISyCode («Keeper»)

Fecha: 2026-10-23. Estado: **propuesta; ningún hito empezado, ninguna puerta aprobada.**
Este documento define el destino y sus puertas; publicarlo no implementa nada ni supera ninguna puerta.
«Keeper» es un nombre de trabajo (decisión D4). Los IDs `MK0`–`MK6` y `GK-*` son locales a este roadmap.

## 1. Objetivo y límites

**Un modelo dedicado a mantener, actualizar y reparar ISyCode**, con un contexto del proyecto ya establecido, al que se le pueda pedir «agrega esto a ISyCode» y lo haga sin romper nada.
Es un rol, como GUS en ISyCo-Worlds, no un nuevo nivel de autoridad.
Tiene su propio proveedor/modelo (o modelo local) y su propia conversación.

Referencia: GUS (`src/main/agents/gus.md` y `worldHelperRoleEngine.ts` en ISyCo-Worlds) declara sus permisos en el frontmatter, el loader se niega a cargar un rol que exceda su política, guarda proveedor/modelo/key aparte y su salida es inerte hasta que una persona la aprueba.
Se toma el patrón, no el código.

| Dimensión | Baseline inspeccionado: `e5ab364` | Objetivo |
| --- | --- | --- |
| Roles | Roles de catálogo (`catalog.py`) enviados como contrato de guía con cada mensaje; no conceden nada | Rol Keeper declarado en un archivo con permisos verificados al cargar |
| Modelo dedicado | Un único slot opcional, `small` (`providers.model_slot`), usado para compactar | Slot `keeper` con proveedor/modelo propios, local incluido |
| Credenciales | API keys por proveedor, no por slot (`load_provider_key`) | Según D2: otro proveedor/local, o key propia del slot |
| Contexto | Compactación en tres capas (ver §2); nada queda fijado | Paquete de contexto fijo que nunca se compacta |
| Cambios | Owners, Sentinel, journal, aprobaciones por modo; Flow silencioso para acciones recuperables | Trabajo en rama, tests en sandbox, rutas protegidas siempre con revisión humana |

No objetivos:

- Que Keeper parchee el proceso de ISyCode en ejecución o recargue código en caliente.
- Que Keeper tenga una autoridad propia: sigue Workspace Authority, IsySentinel, owners, journal y aprobaciones del modo activo.
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
- Keeper es autonomía de Classic/Flow: aplica también [el roadmap de Classic/Security](roadmap-classic-security-ux.md).
- PRs chicos. Si un PR pasa de ~30 archivos, se parte (registro `vicios-tecnicos`, vicio global #1).
- El cuerpo de `TUIApp` no crece. Ya está en 88 métodos, por encima de su contrato de 80; lo nuevo va a mixins o módulos propios.
- Estado nuevo va por `StateIndex`; menú nuevo entra al enum `MenuAction`; cada texto visible tiene entradas en/es/zh.
- La implementación no es una aprobación de puerta. Evidencia en `docs/evidence/keeper/<hito>/<sha>/`.

## 4. Decisiones del owner (antes de MK1)

| ID | Pregunta | Opciones |
| --- | --- | --- |
| D1 | Alcance | (a) solo propone parches, inertes hasta aprobarlos, como GUS; (b) edita y corre tests sin preguntar dentro de una rama, como Flow |
| D2 | Credencial | (a) otro proveedor o modelo local con la key por proveedor actual; (b) key propia del slot, aunque sea del mismo proveedor (toca credenciales: ADR 0006 y M5) |
| D3 | Workspace | (a) solo el repo de ISyCode; (b) cualquier workspace |
| D4 | Nombre | Keeper u otro |

## 5. Hitos

### MK0 — Decisiones y baseline

Trabajo: registrar D1–D4 en un ADR (`docs/decisions/0011-keeper.md`).
Medir: tamaño en tokens del paquete de contexto candidato, presupuesto que deja a cada modelo objetivo, métodos de `TUIApp` y suite actual.
Dependencias: ninguna.

- `GK0-01`: ADR aceptado por Danny con D1–D4.
- `GK0-02`: medición del paquete de contexto contra las ventanas de los modelos elegidos; si no cabe en el más chico, se recorta antes de MK3.

### MK1 — Rol declarativo con permisos verificados

Trabajo: `src/isycode/agents/keeper.md` con frontmatter (`id`, `name`, permisos) y cuerpo con el contrato.
Un loader que rechaza el rol si declara más que la política aprobada en D1 (como `resolveGusRole`).
Los permisos son un subconjunto de Systembilities existentes, nunca acciones nuevas.
Dependencias: MK0.

- `GK1-01`: un rol que pida push, credenciales, autoridad o modo no carga y la TUI lo dice.
- `GK1-02`: el contrato de rol no concede grants: con el rol activo, Sentinel decide exactamente igual que sin él.

### MK2 — Slot de modelo `keeper`

Trabajo: extender `model_slot`/`save_model_slot` con `keeper` y agregar su selector en Configuración.
Admite proveedor y modelo local. Si D2 = (b), la key del slot vive en el owner de credenciales, nunca en preferencias ni logs.
Dependencias: MK1; si D2 = (b), también M5 del roadmap de Classic/Security.

- `GK2-01`: con el slot vacío, Keeper no arranca y explica por qué; no cae al modelo del chat sin avisar.
- `GK2-02`: la key del slot nunca aparece en preferencias, transcripciones, journal ni capturas.

### MK3 — Contexto fijo y compactación

Trabajo: un paquete de contexto (AGENTS.md, catálogo de skills de diseño, índice de ADRs, mapa del registro) leído por un owner de lectura con recibo y digest.
Se envía en cada turno como el contrato de rol y se descuenta del presupuesto de historial antes de compactar.
La compactación y la cápsula solo tocan la conversación. Si un archivo del paquete cambia, se relee por su digest.
Dependencias: MK2.

- `GK3-01`: tras forzar compactación automática y `/compact`, el paquete sigue completo en la petición.
- `GK3-02`: con el paquete puesto, ninguna petición excede la ventana del modelo en la matriz de modelos de MK0.
- `GK3-03`: texto inyectado dentro de esos archivos se trata como datos y no cambia permisos.

### MK4 — Superficie en la TUI

Trabajo: entrada a Keeper desde la TUI (comando y rol), con su propia conversación guardada aparte como la de GUS y su color de rol.
No se crea un sistema de lanes nuevo.
Diseño según `.agents/skills/isycode-design`.
Dependencias: MK3.

- `GK4-01`: abrir, conversar, cerrar y retomar Keeper sin mezclar su transcripción con la del chat.
- `GK4-02`: en/es/zh a 80×24, 100×30 y 140×40.

### MK5 — Flujo de cambio seguro

Trabajo: Keeper trabaja en una rama propia y entrega diff, resultado de tests en sandbox y resumen.
Hay una lista de rutas protegidas (`security.py`, `workspace_authority.py`, owners, `action_audit.py`, approvals, pantallas de aprobación, `docs/decisions`) que siempre pide revisión humana, también en Flow.
Nunca push sin aprobación, nunca recarga en caliente.
Dependencias: MK4 y D1.

- `GK5-01`: un cambio en una ruta protegida nunca se aplica en silencio, en ningún modo.
- `GK5-02`: un cambio que rompe la suite no se ofrece como listo; se reporta con la salida real.
- `GK5-03`: deshacer el trabajo de Keeper con `/undo` o descartar su rama deja el repo como estaba.

### MK6 — Matriz adversarial y dogfood

Trabajo: inyección en archivos del repo, intento de tocar rutas protegidas, de leer credenciales y de salirse del workspace; agotamiento de presupuesto; cambio de modo durante un turno.
Dogfood: cambios reales a ISyCode hechos con Keeper y revisados por Danny.
Dependencias: MK5.

- `GK6-01`: toda la matriz deniega o pregunta; ningún caso concede.
- `GK6-02`: al menos 5 cambios reales de dogfood con su evidencia y sin regresiones.

## 6. Siguiente paso

Que Danny responda D1–D4. Con eso se escribe el ADR de MK0 y se mide el paquete de contexto.
