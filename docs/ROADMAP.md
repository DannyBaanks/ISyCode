# ISyCode — Roadmap de producto y ejecución

**Una TUI de ISyCo con la experiencia visual de Crush, capacidades propias de ISyCo/OpenISy y seguridad deny-by-default de ISySentinel.**

Estado de este documento: **plan de trabajo**, no declaración de que las integraciones ya estén completas. Los estados y la evidencia tienen fecha; para el resumen vigente consulta el [README](../README.md), la [matriz de features](product/tui-feature-matrix.md) y la [guía de readiness](daily-use-readiness.md). Última auditoría de fuentes registrada: 2026-09-27.

**Actualización de arquitectura (2026-09-27):** ISySentinel + Workspace Authority son el modelo de seguridad de producto. Los hitos escritos antes de M15 que dicen “autoridad IsyMotron” describen el adapter legado existente, no el destino de arquitectura; M15 debe retirar esa dependencia de seguridad antes de habilitar acciones con efectos. Para Gateway HTTP se exige además su Sentinel remoto. Ver [contrato de fronteras](design/isysentinel-security-boundaries.md).

**Estrategia de producto (2026-09-28):** primero cerrar **ISyCode Secure**, con capacidades pequeñas, tipadas y deny-by-default. Después abrir una línea **ISyCode Full** para ampliar los permisos que el usuario concede. Full no es una omisión de Sentinel ni una elevación implícita: mantiene Workspace Authority, owners, approvals para efectos sensibles, límites y recibos; agrega adapters/acciones una por una. No se porta ni se copia la implementación de otra CLI.


**Incremento de uso diario (2026-09-30):** implementados recuperación sin replay automático, sesiones con borradores/metadatos portables y gestión mediante owners, contexto AGENTS.md con recibo, diagnóstico local, `/check` explícito y pruebas headless del flujo leer/editar/test/diff. [Evidencia y pendientes](daily-use-readiness.md): esto no cierra todo M16 ni acredita un proveedor real, Gateway, accesibilidad o estabilidad durante horas. El [soak local del 2026-10-01](long-session-soak-2026-10-01.md) pasó 75 ciclos con herramientas reales y dos reinicios en unos 11 minutos, con proveedor simulado; encontró y corrigió una carrera al arrancar comandos cortos.

## 1. Producto que queremos construir

ISyCode es un agente para terminal que se abre en el directorio actual (`cwd`) y trabaja sobre ese proyecto. La interfaz combina:

- **Chat principal** amplio, con streaming, historial, comandos y estados de tarea claros.
- **Panel lateral derecho** inspirado visualmente en Crush: MCPs y skills reales, estado/conteo de herramientas y acceso al explorador del proyecto.
- **Explorador de archivos del proyecto actual**: árbol navegable, búsqueda y vista previa de archivos. El root se captura al iniciar ISyCode; no se convierte silenciosamente en el root global del Gateway.
- **ISySentinel + Workspace Authority** para evaluar acciones deny-by-default bajo la identidad `.isyroot`; el execution owner ejecuta solo después de ALLOW y registra el resultado por separado.
- **Adapters opcionales** para IsyMotron, Gateway, MCP, LSP, Mobile Host, Bridge y L1. Cada servicio conserva su propia frontera y sus credenciales; ninguno sustituye los grants del workspace.
- **Superficies OpenISy/ISyCo** existentes: MCP, skills, Gateway, capacidades/Bridge y, más adelante, L1. Se integran por interfaces existentes; no se reimplementan dentro del renderer.

### Dirección visual

Crush es referencia visual, no una dependencia ni una copia de marca. Queremos una terminal oscura y legible, identidad ASCII compacta, colores con significado, conversación como zona dominante y una columna lateral útil. En terminales anchas, el chat ocupa aproximadamente 70–75% del ancho y la barra lateral el resto, con un ancho objetivo de 32–38 columnas. En terminales angostas, la barra lateral se reduce o se oculta con un comando; el chat conserva el espacio.

La barra lateral tendrá vistas seleccionables **Overview** y **Files**. Overview presenta las conexiones reales de MCP y las skills disponibles; Files presenta el árbol del directorio de lanzamiento y permite abrir una vista previa. Un indicador compacto conserva el número/estado de MCPs y skills al cambiar de vista. No se colocará un panel de diffs en esa columna. Si más adelante hace falta inspeccionar un diff, será una acción explícita en el chat/editor, nunca el contenido por defecto del panel.

Los estados serán datos reales: conectado, desconectado, autenticación requerida, error, cargando o vacío. Ninguna integración aparecerá verde por estar escrita en una lista estática.

### Decisión de arquitectura propuesta

Conservar inicialmente la TUI Python/Textual de ISyCode y su contrato del renderer, integrar OpenISy mediante MCP/configuración de skills y consumir el Gateway por HTTP. ISyCode será dueño de ISySentinel, Workspace Authority y las decisiones de permisos ligadas a `.isyroot`; IsyMotron podrá ser un adapter/runtime opcional, nunca la autoridad de seguridad del producto. Esto evita importar código TypeScript/Bun de OpenISy directamente en Python y permite reemplazar el renderer sin cambiar las decisiones de política.

**Puerta de arquitectura M0:** comparar esta opción con alojar la UI dentro del TUI TypeScript de OpenISy. La opción propuesta se confirma solo si un spike demuestra que podemos leer estados y herramientas MCP, descubrir skills y mantener el contrato de ISySentinel sin duplicar la sesión de OpenISy. Si no, el spike deja un ADR corto con la decisión y el costo antes de que empiece una integración amplia.

## 2. Auditoría de los proyectos y qué reutilizar

| Proyecto y ubicación | Ya existe | Reutilización prevista | Límite que debe respetarse |
|---|---|---|---|
| **ISyCode** — este repositorio | TUI Textual en `src/isycode/tui.py`; streaming en `src/isycode/streaming.py`; cliente HTTP en `src/isycode/gateway_client.py`; plugins; módulos de sesiones/seguridad/Bridge | Punto de partida para el shell de chat, comandos y adapters | El estado actual se describe en [README.md](../README.md) y en la [matriz de features y evidencia](product/tui-feature-matrix.md). |
| **ISySentinel (ISyCode)** | Pendiente de separar Authority, Systembilities, consenso Sentinel, execution owners y recibos | Fuente de verdad de permisos por workspace y veredicto ALLOW/DENY | Sentinel solo combina resultados; no ejecuta, no concede permisos y no altera el request. `.isyroot` solo limita el máximo root. |
| **IsyMotron** — adapter externo configurable | `Provider`, `Planner`, `Executor`, `Host`, `Enforcer`, leases, motores y recibos | Adapter/runtime opcional y referencia para flujos que el usuario active | Sus grants/leases/recibos no se convierten en permiso de ISyCode. No modificar su semántica para completar el modelo de seguridad del producto. |
| **OpenISy** — integración en checkout separado | Fork de OpenCode con TUI, sesiones/proveedores, MCP, skills, permisos y pipeline L1 | Fuente primaria para las capacidades de OpenISy. Preferir MCP y formatos/configuración existentes frente a una segunda implementación | Su runtime L1 es experimental y sujeto a flag. No importar su estado como autoridad de filesystem. |
| **Gateway de ISyCo** — servicio externo | API de archivos/búsqueda, operaciones semánticas y conectores Drive/Email/GitHub; auth con scopes, contención de paths, redacción, límites y audit log | File/search/semantic remoto solo cuando el Gateway esté configurado y su root coincida con el workspace que se muestra | Tiene un único `IESY_ROOT`; no asumir que es igual al `cwd`. Las escrituras requieren scope dedicado. El Gateway documenta que no ofrece delete ni ejecución de comandos. Indisponibilidad no autoriza fallback a shell. |
| **Bridge/capacidades** — protocolo externo | `cap.agent_bridge/handshake.py`, registro de capacidades y coordinación/leases | Integración de coordinación optativa después del flujo single-agent | Es un protocolo separado y nunca es autoridad de filesystem. |
| **IsyVM** — prototipo externo | TUI Textual, sidebar responsive, status bar, comandos, modos y explorador Qt | Referencia de diseño e interacción para sidebar responsive, foco/atajos, file tree y contratos de layout | No reutilizar su `PolicyEngine`/Layer A como seguridad de ISyCode: Layer A es best-effort y Layer B está pendiente. |

### Estado honesto al iniciar este roadmap

- M0-A/M0-B y la TUI mínima tienen evidencia descrita en el roadmap anterior: 5-turn smoke y 20-turn soak; la TUI se había inspeccionado en tmux. Esa evidencia prueba los escenarios anotados, no producción ni integraciones completas.
- ISyCode aún no tiene ISySentinel separado y conectado en todas las rutas de ejecución; existe un prototipo monolítico y algunos adapters acoplados a IsyMotron. No anunciar el nuevo modelo como operativo hasta migrar esos callsites.
- OpenISy ya ofrece MCP/skills y un TUI propio; el panel actual de ISyCode no lee el estado real de esos servicios.
- El file tree de IsyVM sirve como referencia, pero no es un browser de terminal listo para importar.
- No se verificó visualmente la TUI de ISyCode durante esta revisión, no se ejecutaron pruebas y no se revisaron como limpias las modificaciones locales de OpenISy/IsyVM.
- Los checks de `tests/test_safety.py` no bastan por sí solos para declarar seguridad completa: cada claim debe corresponder a evidencia reproducible y a la ruta efectiva del TUI.

## 3. Contratos y límites entre componentes

```text
Textual UI (chat, Overview, Files, approvals, receipts)
                 │ renderiza y envía intención
                 ▼
ISyCode Runtime Contract (sesión, catálogo, tarea, resultado)
       ┌─────────┼────────────┬─────────────┐
       ▼         ▼            ▼             ▼
  ISySentinel     OpenISy MCP   Skills    Gateway HTTP Sentinel
  Authority       discovery     catalog   remote key/op gate
  Systembilities  LSP / Docker  Bridge    Mobile Host / L1
  execution owners per adapter; outcomes/receipts are separate
```

Reglas de frontera:

1. La TUI renderiza estados y solicita acciones; no resuelve paths físicos para conceder autoridad ni implementa política.
2. El modelo propone intención y parámetros. El catálogo enviado al modelo contiene solo capacidades concedidas.
3. Workspace Authority evalúa grants explícitos ligados al `.isyroot`; ISySentinel agrega todas las Systembilities y devuelve ALLOW/DENY. Un plan del modelo nunca es autorización.
4. El explorador empieza en `workspace_root`, pero solo enumera y lee paths cubiertos por grants explícitos. `.isyroot` nunca habilita lectura. `..`, paths fuera del root y enlaces que escapen se rechazan.
5. MCP/skills se descubren y presentan desde sus servicios/configuración reales. Su presencia en la barra no concede permiso de ejecución.
6. Gateway y Bridge permanecen adapters separados. Una falla de conexión no amplía permisos, no habilita shell y no convierte una escritura remota en escritura local.
7. Toda acción con efectos devuelve resultado y recibo. La UI distingue `PASS`, `REJECT`, `NOT_VERIFIABLE` y ausencia de recibo; nunca reduce esos estados a un check verde genérico.
8. L1 no se activa desde el panel por estar listado: creación, gates, activación, registro de capability, grant y aprobación de ejecución son estados diferentes.
9. Para HTTP Gateway, ISySentinel local y Gateway HTTP Sentinel deben permitir independientemente. API keys autentican el perímetro remoto; no son grants locales.

## 4. Milestones

### M0 — Cerrar auditoría, baseline y decisión de runtime

**Estado:** en curso. Ya hay launcher global que conserva el cwd, discovery del `.isyroot` vacío más cercano, separación de `launch_dir`/`workspace_root`/grants, onboarding recurrente opt-in y sesiones de chat reanudables en estado privado externo. Las sesiones temporales se borran al salir; los títulos nacen del primer mensaje. `src/isycode/contracts.py` define interfaces estructurales para runtime, workspace, MCP, skills y verificación; la TUI acepta factories para sustituir runtime/workspace/OpenISy. Los adapters IsyMotron conservan su verificador legado, pero no autorizan Files ni efectos del perfil Secure. Sigue pendiente cerrar el spike/compatibilidad OpenISy.

**Objetivo:** fijar qué contratos consumirá ISyCode y cómo se conectará a OpenISy sin reconstruir su runtime.

**Trabajo:**

- [ ] Confirmar el backend primario de UI: mantener Python/Textual o alojar el panel de ISyMotron dentro del TUI TypeScript de OpenISy. Hacer un spike acotado con lectura de MCP/skills y una operación demo, sin mutaciones reales.
- [x] Añadir ADR al repo con la elección, alternativas, lifecycle de consulta, timeout y política de errores. El ADR sigue propuesto hasta validar su endpoint experimental contra OpenISy.
- [x] Definir `AgentRuntime`, `WorkspaceProvider`, `MCPProvider`, `SkillCatalog` y `ReceiptVerifier` como interfaces Python sin lógica de permisos en widgets. El runtime, workspace y cliente OpenISy se inyectan por factories; el verificador compartido delega en IsyMotron.
- [x] Capturar el cwd canónico como `launch_dir`, resolver el `.isyroot` vacío más cercano como `workspace_root` y mantener los roots de autoridad como dato separado; mostrar identidad y procedencia en la TUI.
- [x] Añadir launcher PATH (`~/.local/bin/isycode`) que resuelve el checkout sin cambiar el cwd de invocación, además de `python -m isycode`; evitar literales de rutas personales.
- [x] Preguntar si el directorio inicial será recurrente. Solo un sí crea el `.isyroot` vacío; un no conserva el fallback y mantiene el historial temporal fuera del workspace.
- [x] Añadir conversaciones con título automático desde el primer mensaje, guardado privado fuera del repo y reanudación desde **Sessions** para roots marcados.
- [x] Invalidar plan y confirmación armada al iniciar una petición nueva o un plan, rechazarlo o fallar; la confirmación guarda el digest exacto del plan presentado. La cancelación del runtime aún no está implementada.

**Criterios de aceptación:**

- La TUI arranca desde un proyecto con espacios en el path y desde otra carpeta distinta al repo ISyCode.
- Se puede iniciar desde un directorio arbitrario y el header, explorer y operaciones nombran el mismo root.
- El adapter de prueba muestra capacidades MCP/skills reales del endpoint configurado o un estado explícito vacío/error; no tiene nombres verdes hardcodeados.
- Un plan rechazado no puede volver a ejecutarse al presionar la tecla de confirmación.
- ADR indica las llamadas exactas a IsyMotron/OpenISy y qué código existente se reutiliza.

**No incluye:** habilitar escritura real ni portar el TUI completo de OpenISy.

### M1 — Shell visual y navegación de la TUI

**Estado:** iteración visual ejecutable: chat principal y rail `Overview`/`Files`; header compacto con ruta de workspace; MCP/skills de OpenISy; sección LSP con estado explícito “sin adapters configurados”; selector de archivos con `Open preview`; `Copy path` deshabilitado hasta que exista owner de clipboard; barra inferior `Sidebar`, `Sessions`, `Providers`, `Role`, `Context` y `⚙`; la paleta `/`/`Ctrl+P` tiene diez ramas semánticas con listas anidadas, scroll y búsqueda. `Ctrl+F` busca en la salida completa del chat y permite recorrer coincidencias. Las entradas de Context y `/readme` indican que el picker nativo está bloqueado hasta que `desktop.file_picker` tenga owner. El rail usa fondo gris grafito y texto lavanda/gris de contraste moderado. Las respuestas del chat y Roundtrip pasan por parser Markdown con estilos para encabezados, negritas, listas, código en línea y bloques con resaltado de sintaxis. `Esc` cancela el stream activo y descarta su respuesta parcial; cuando no hay generación, vuelve del menú o enfoca el composer sin borrar el borrador. Faltan capturas en varios tamaños y la integración de acciones MCP/skills.

**Objetivo:** acercarse a la composición de Crush: chat despejado, panel lateral útil y estados de integración confiables.

**Trabajo:**

- [ ] Definir tokens de color/espaciado y componentes reutilizables: header/banner, chat log, bloque de razonamiento opcional, input multilínea, status bar, rail derecho y tarjetas de actividad. (El popup y la barra inferior ya siguen la guía visual aprobada.)
- [x] Implementar el rail `Overview`/`Files` ajustable con F7/Shift+F7: 32–38 columnas ancho y 22–34 compacto; falta validar el reparto visual en capturas.
- [x] Overview: secciones compactas `MCPs`, `LSPs` y `Skills`; estado MCP/skill derivado del adapter, declarar ausencia de adapter LSP sin simular conexión, `Enter` abre detalle y descripción. Conteos solo cuando la API real los exponga.
- [x] Files: pestaña visible en el mismo rail; navegación por árbol, expansión/cierre, búsqueda, selección y preview gated; regresar al chat sin perder borrador.
- [ ] Copy path: permanecer deshabilitado hasta que `clipboard.copy` tenga un execution owner.
- [x] Atajos documentados y sin colisiones con escritura: `Ctrl+F` buscar en consola, `Ctrl+B` mostrar/ocultar rail, `Ctrl+P` abrir paleta semántica, `F6` Files, `Shift+F6` Overview, `F7`/`Shift+F7` ajustar ancho, `Ctrl+L` enfoca el composer, `Esc` cancela el stream activo y en reposo vuelve del menú/enfoca el composer, `Enter` seleccionar/enviar y `Shift+Enter` nueva línea. Los atajos viven en el engranaje; las confirmaciones no se activan al teclear en el composer.
- [ ] `Context → Inject AGENTS.md…` permanece bloqueado hasta que `desktop.file_picker` tenga un execution owner; después la lectura requerirá grant `workspace.context.inject` + ISySentinel.
- [x] Renderizar Markdown del chat y Roundtrip con jerarquía de encabezados, negritas, listas, código en línea y bloques resaltados; mostrar el stream incrementalmente.
- [x] Mantener rail y popup en paleta gris grafito con contraste legible; conservar acentos de color para estados y selección.
- [x] Loading, error, vacío, desconectado y auth requerida tienen texto distinto en OpenISy; el refresh deshabilita su botón mientras consulta. No usar solo color para distinguirlos.
- [x] Representar estado ocupado de chat/plan, espera de confirmación y listo en una línea persistente independiente del banner temporal de razonamiento.
- [x] Una entrada enviada mientras el agente trabaja conserva el texto en el composer y muestra que el usuario debe reenviarlo al terminar; no se imprime como si estuviera en cola.
- [x] Streaming interrumpido después de recibir texto se marca como parcial/no completado y no se guarda como respuesta completa del historial. Faltan witnesses de timeout/cierre del stream.
- [x] Adaptar sidebar para terminal estrecha: bajo 100 columnas se compacta; bajo 80 se oculta y puede reabrirse con Ctrl+B. Las capturas de aceptación siguen pendientes.

**Criterios de aceptación visual/funcional:**

- Capturas de estados `welcome`, `MCPs conectados`, `sin integraciones`, `Files`, `plan`, `aprobación`, `DENY` y `recibo verificado` en 80×24, 100×30 y 140×40.
- En 140 columnas el chat usa al menos 68% del ancho útil y el rail no causa scroll horizontal.
- A 80×24 la entrada, chat y navegación siguen utilizables; ningún control clave desaparece sin un atajo alterno anunciado.
- MCP/skill con error no se ve verde; los conteos concuerdan con lo reportado por el adapter.
- Las pruebas Textual verifican foco, atajos, redimensionamiento, input ocupado, vistas del rail y estado de streaming.

**No incluye:** clonar colores, logo o arte propietario de Charm/Crush; diff como pantalla inicial; activar herramientas automáticamente.

### M2 — Explorador del workspace actual

**Estado (perfil Secure):** Files/context usan owners nativos ISyCode (`LocalWorkspaceReadOwner`) bajo Workspace Authority + ISySentinel; cada autorización se ata al owner registrado y su decisión/receipt se persiste en el journal privado. El browser queda read-only, parte de `workspace_root`, filtra `.gitignore`, nombres sensibles y symlinks, acota búsquedas/previews y bloquea resultados sin grant. La clase IsyMotronWorkspace sigue como compatibilidad legada, pero no es la ruta del TUI Secure. Faltan fixtures y validación visual/funcional de estos flows.

**Objetivo:** permitir encontrar y leer archivos del directorio donde se invocó `isycode`.

**Trabajo:**

- [x] Resolver el root como `cwd` canónico al iniciar y mostrarlo en header y vista Files.
- [x] Cargar directorios bajo demanda; ordenar carpetas primero; soportar búsqueda difusa acotada (máximo 300 directorios/6,000 entradas por búsqueda).
- [x] Respetar `.gitignore` y permitir incluir ignorados con acción explícita. Si el archivo listado desaparece o no puede leerse, bloquear el listing en vez de aplicar un filtro parcial. Ocultar siempre `.git`, `.isycode`/estado local, claves, `.env` y otros nombres protegidos por el browser.
- [x] No subir al padre del root. No seguir symlink/junction fuera del root. Rechazar paths externos y traversal mediante `.isyroot` + scope de Workspace Authority.
- [x] Al seleccionar archivo, abrir preview de texto de solo lectura con ruta relativa, tamaño, encoding/estado binario y truncación explícita. No interpretar archivos como comandos; archivos sensibles comunes se ocultan y el host exige grant para cualquier lectura.
- [ ] Abrir editor externo solo como acción optativa documentada; el TUI no cambia permisos por hacerlo.
- [x] Usar `workspace.files.list/read/search` de ISyCode con grant explícito por ruta; un grant ausente, fallo del owner o decisión DENY bloquea la lectura.
- [x] Entregar preview/listing solo después de verificar el recibo ligado al digest de request/result y persistir sus digests; `DENY`, `REJECT` y `NOT_VERIFIABLE` bloquean los datos.
- [ ] Si el Gateway ofrece el mismo root, puede alimentar búsqueda/read según su scope. Si su `IESY_ROOT` es distinto, mostrarlo como workspace remoto separado o no ofrecerlo; nunca mezclarlo con Files local.

**Criterios de aceptación:**

- El explorador abre ISyCode desde ISyCode y desde cualquier repo de usuario; ambos muestran el root correcto.
- Fixture con archivo normal, archivo binario, nombre Unicode, carpeta ignorada, `.env`, `.git`, symlink interno y symlink a fuera: solo se ven/abren los casos permitidos por política.
- No puede navegar arriba del root por UI, búsqueda ni ruta escrita.
- Preview de archivo grande se limita y explica la truncación.
- Abrir/cerrar Files no interrumpe la conversación ni cambia el workspace autorizado.

**No incluye:** editor de archivos propio, Git diff browser, delete/move/rename.

### M3 — Integración de MCP y Skills de OpenISy

**Estado:** adapter read-only contra `/mcp` y `/skill` del HTTP API experimental de OpenISy, con cwd, auth opcional, refresh manual y lista completa seleccionable de estados/skills; al refrescar, ambos catálogos muestran `Loading` y el botón se deshabilita hasta obtener resultado; respuestas de refresh anteriores no pisan una más reciente. Al elegir skill muestra origen, descripción y una guía que deja claro que solo el runtime de OpenISy la puede activar hoy. Sin servidor configurado aparecen estados explícitos; errores y auth pendiente se etiquetan. `/mcp` no devuelve conteo de tools; `/experimental/tool` cuenta el registry interno de OpenISy, no el catálogo MCP, así que no se presenta como tal. Este catálogo externo sigue siendo de descubrimiento; la invocación manual descrita en M14 aplica solo al Gateway MCP.

**Objetivo:** hacer que el lateral represente el inventario real de OpenISy y que las skills sean descubribles sin duplicar su cargador.

**Trabajo:**

- [ ] Consumir estado, configuración y catálogo del servidor MCP desde una interfaz soportada por OpenISy (preferir MCP/contrato público a imports internos TS desde Python).
- [ ] Completar el catálogo de herramientas por un contrato estable o MCP estándar. El GET `/mcp` actual solo publica estados de servidor; la UI indica explícitamente que no tiene conteos.
- [ ] Mostrar nombre, connected/disabled/failed/needs-auth, cantidad de herramientas y error seguro/resumido. Actualizar por evento si existe o refresco con intervalo y comando manual.
- [ ] Mostrar skills encontradas por OpenISy con nombre, descripción y origen (`project`, usuario, builtin/remoto); diferenciar instaladas de activas/disponibles para esta sesión.
- [x] Permitir seleccionar una skill para ver su descripción, origen e instrucción de invocación dentro de OpenISy.
- [ ] Integrar activación/inyección de skills únicamente mediante el runtime de OpenISy; ISyCode no simula ni reconstruye esa autoridad.
- [ ] Mostrar eventos del catálogo externo en el transcript solo cuando un contrato runtime real permita una activación/call; el flujo manual Gateway MCP pertenece a M14. El catálogo visible nunca autoriza una llamada.
- [ ] Integrar autenticación requerida con instrucciones claras sin imprimir tokens ni variables secretas.
- [ ] Confirmar compatibilidad de versión OpenISy y fail closed si el contrato es desconocido.

**Criterios de aceptación:**

- Dos fixtures de MCP (uno disponible, otro desconectado) producen estados correctos y número de herramientas correcto; prueba adicional con auth pendiente.
- Skill de proyecto nueva se refleja tras refrescar sin recompilar la TUI; skill denegada no aparece invocable.
- Caída/reinicio de MCP no bloquea escritura en chat ni borra transcript.
- No se presenta una skill o herramienta como “permitida” por el mero hecho de estar descubierta.

**No incluye:** duplicar el framework de plugins de OpenISy ni activar L1.

### M4 — Runtime de IsyMotron detrás del contrato de ISyCode

**Estado (perfil Secure, actualización 2026-09-28):** IsyMotron Planner puede producir una propuesta; la solicitud de provider pasa primero por el host grant de Workspace Authority e ISySentinel. La TUI ya no arma ni confirma su salida como una acción ejecutable, y `IsyMotronRuntime.execute()` rechaza toda ejecución heredada. Sus grants, leases y receipts no son autoridad de producto. Files/context ahora usan owners nativos ISyCode. Los pasos de una propuesta solo podrán ejecutarse cuando cada capability tenga schema, owner, Authority/Systembility, Sentinel y aprobación requerida. Falta implementar motores nativos para las acciones que aún no existen.

**Objetivo:** conservar `/plan` como proposal-only y sustituir gradualmente cualquier uso de IsyMotron como autoridad por el pipeline de ISyCode: provider con host grant → planner → owner tipado → Workspace Authority → ISySentinel → approval requerida → ejecución acotada → receipt/journal.

**Trabajo:**

- [ ] Completar el runtime nativo de ISyCode para catálogo, plan, acciones tipadas, cancelación, estado y receipts. La interfaz de propuesta existe; la ejecución heredada se mantiene deshabilitada hasta migrar cada acción.
- [x] Sustituir la creación de `LegacyHost` y `LoopbackRelay` dentro de widgets por un runtime. Mantener LegacyHost solo en modo demo explícito.
- [x] Mostrar el origen/host para propuestas y declarar que no tienen autoridad ni se ejecutan en Secure.
- [ ] Convertir errores de Provider/Planner/Host a estados tipados y mensajes útiles; no ocultar error en salida normal ni continuar con planes previos. La UI ya traduce fallos comunes del Provider y evita imprimir cuerpos/URLs; el contrato aún no devuelve estados tipados.
- [x] Renderizar plan en pasos con host, capability, parámetros revisables y explicación; marcar claramente `propuesta, sin autoridad`.
- [x] Autorizar el host del provider con Workspace Authority + ISySentinel antes de solicitar una propuesta; conservar `Planner.parse` como formato de propuesta.
- [x] Mostrar decisiones/recibos por paso como eventos individuales; en modo local read-only, presentar el texto de archivo solo tras receipt `PASS`; directorios remiten al browser filtrado.

**Criterios de aceptación:**

- Un plan de LegacyHost no se ejecuta desde la TUI aunque tenga grants de IsyMotron.
- Provider sin host grant explícito no recibe la solicitud del planner.
- Cada capability añadida a la ejecución nativa obtiene su propio owner y tests/witnesses antes de habilitarse.
- Cambiar renderer por un harness fake no cambia decisión del host ni verificación del recibo.
- Inyectar Provider caído, timeout, JSON truncado y tarea cancelada deja estados coherentes y no inicia ejecución oculta.

### M5 — Seguridad, aprobación ligada al plan y recibos (bloquea mutaciones reales)

**Estado:** enforcement y leases se usan para Files y el simulador. El UI llama al verificador real y distingue `PASS`, `REJECT` y `NOT_VERIFIABLE`; solo cuenta como demostrada una ejecución con evidencia del engine y recibo `PASS`. Cada evento de ejecución muestra el sello, status exacto, claim/request/decision match, decisión re-derivada y razón. La revisión muestra host, host ID/engine, capabilities concedidas, bounds lógicos y parámetros. El digest del plan y un fingerprint del contexto de autoridad se comparan al revisar, confirmar e inmediatamente antes de `Executor`; en `local-readonly` también se compara de nuevo el grant file. Un cambio invalida la operación antes de enviar pasos al host. Sigue bloqueando escrituras reales: faltan witnesses completos y validación con hosts reales; no existe cancelación dentro de Executor.

**Objetivo:** garantizar que la aprobación cubre exactamente lo que el host vuelve a validar y ejecutar.

**Trabajo:**

- [x] Construir catálogo desde `HostDescription.granted`; IsyMotron `Planner.catalogue` filtra las capacidades no concedidas antes de enviar el catálogo al modelo.
- [x] En modo `local-readonly`, volver a leer IsyMotron grants antes de ejecutar y rechazar el plan si difieren del snapshot usado al crear el runtime.
- [x] Ligar el doble paso de revisión/confirmación al digest del plan y fingerprint de identidad/catálogo/grants/bounds; volver a comparar el contexto antes de ejecutar. La UI muestra identidad, grants, bounds y parámetros revisados.
- [ ] Usar scope de host y concesiones verificables por cada operación. Para filesystem, conceder el root explícito del workspace; no usar la policy experimental de IsyVM ni `src/isycode/safety.py` como autoridad paralela.
- [ ] Presentar una pantalla/confirmación que identifique host, capability/efecto, rutas lógicas afectadas y parámetros. Para operación destructiva, presentar manifest/blast radius solo si el host real puede resolverlo y volver a comprobarlo.
- [ ] Ampliar el binding de confirmación para manifests/leases cuando haya operaciones que los creen antes de la aprobación. Hoy la ejecución no emite leases hasta después de confirmar; para el runtime actual se liga plan + contexto de autoridad y la aprobación caduca en 10 segundos.
- [ ] No permitir doble-R sobre un buffer global. Usar acción contextual/confirmación modal; el foco del input no puede disparar mutaciones.
- [ ] Invalidar plan anterior al empezar cualquier petición nueva, incluso si la petición falla o es rechazada.
- [ ] Ejecutar únicamente mediante `Executor`/`Host`; no escribir archivos directamente desde la UI, ni añadir fallback a `bash`, terminal, `shutil` o Gateway cuando falle el host.
- [x] Verificar recibos con `verify_receipt` y renderizar seal, request/claim match, decision re-derivada, razón y estatus exacto. No ocultar `NOT_VERIFIABLE`.
- [ ] Al cancelar o interrumpir, no marcar step como terminado sin recibo; refrescar plan/scope antes de reintento.

**Gate bloqueante:** no se expone botón/atajo de write para workspace real hasta que todos los siguientes witnesses pasen con hosts de fixture/desechables y receipt verifier real.

**Criterios de aceptación / witnesses:**

1. Capability ausente del grant → no se lista al modelo y el host deniega si se fuerza manualmente.
2. Path fuera del root, traversal, enlace/junction escape y root protegido → host DENY; ninguna modificación observable.
3. Cambiar el plan o manifest después de aprobar → digest mismatch, cancelación y nueva revisión requerida.
4. Lease expirado, revocado o para otro host/capability/sujeto → DENY.
5. Recibo alterado, claim distinto o request digest diferente → verifier devuelve REJECT; UI nunca muestra PASS.
6. Gateway desconectado → cualquier mutación por Gateway falla cerrada; ninguna ruta shell/local alternativa se intenta.
7. Error del engine no se etiqueta ALLOW exitoso; resultado parcial/unknown se representa sin fabricar recibo.
8. Mismo request con distinto provider/model → la autoridad sale del host/grant, no de identidad ni confianza en el modelo.

### M6 — File operations y capacidades OpenISy bajo grants explícitos

**Estado:** Files/context usan owners nativos ISyCode. El planner IsyMotron queda en modo proposal-only, y el Executor heredado está bloqueado en Secure aunque IsyMotron tenga grants. ISyCode muestra disponibilidad del Gateway sin decir que está conectado al workspace local; admite `GATEWAY_URL`, exige HTTPS fuera de loopback y bloquea redirects a otro origen para no filtrar el bearer token. Gateway y el resto de capacidades siguen sin integrarse en un runtime nativo universal; cualquier escritura real continúa pendiente de M15/M6. El health endpoint oculta intencionalmente `IESY_ROOT`, por lo que hoy no existe evidencia para comparar el root con `cwd` ni para montar el explorador remoto.

**Objetivo:** habilitar gradualmente operaciones reales sin convertir MCP, Gateway o shell en un bypass de Workspace Authority + ISySentinel.

**Trabajo:**

- [ ] Acordar con Gateway una identidad remota no sensible y verificable (por ejemplo, ID configurado del workspace); no exponer el path físico en `/health`. Hasta tenerla, Gateway se limita a estado de disponibilidad y sus archivos no aparecen en Files.
- [ ] En la primera entrega habilitar solo read/list/search del workspace remoto identificado, con scope al root y límites/redacción del host.
- [ ] Mapear operaciones Gateway a capabilities/hosts explícitos. Confirmar quién autoriza cada integración; permisos Gateway (`isyco.read`, `isyco.write`) y grants locales de Workspace Authority son gates independientes.
- [ ] Activar write solo cuando Gateway root coincide con el workspace remoto seleccionado y tanto el key scope como host grant permiten la acción; indicar overwrite/create antes de pedir aprobación.
- [ ] Mantener Drive, Email, GitHub y MCP en su superficie específica. `email.send`, upload, crear issue y otras mutaciones externas necesitan aprobación/efecto visible propio.
- [ ] Dejar delete, chmod, move, `sudo` y shell deshabilitados hasta que exista capability, engine y política IsyMotron auditados para cada una.
- [ ] En modo Gateway degradado, mostrar estado y conservar tareas/read local solo si la capability local fue concedida por IsyMotron.

**Criterios de aceptación:**

- Demo con Gateway `IESY_ROOT` igual y diferente al `cwd`: el ID del workspace permite verificar coincidencia; diferencia aparece como workspace separado y nunca se mezcla. Hasta que exista ese contrato, ambas condiciones deben resultar en “root remoto no verificado”, sin montar rutas Gateway en Files.
- Para todas las rutas de mutación soportadas, quitar scope del Gateway o grant del host causa DENY y ninguna escritura.
- Pruebas con redacción de secretos, límites de tamaño, timeout y rate-limit preservan UI usable sin exponer key/token.
- Cada side effect tiene un receipt de host y un evento visible en transcript.

### M7 — Sesiones, fallos y recuperación

**Estado:** `src/isycode/session.py` tiene IDs estrictos, directorio real 0700, escritura atómica con fsync, límites de tamaño y lectura que rechaza symlinks/archivos no regulares. El parser valida estructura; `verify_chain()` rechaza gaps, duplicados, referencias vacías y pasos que no coinciden con el plan. `load_for_resume()` añade una compuerta separada que exige la huella de autoridad vigente y un callback para volver a verificar cada recibo; al aceptar, borra approvals y lease de la copia recuperada. `load()` conserva su comportamiento de inspección por compatibilidad. Aún no se invoca desde TUI/runtime: no reanuda ejecución, no obtiene la huella/grants actuales por sí solo y el callback canónico de IsyMotron todavía no está conectado. Tampoco hay política completa de redacción/allowlist para datos persistidos.

**Objetivo:** reanudar trabajo sin confiar en memoria privada del modelo ni repetir side effects exitosos.

**Trabajo:**

- [ ] Persistir session id, intento actual, plan aceptado/digest, snapshot de grants, pasos con recibos, pendientes, approvals/lease con expiración, provider/model y timestamps.
- [ ] Persistencia atómica con permisos de archivo restrictivos; nunca guardar API keys, OAuth tokens, contenido secreto innecesario o chain-of-thought crudo.
- [x] Base fail-closed: verificar estructura y continuidad de la cadena; `load_for_resume()` rechaza cadena inválida y exige revalidación de cada recibo. Sigue pendiente conectarlo al verificador IsyMotron y al flujo de inspección/export del TUI.
- [x] Base de reanudación: la compuerta descarta approvals y lease heredados y rechaza huella de autoridad distinta. Sigue pendiente recalcular grants desde los hosts actuales y pedir nueva aprobación contextual desde el TUI/runtime.
- [ ] Manejar provider 429/5xx/timeout, output malformado y cierre del proceso con reintentos acotados, cancelación y handoff optativo.
- [ ] Retener comportamiento de UI: mensaje truncado se marca parcial; no se mezcla con respuesta completa ni se manda de vuelta como respuesta terminada.

**Criterios de aceptación:**

- Caída después del paso 2 de 4 reanuda en el primer paso sin recibo válido; los pasos con receipts nunca se repiten.
- Receipt faltante/digest corrupto/gap en cadena impide ejecución y muestra razón.
- Provider replacement recibe intent/plan/receipts/outstanding, no reasoning privado del provider anterior.
- Soak reproducible de 20 turnos con malformed JSON, timeout/429 y una capability no concedida: imprimir métricas por turno y cero escalación.

### M8 — Bridge y coordinación multi-agente (opcional)

**Estado:** wrapper `src/isycode/bridge.py` y handshake existen; superficie visual y gates de coordinación pendientes.

**Objetivo:** exponer presencia, mensajes y leases del Bridge sin confundir coordinación con autoridad local.

**Trabajo:**

- [ ] Mostrar identidad del agente, status, peers y lease con expiración, owner, topic y path lógico.
- [ ] Integrar heartbeat/peek/send/claim/release por adapter; mostrar expiración y error de red.
- [ ] Un lease del Bridge es señal de coordinación y nunca equivale a un grant de Workspace Authority.
- [ ] Evitar claim con path físico fuera del workspace autorizado; credenciales/tokens del bridge no aparecen en transcript.

**Criterios de aceptación:** dos agentes comparten tarea, conflicto de lease se muestra y bloquea colisión; aun con lease adquirido, operación no concedida por host recibe DENY.

### M9 — L1 / herramientas creadas por OpenISy (opcional y al final)

**Estado:** OpenISy tiene pipeline L1; TUI de ISyCode no lo integra.

**Objetivo:** permitir descubrimiento/inspección de herramientas autoextendidas sin convertir creación en autoridad.

**Trabajo:**

- [ ] Lectura/listado de estado L1 y detalle de generación/evidencias en panel OpenISy.
- [ ] Activación solo tras gates reales de OpenISy: validate → test → probe → seal → active; respeto a safe mode y flag experimental.
- [ ] Mostrar capability, effect y estado registration/grant de Workspace Authority por separado.
- [ ] Una tool `ACTIVE` en OpenISy no entra al catálogo de ejecución hasta que esté registrada y concedida en autoridad IsyMotron. Cambiar implementación invalida freshness/evidence según OpenISy.

**Criterios de aceptación:** herramienta nueva (incluida una destructiva) puede existir/probarse y permanece no invocable hasta registro y grant independientes; safe mode deshabilita su carga; rollback deja evidencia y herramienta previa intacta.

### M10 — Navegador semántico `isyco cli`

**Estado:** `isyco cli` abre un árbol interactivo con ramas Agent, Workspace, Integrations, Providers, Session y Settings. El árbol se puede filtrar por nombre/descripción y recorrer con teclado; Enter inspecciona una hoja y `Open selected` lleva a vistas o comandos que ya existen en ISyCode. `/session` muestra workspace/provider/model/rol sin exponer historial. No lanza shell ni crea autoridad paralela. Falta inspección visual manual del nuevo filtro en terminales pequeñas.

**Objetivo:** ofrecer una entrada CLI fácil de descubrir, organizada como carpetas por intención y conectada a las vistas reales de ISyCode.

**Trabajo:**

- [x] Conservar el `isyco` existente y añadir `cli` como ruta explícita a ISyCode; conservar `isycode` como launcher directo de la TUI.
- [x] Abrir `isyco cli` como navegador interactivo con seis ramas semánticas y descripción de cada acción; ninguna hoja se abre antes de `Open selected`.
- [x] Conectar Chat, Plan prellenado, Help, Files, OpenISy Overview, Providers, Roles, Settings y estado de sesión a vistas/comandos reales de la TUI.
- [x] Expandir ramas/hojas para capacidades implementadas: sesión, configuración, MCP/skills, provider/modelo y ayuda; describir efectos y pedir confirmación de apertura.
- [x] Incorporar filtro por nombre/descripción y navegación de teclado con Tree (↑/↓, ←/→, Enter, Esc); Esc limpia el filtro y luego vuelve/sale.
- [x] Documentar instalación/uso y conservar el dispatcher `isyco` existente; los motores con autoridad no se sustituyen por aliases ni por nuevas ejecuciones del navegador.

**Criterios de aceptación:**

- `isycode` abre la TUI; `isyco cli` abre el árbol de intenciones; `isyco` sin argumentos muestra uso breve.
- Cada hoja lleva a una acción implementada y no dispara ejecución externa al seleccionarla; cancelar vuelve al shell sin cambiar workspace ni autoridad.
- Las ramas se pueden navegar con teclado, buscar por nombre/descrición y entender antes de abrir. Inspección de legibilidad en terminal pequeña pendiente.
- No se muestra una integración como disponible si el adapter reporta desconexión/error, y no se inventan comandos que aún no existen.

### M11 — Catálogo de providers y colaboración Roundtrip

**Estado (alcance de validación acotado):** ISyCode tiene presets cloud OpenAI-compatible para OpenAI, NVIDIA NIM, Nebius, Groq y OpenRouter; Ollama y llama.cpp permanecen como endpoints locales opcionales y fuera de la matriz de validación cloud. Groq y OpenRouter usan sus endpoints y variables de clave oficiales. El selector y el vault usan metadatos de ISyCode primero; se conserva fallback del adapter heredado de IsyMotron donde aplique. La clave se busca primero en la bóveda de ISyCode (secretos en el keyring del SO, metadatos privados), después en variables de entorno y al final en el almacén heredado de IsyMotron. El selector muestra presencia sin leer ni revelar el valor. Evidencia: el usuario probó NVIDIA NIM en la TUI; su captura muestra el primer request denegado, el grant explícito de `integrate.api.nvidia.com` y una respuesta a “Hola”. Nebius había sido probado previamente por el equipo. Groq/OpenRouter tienen presets probados estáticamente, pero aún no una llamada autenticada en vivo; OpenAI tampoco tiene evidencia live registrada aquí. Cualquier otro proveedor/API queda abierto para propuesta por PR o issue. La rama Models consulta el catálogo solo si el usuario lo pide. Siguen pendientes validar conexiones reales de los providers sin evidencia live, persistir provider/modelo predeterminados, capacidades por modelo, estados conectada/ejecutable, presupuesto/costo, telemetría, proxy cancelable y OAuth nativo. OAuth descubierto desde servicios remotos no se presenta como autenticación de ISyCode.

**Objetivo:** elegir y conectar providers desde ISyCode y permitir que un segundo modelo revise una tarea en un ciclo acotado. Las acciones locales obedecen a ISySentinel + Workspace Authority; IsyMotron solo puede actuar como adapter/runtime opcional.

**M11-A — Providers y autenticación**

- [ ] Definir un catálogo tipado: id, nombre, modelos disponibles, capacidades del endpoint, métodos de autenticación, estado de conexión y configuración elegida. Separar modelos del provider primario y del modelo revisor.
- [x] Añadir OpenAI API al seam de IsyMotron con `OPENAI_API_KEY`; GPT-6 Chat Completions usa `max_completion_tokens`, `reasoning_effort` y omite `temperature` cuando effort no es `none`. La misma configuración llega al stream del TUI.
- [x] Conectar el catálogo a la TUI: `/providers` muestra presets/credenciales, `/provider <id> [model]` selecciona por sesión y `/provider models` consulta los modelos de la cuenta.
- [x] Añadir presets cloud de Groq y OpenRouter al transporte compatible existente; quedan dentro del alcance admitido, pero no se declaran verificados en vivo sin claves y una llamada real. Otros proveedores cloud requieren PR o issue.
- [x] Reemplazar el listado textual por el selector visual inferior de catálogo, manteniendo `/providers` y `/provider <id> [model]` por comando.
- [x] Añadir `gpt-6-luna` como default configurable y `ISYMOTRON_REASONING_EFFORT` para seleccionar esfuerzo. Falta disponibilidad por cuenta, prueba de API y presentar tokens/costo en UI.
- [x] Seleccionar `nvidia/nemotron-3-ultra-550b-a55b` como default NVIDIA NIM de ISyCode y respetar `ISYMOTRON_MODEL` explícito; no cambia el default compartido de IsyMotron.
- [x] Tratar API key y OAuth como flujos distintos: API key es una entrada enmascarada persistida fuera del repo; OAuth reportado por OpenISy se marca como propio de OpenISy y no se acepta como credencial IsyMotron.
- [x] Migrar el guardado de credenciales nuevas al keyring del sistema mediante la bóveda de ISyCode; mantener env y almacén heredado como transición de lectura. El TUI no muestra el valor en pantalla, logs ni recibos.
- [ ] Nunca reutilizar cookies, sesión de Codex/ChatGPT ni credenciales internas de OpenCode como login de API. Una clave OpenAI de API usa facturación y límites de API independientes.
- [ ] Mantener selección equivalente por configuración/env para automatización y recuperar estado claro si el provider, modelo o permiso API no está disponible.

**M11-B — Roundtrip con segundo modelo**

- [x] Añadir `/review <text>` como acción explícita con el provider/modelo secundario fijo OpenAI API / GPT-6 Luna.
- [x] Delimitar cada roundtrip al texto escrito por el usuario, mostrarlo completo y permitir cancelar antes de enviar.
- [x] Mostrar la respuesta en un panel propio; solo el botón `Iterate with this review` prepara el contenido para el modelo principal, que queda editable en el composer hasta Enter.
- [x] Mantener una revisión por sesión y tope de salida de 1,200 tokens; el botón `Cancel review` cancela la tarea de conexión/stream y descarta salida parcial sin reintento automático.
- [ ] Definir límite/presupuesto de costo configurable y persistir el uso reportado sin guardar artefacto ni chain-of-thought.
- [x] El revisor no recibe herramientas con efectos ni puede aprobar/ejecutar planes. Cualquier plan posterior sigue pasando por IsyMotron.
- [ ] Persistir telemetría mínima de provider/modelo/uso/errores sin secretos ni chain-of-thought; UI muestra proveedor y tokens cuando la API los devuelve.

**Criterios de aceptación:**

- El selector distingue listo, falta credencial, OAuth pendiente, desconectado, modelo no disponible y error; ningún estado se marca conectado solo por aparecer en catálogo.
- Una llamada de OpenAI API usa el modelo id seleccionado y muestra tokens/costo reportados; falla cerrada si la API rechaza el modelo o el permiso.
- Un revisor puede detectar y devolver un problema; no puede ejecutar una herramienta ni ampliar authority; el usuario controla si esa revisión regresa al modelo principal.
- Cancelar, alcanzar presupuesto o recibir error termina el Roundtrip sin perder la conversación primaria ni repetir llamadas en secreto.
- Dos iteraciones como máximo por defecto y límite total verificable de llamadas/tokens; IsyMotron conserva el gate de cada side effect.

### M12 — Paleta semántica, opciones y selector de roles

**Estado:** implementado en la TUI: barra inferior compacta, popup `/` de dos niveles con diez ramas, lista desplazable y búsqueda; engranaje con comandos/atajos; selector Provider y Role. El selector presenta los presets del chat nativo (cinco APIs cloud en el alcance actual y dos endpoints locales opcionales), y mantiene separada la disponibilidad del planner IsyMotron, que solo cambia si su adapter reconoce el provider. Si hay una integración OpenISy configurada, su inventario y auth metadata aparecen por separado. Los agentes de chat y los ocho motores operativos ISyCo permanecen separados. Cada motor transfiere al contexto del rol su flujo ordenado, alcance de capacidades, comandos y límites. La selección no concede tools ni ejecuta comandos CLI desde el chat. Ver [diseño aprobado](design/2026-09-27-tui-navigation.md) y [plan](plans/2026-09-27-tui-navigation.md).

**Criterios entregados:**

- [x] `/` abre las ramas Skills, Models, MCP, LSP, Files, Roles, Providers, Session, Workspace y Commands; las ramas abren su inventario actual.
- [x] Búsqueda, scroll, Enter para seleccionar y Escape para volver/cerrar.
- [x] Footer global oculto; Sidebar, Providers, Role y ⚙ están en la barra, sin botón de envío.
- [x] Gear incluye lista de atajos activos, controles de workspace, refresh de catálogos y limpiar rol.
- [x] La clave del provider se captura enmascarada y se guarda atómicamente fuera del repo; no se imprime su contenido.
- [x] Agentes de chat y ocho motores operativos ISyCo se muestran en secciones distintas; el catálogo incluye workflow, alcance, comandos, restricciones y kernel compartido.

**Pendiente para completar los catálogos conectados:**

- [ ] Conectar discovery de LSP cuando ISyCode tenga una interfaz/adaptador LSP real.
- [x] Completar el acceso visual a los modelos por cuenta: Models permite cargar el catálogo remoto del provider activo de forma explícita y selecciona un ID para esta sesión. Aún no se consultaron modelos contra una cuenta real en este trabajo.
- [ ] No habilitar OAuth desde ISyCode hasta tener un puente de inferencia sin tools y con callback/state/refresh correctamente aislados.
- [ ] Añadir acciones de activación MCP/skills solo mediante contratos runtime que preserven IsyMotron y la autoridad de OpenISy.

### M13 — Mobile Host: sustrato de ISyCode Móvil

**Estado (actualización 2026-09-29):** etapa local implementada en ISyCode y conectada a owners de Workspace Authority/ISySentinel. La TUI no inicia el host automáticamente: Settings pide grant y aprobación explícitos antes de escuchar en `127.0.0.1:8765`; al cerrar la TUI, el listener se limpia como ciclo de vida, mientras la acción seleccionable `mobile.host.stop` sigue DENY. Pairing exige grant `mobile.pair`, PIN local de seis dígitos de un solo uso y receipt durable antes de devolver una credencial aleatoria de una hora; el keystore conserva su hash. Settings muestra liveness y clientes autenticados. Private access propone `/isycode` hacia Mobile Host y el health probe verifica el path montado `/isycode/v1/health`; requiere aprobación separada y mantiene Funnel apagado. **NOT_DEMONSTRATED:** todavía no se cambió Serve en vivo ni se emparejó desde un segundo dispositivo del tailnet. El inventario detecta comandos instalados pero mantiene todos los adapters no seleccionables.

**Entregado en esta etapa:**

- [x] Arranque/parada del host ligados al ciclo de vida de la TUI; el refresh del estado no reinicia catálogos ni workspace.
- [x] `GET /v1/health`, `GET /v1/status` protegido por scope, `POST /v1/pair/exchange`, `GET /v1/runtimes`, `POST /v1/runtimes/select` (respuesta explícita `409` mientras falten adapters) y `POST /v1/clients/heartbeat`.
- [x] Rate limits por peer y global para intentos fallidos; credenciales bearer revocables/expirables por el almacén interno, con scopes y allowlist de runtime.
- [x] Settings diferencia host vivo de clientes conectados y permite generar un PIN nuevo localmente.
- [x] Iniciar Mobile Host desde Settings con grant por workspace, aprobación de un uso y límite loopback; pairing queda gated y produce receipt antes de responder.
- [x] Integrar preview y health probe de Tailscale Serve con la ruta Mobile Host `/isycode` y puerto loopback `8765`; la operación live sigue dependiendo de aprobación del usuario y witness externo.
- [x] Contrato y límites de esta versión documentados en `docs/mobile-host-v1.md`, README y GUIA.

**Pendiente antes de llamar usable a ISyCode Móvil:**

- [ ] Migrar cliente móvil al contrato sin romper sus pairings actuales; acordar esquema de identidad del dispositivo, rotación/renovación y revocación visible para usuario.
- [ ] Añadir administración de credenciales desde Settings (nombre, grants por runtime/acción, expiración, revocar y recibo de creación).
- [ ] Implementar adapters de runtime reales y solo listar como seleccionables los que puedan crear sesiones bajo la autoridad IsyMotron.
- [ ] Definir y servir `POST/GET /v1/sessions`, reanudación segura, ownership por credencial y aislamiento por workspace.
- [ ] Definir WebSocket de eventos con secuencia/replay/backpressure, estados de error y reconexión.
- [ ] Implementar cancelación y approvals con expiración, binding a sesión/turno/capability, auditoría y validación del host.
- [ ] Demostrar Serve y pairing desde un segundo dispositivo autorizado del tailnet; mantenerlo no demostrado hasta verificar la ruta externa real y su flujo de intercambio.
- [ ] Cerrar threat model, límites de requests, revocación, recuperación/crash y pruebas de integración host-cliente antes de marcar la feature completa.

**Gate de seguridad:** el cliente nunca elige un runtime solo porque aparece en el catálogo; toda operación de sesión valida credencial, workspace, runtime, acción y grant/approval de Workspace Authority + ISySentinel antes de dispatch. Health permanece mínimo y no revela nombres de dispositivos ni pairing.

### M15 — ISySentinel y fronteras de seguridad

**Estado (actualización 2026-09-29):** ISySentinel y Workspace Authority están separados; grants por `.isyroot` requieren owner registrado y approvals request-bound, atómicas y de un solo uso. El snapshot clasifica 61 acciones: 26 con owner válido, una lectura compartida, una variante, 32 DENY explícitas y una no-authority; no hay acciones sin clasificar ni owners ambiguos. Mobile Host agrega owners para el arranque loopback y el pairing; su apagado al cerrar TUI está anotado como cleanup, no como permiso `mobile.host.stop`. El auditor AST no encuentra bypasses directos en la TUI. La cobertura Secure local está cerrada. En el Gateway separado se corrigió el scanner AST para seguir imports del servidor FastAPI, se alineó la claim, `/health` informa `read_only: false` y las mutaciones de Drive/Gmail/GitHub usan scopes granulares que no se heredan de las scopes legacy de lectura. La configuración rechaza aliases y el compose de producción fija un worker y exige HTTPS por el proxy confiable. Suite Gateway: 89 tests pasaron; el reporte estático OpenAPI marcó 6 PASS, 10 DEGRADED documentados, 16 NOT_DEMONSTRATED y cero drift/backend ausente. **El deployment no está demostrado ni actualizado:** el contenedor local aún devuelve el health anterior y el origen público observado muestra la página por defecto de ngrok; no hay tunnel activo. Tampoco se configuraron workspace IDs, grants/approval ni una key semántica para una llamada real. M15 sigue abierto por actualizar/restaurar el origen, verificar HTTPS/proxy en vivo y completar un roundtrip remoto con ambos gates. Ver [contrato de fronteras](design/isysentinel-security-boundaries.md) y [auditoría M15 Gateway](security/m15-gateway-audit-2026-09-28.md).

**Objetivo:** hacer de ISySentinel la decisión de seguridad de ISyCode, con autoridad explícita por `.isyroot`, Systembilities de solo lectura y ejecución posterior por adapters. Mantener Gateway HTTP Sentinel como gate remoto independiente.

- [x] Separar `Workspace Authority` (política explícita per-root) de `IsySentinel` (agregación pura de Systembilities); `.isyroot` solo fija el límite máximo.
- [x] Evaluar todos los checks aplicables y reportarlos; error, excepción, acción desconocida o conjunto vacío → DENY.
- [x] Añadir binding verificable entre `ActionRequest` inmutable y execution owner antes de ALLOW; el digest incluye el owner y el Sentinel comprueba la pareja contra el registro explícito de owners implementados.
- [x] Clasificar cada acción del catálogo como owner válido, DENY explícito o no-authority; cerrar la ambigüedad de `broker.start` con variantes disjuntas y guardar un snapshot reproducible. Esta marca cubre el catálogo, no demuestra reachability end-to-end.
- [x] Mantener prompts, emisión/consumo de approvals, auditoría y receipts fuera de Sentinel; approvals ligados a digest con expiración y consumo atómico de un solo uso. El journal append-only valida decisión/receipt y el inspector es read-only; no retiene payloads.
- [x] Definir política y modelo de estado por workspace fuera del checkout, con permisos por action y scope; estado faltante o inválido → DENY.
- [x] Cerrar la superficie Secure de la TUI: filesystem/context, provider, Gateway, MCP/skills, LSP y broker usan owners; Bridge/Mobile, credenciales nuevas, sesiones persistentes, picker y clipboard sin owner quedan bloqueados. La auditoría AST de la entrada TUI y sus modales construidos pasa sin bypass directo.
- [x] Alcance Secure: mantener sesiones persistentes, Mobile Host, Bridge, L1, clipboard, picker y mutaciones sin owner en DENY/inaccesibles; solo reabrirlos con contratos Authority/Sentinel/approval/receipt completos. Su implementación funcional pertenece a hitos posteriores y no es un requisito para cerrar la superficie Secure.
- [x] Exponer en Settings grants por `.isyroot`, y mostrar Authority, cada Systembility, Gateway cuando aplique, y estado de ejecución/receipt por separado.
- [x] Revisar de solo lectura el request path del Gateway HTTP: auth y scopes por ruta, revocación al releer keystore, redacción, rate limits por proceso y HTTPS condicional. `gateway/sentinel.py` no tiene callsite en FastAPI; no presentar sus defectos legacy como controles activos. Registrar resultados y límites en [la auditoría Gateway](security/m15-gateway-audit-2026-09-28.md).
- [x] Gateway externo (código): el test recorre imports locales alcanzables desde FastAPI, la claim se llama `WRITE_SURFACE_RESTRICTED`, `/health` informa `read_only: false`, y Drive/Gmail/GitHub separan scopes de lectura y mutación; aliases inseguros rechazan el arranque.
- [x] Gateway externo (receta): el compose fija un worker y exige HTTPS mediante el proxy confiable; el healthcheck local presenta el header esperado.
- [ ] Gateway externo (deployment): actualizar el contenedor y restaurar un tunnel/origen funcional. El contenedor vivo sigue exponiendo health viejo y el origen público observado devuelve la página por defecto de ngrok; Compose no encontró el token de Cloudflare en el entorno.
- [ ] Verificar HTTPS/proxy en el despliegue vivo y decidir si el límite por proceso basta para la carga real. La receta fija un worker, pero eso no demuestra el origen público.
- [ ] Demostrar una operación semántica remota desde ISyCode con workspace ID coincidente, grant/approval local y scope Gateway correcto. Esto no se sustituye por la health check.
- [x] Cerrar witnesses locales de root/path/symlink, grants vacíos, fallos/excepciones, approvals stale/replay, bypasses y keys inválidas/revocadas/expiradas; agregar recibos durables de owners conectados y pruebas locales de redirect/origin del cliente Gateway. Las capacidades sin owner siguen en DENY.

### M14 — Gateway semántico nativo, LSP y provisionamiento de brokers

**Estado:** implementación nativa conectada; live witness parcial. El reporte de Maintainer aportado por Danny (MCP v0.2.1 → Gateway → broker Docker; `tools/list` reportó 31 tools; pruebas reportadas 18/18 del broker y 9/9 del MCP) describe el stack de ISyCo, no una verificación hecha por ISyCode. ISyCode conserva discovery e invocación manual Gateway MCP bajo owner/grant/approval separados. Las once operaciones semánticas HTTP tienen allowlist, payloads estrictos, selector/revisión en TUI, owner, grant local, aprobación de un uso y recibo local en memoria; el resultado permanece fuera del contexto del modelo. Gateway ahora expone un ID opaco protegido por `isyco.semantic` y compara ese ID en cada operación. El ID requiere configuración coincidente en ambos lados: es una afirmación de binding del operador, no prueba criptográfica de igualdad física de árboles. No se hizo una operación semántica contra el Gateway real: el Gateway actual no tiene ID configurado y la autoridad local no tiene grants. Health del Gateway devolvió HTTP 200. Pyright respondió `initialize` y `workspace/symbol` reales contra un workspace temporal y devolvió `HandshakeWitness`; pruebas negativas confirmaron que el sandbox deniega sockets y escritura al workspace. Este host no permite crear namespace de red, así que Bubblewrap conserva el namespace host y un bootstrap confiable instala seccomp para denegar sockets e io_uring antes de ejecutar Pyright. El root activo se resolvió como fallback al directorio de lanzamiento porque no hay `.isyroot`; su autoridad está vacía, así que no se inició ningún servidor LSP sobre el código del usuario. Broker: build y arranque reales con Docker demostrados para ISyCode; recipe digest `58b69a41…`, montaje read-only, `cap_drop: ALL`, `no-new-privileges`, límites de recursos y credenciales ausentes. La red es Docker `internal` sin publish; un proxy host aparte escucha solo en `127.0.0.1`, valida las once rutas HTTP semánticas, limita cuerpos/respuestas a 1 MiB y reintenta health por hasta 20 s. Health pasó mediante el owner registrado; `definition` respondió `source: jedi`, `degraded: false`; `symbols/search` también respondió 200 indicando honestamente `source: fallback`; `/v1/delete` respondió 404. Se verificó el ciclo Start de un broker previamente detenido. Los grants y approvals de esta ejecución fueron temporales y no se guardaron en Workspace Authority; el broker quedó registrado en estado privado local. El inventario conserva identidad de contenedor/red y del proxy para Health/Logs/Start/Stop/Remove; Logs redacta patrones comunes y Remove conserva la imagen compartida. Los lifecycle tests siguen usando Docker simulado; falta un informe de métricas persistente y una operación Gateway real autorizada. `rust-analyzer` se detecta pero sigue sin adapter seguro. El broker Jedi/AST y `pyright` CLI no se presentan como protocolo LSP.

**Objetivo:** ofrecer operaciones semánticas como herramientas nativas de ISyCode sobre el Gateway HTTP, permitir crear un broker read-only para una carpeta elegida y reportar resultados medibles. No duplicar MCP, OAuth, IsyMotron ni el código dueño del Gateway.

**M14-A — Contrato nativo Gateway (read-only primero)**

- [x] Mantener `SemanticGatewayClient` sobre HTTP con allowlist exacta de once operaciones semánticas; ninguna escritura se incluye en el adapter.
- [x] Usar `GATEWAY_URL` y una key con scope `isyco.semantic` desde `CredentialVault`; no pedir OAuth para operaciones locales/semánticas ni mostrar, persistir en transcript o pasar la key al broker de análisis.
- [x] Extender el catálogo de credenciales por servicio: API keys con nombre, propósito y service/provider se guardan en el keyring del sistema; Settings presenta metadatos y presencia, permite revocar y nunca vuelve a revelar el secreto. OAuth sigue como flujo distinto y no se simula con una API key.
- [x] Presentar las once operaciones semánticas como herramienta nativa en `/` → MCP, con etiqueta HTTP para distinguirlas de `tools/call`; no se inyectan al contexto del modelo.
- [x] Enlazar `symbols/search` a ISySentinel/Workspace Authority local, aprobación por llamada y recibo en memoria. La key autentica al Gateway, pero no sustituye el grant local; el Gateway mantiene su Sentinel HTTP remoto.
- [x] Mostrar el JSON del resultado, con los campos disponibles (`source`, `degraded`, `truncated`) y errores seguros; no inferir semántica completa de una respuesta `fallback`.
- [x] Excluir `write_file`, `applyEdit` y rutas mutadoras del owner semántico. Fallos del Gateway no activan shell ni MCP como fallback.
- [x] Añadir owners/UI con payloads tipados para las otras diez operaciones semánticas y exigir un ID de workspace configurado que coincida entre cliente y Gateway.
- [ ] Configurar ambos IDs en una instalación real y demostrar identidad + una operación semántica completa con grants locales y scope remoto autorizados.

**M14-B — Provisionar un broker para una carpeta elegida**

- [x] Reusar el picker Linux para elegir el root canónico; limitarlo al `.isyroot` activo, comprobar symlinks e identidad. El owner también comprueba el grant `workspace.files.read` del subárbol elegido antes de incluirlo en el plan.
- [x] Fijar el primer preview a la receta del broker semántico en el checkout ISyCo configurado, leer una allowlist acotada y mostrar hashes reproducibles. El preview no ejecuta scripts ni Docker.
- [x] Revisar y confirmar en una pantalla la receta externa antes de build; explicar que el build usa la red del daemon para descargar dependencias.
- [x] Antes de build, presentar carpeta/root, hashes de archivos de receta, imagen, puerto loopback y efectos exactos; pedir approvals separadas ligadas a digest/root por Authority y Sentinel.
- [x] Enviar build/start al execution owner tipado tras ISySentinel ALLOW; no ejecutar `docker`, shell ni Compose directamente desde widgets ni montar el socket Docker dentro del broker.
- [x] Montar el proyecto elegido read-only en `/workspace`; `read_only`, `cap_drop: ALL`, `no-new-privileges`, límites de PIDs/CPU/memoria y filesystem temporal limitado. No montar secretos ni credenciales.
- [x] Mantener configuración e inventario privado fuera del proyecto; un ID por root detecta conflictos y permite abrir un broker registrado sin rebuild.
- [x] Añadir acciones explícitas `Build`, `Start`, `Health`, `Logs`, `Stop` y `Remove`, con owners por identidad y approvals para operaciones sensibles.
- [x] Exponer el servicio local mediante un proxy host con bind exclusivo a `127.0.0.1`; el contenedor permanece en una red Docker `internal` sin publicar puertos.
- [x] Ejecutar con Docker build/start/health reales y probar una operación Jedi no degradada (`definition`) y una operación fallback etiquetada; negar rutas fuera de allowlist con 404. El owner reintenta el health check de forma acotada.
- [ ] Mostrar un reporte completo y durable de operaciones semánticas con source, duración, truncamiento y métricas agregadas.

**M14-C — Adapter LSP real**

- [x] Implementar inventario sin lanzar servidores y un primer adapter LSP stdio para Pyright `workspace/symbol`; `rust-analyzer` se detecta como no soportado.
- [x] Mantener el root del LSP bajo Bubblewrap y read-only; exigir grant exacto del ejecutable, grant `workspace.files.read` para el root y aprobación de un uso. El bloqueo de red se aplica por seccomp cuando el host impide crear network namespaces.
- [x] Responder solicitudes entrantes soportadas (`workspace/configuration`, registro/capacidad) y rechazar métodos no admitidos con `-32601` para evitar esperas sin respuesta.
- [x] Ejecutar y verificar `initialize` + `workspace/symbol` en un workspace temporal con un símbolo conocido; probar denegación de sockets y escritura.
- [x] Agregar modo compatible para hosts que bloquean network namespaces: mantener filesystem/user/process isolation y denegar sockets/io_uring mediante seccomp antes de ejecutar el servidor.
- [x] Derivar estados del inventario (`sandbox_ready`, `installed_unavailable`, `installed_unsupported`) y mostrar progreso/error del proceso efímero junto con su recibo. Pyright se inicia y cierra por consulta, por lo que no se presenta un estado `running` persistente ni un `configured` sin configuración real.

**Criterios de aceptación:**

- Con Gateway activo, una llamada semántica nativa devuelve resultado real con source/truncation visibles; MCP puede estar apagado y el resultado sigue funcionando.
- Sin `isyco.semantic`, con key inválida, Gateway caído, root no coincidente o recibo no verificable, la operación falla cerrada sin fallback a MCP, shell ni filesystem local.
- Los owners de lifecycle usan Docker simulado en pruebas y ya tienen un witness real de build/start/health y operaciones semánticas; falta instrumentar métricas durables y confirmar el Gateway remoto con grants locales y scope remoto.
- Receta cambiada, ruta symlink, script no reconocido, build fallido, timeout y contenedor ya existente requieren estado visible y no producen una segunda autoridad.
- LSP queda demostrado para Pyright con el testigo temporal `HandshakeWitness`; no hay grants para inspeccionar el workspace activo del usuario ni se marca `rust-analyzer` como adapter.

**No incluye:** ejecución de scripts arbitrarios, montaje writable del repo, herramientas MCP invocadas implícitamente, OAuth propio de ISyCode, ni Docker accesible desde red pública.

### M16 — Producto diario, Settings y superficie de release

**Actualización local 2026-10-01:** sesiones y credenciales ya tienen owners; el bucle ejecuta herramientas tipadas con Authority/Sentinel/aprobaciones. Sesiones, drafts, retry manual, export/import y recuperación provider/model/role/context funcionan. Se añadieron notas acotadas y redactadas de herramientas entre turnos/reinicios, incluyendo resultados no verificados tras una interrupción; no hay replay de efectos ni guardado de razonamiento crudo. El chat mantiene el orden por paso y respeta la lectura del historial. Textual se fija en 1.0.0, la versión validada en Python 3.10/3.12; las capturas históricas 8.2.8 no prueban soporte. Consumo reportado y presupuesto opt-in de chat/resumen disponibles; el presupuesto detiene nuevas peticiones y no garantiza una factura máxima. OAuth de suscripción, rendimiento prolongado y witnesses remotos siguen pendientes. Las descripciones anteriores de milestones son registros históricos y no reemplazan esta evidencia.

**Estado (actualización 2026-09-29):** la cobertura M15 en ISyCode queda cerrada para Secure: cada acción del catálogo tiene owner o DENY explícito; el selector no convierte grants en owners. Esta continuación conectó `ProviderNetworkOwner` a chat, catálogo de modelos, Roundtrip y `/plan`, enlazó digest del material a Authority/Sentinel y guarda recibo durable por respuesta; se quitó el fallback de `/plan` que podía emitir una llamada adicional. Se añadieron witnesses aislados de owners Gateway MCP/semántico, LSP y proveedor, más transporte HTTP same-origin/cross-origin. El workspace del Gateway ahora está vinculado al `.isyroot` por un ID estable no secreto; el contenedor real rechaza HTTP directo, acepta el proxy marcado y el `SemanticGatewayClient` autenticado confirmó que la identidad coincide. `test_workspace_root.py` + `test_gateway_transport_security.py`: 22 passed; `compileall` y `git diff --check` pasan. Sigue NOT_DEMONSTRATED el origen público porque no hay túnel activo, y una operación semántica que atraviese Authority + Sentinel + aprobación: el root activo no tiene todavía un grant local `gateway.semantic.read`. M15 continúa abierto solo por esos witnesses operativos pendientes y la validación/reparación del checker de imports del Gateway; sus límites de cuota siguen siendo por proceso. Capabilities Secure sin owner permanecen DENY.

**Objetivo:** hacer de ISyCode un TUI diario coherente sin convertirlo en framework ni exponer capacidades no autorizadas. Seguir las etapas del compose y actualizar la matriz con evidencia, no con checkboxes heredados.

- [x] A — inventario inicial de superficies y evidencia en `docs/product/tui-feature-matrix.md`.
- [x] A2 — comparación con las CLIs instaladas y brechas priorizadas en `docs/product/cli-competitive-audit.md` (Crush no estaba en PATH; su instalación local no se pudo validar).
- [x] B — superficie Secure de M15 cerrada en ISyCode: owner binding, clasificación exhaustiva, variantes `broker.start`, snapshot, journal/inspector, recibos locales y auditoría AST sin bypass; capacidades sin owner siguen inaccesibles. El perímetro remoto del Gateway queda como dependencia explícita, no como capacidad local declarada segura.
- [ ] C — consolidar configuración no secreta versionada y precedencia.
- [ ] D — navegación/atajos/Help: el mapa del shell ahora sale de `src/isycode/shortcuts.py`; faltan cobertura de atajos modales, rebinds honestos y paleta universal completa.
- [x] E — ciclo local de sesiones: owners create/read/append/delete, export/import por comandos, recuperación provider/model/role/context, retry/drafts y notas acotadas de herramientas. No reanuda efectos ni aprobaciones. Siguen pendientes transferencia por picker y pruebas prolongadas.
- [ ] F parcial — providers/models: owners de credenciales, prueba `/check`, selección provider/model, límite de salida y consumo/presupuesto de chat implementados. Faltan login de suscripción/OAuth, controles de razonamiento completos y validación real de cada proveedor. Una clave presente no equivale a conexión verificada.
- [x] G parcial — Workspace/Context/Files usan grants raíz explícitos y Sentinel; `.isyroot` sigue siendo solo frontera. Faltan otras acciones de Files y UI de metadata bloqueada.
- [ ] H parcial — Gateway/MCP/catálogo requieren host grant local. Gateway MCP tiene invocación manual revisada; el `.isyroot`, el ID derivado y el `GET /v1/workspace/identity` quedaron demostrados contra el contenedor real. Aún falta un semantic query desde ISyCode tras conceder `gateway.semantic.read` y aceptar la aprobación de un uso; no hay túnel público activo. El Sentinel remoto sigue separado.
- [ ] I — Activity, approvals, receipts, diagnostics y logging con redacción.
- [ ] J — opciones avanzadas Mobile Host/Bridge/L1, solo donde exista adapter.
- [ ] K — accesibilidad, tamaños de terminal, rendimiento y reducción de animación.
- [ ] L — release witnesses y matriz reconciliada con comportamiento real.
- [x] Corregir la salida de pseudo tool calls: no tratar JSON `bash` en texto como ejecución y mostrar explícitamente `NOT_EXECUTED`.
- [x] Ejecución local de herramientas tipadas con schema, Authority, Systembilities, Sentinel, aprobación cuando aplique y owner; comandos mediante ejecutable/argumentos en sandbox. Sin fallback a shell arbitrario.

**Gate de Secure:** no declarar la versión segura lista mientras M15 esté pendiente, existan pantallas sin config coherente, una integración parezca runnable sin adapter, o una acción pueda saltarse owner, Authority, Sentinel, aprobación requerida o receipt. Las acciones no implementadas se mantienen DENY aunque exista una grant.

**Fase posterior — Full:** tras cerrar y publicar el perfil Secure, ampliar permisos de manera explícita y por adapter: shell/comandos tipados, escrituras y más integraciones. Cada capability nueva requiere owner concreto, scope/grant visible, clasificación de riesgo, approval apropiada, límites de ejecución y receipt. No habrá un interruptor global que evite Sentinel; Full significa mayor cobertura de acciones concedibles, no menor seguridad.

### Integración opcional: acceso privado por Tailscale

- [x] Inventario local read-only mediante `TailscaleReadOwner`; grant por workspace y ejecutable.
- [x] Instalación automatizada solo en Ubuntu/Debian soportado: preparación de fuente/paquete firmado, staging root-owned y apt exacto, cada fase con confirmación propia. Se ofrece guía manual para el resto.
- [x] Login explícito en navegador oficial: no se reciben ni guardan contraseñas, auth keys u OAuth tokens.
- [x] Serve privado al Mobile Host loopback (`127.0.0.1:8765`) en `/isycode`; health probe al path montado `/isycode/v1/health`; nunca Funnel ni `serve reset`. Configuración Web, TCP y Services ajena a ISyCode se compara antes/después. El cambio en el tailnet real y la sincronización con otro dispositivo siguen NOT_DEMONSTRATED.
- [x] Cada efecto usa Workspace Authority, IsySentinel, approval de un uso y receipt persistente; revocar el grant no borra una ruta automáticamente.
- [x] Witnesses offline de habilitar, verificar y deshabilitar conservan otras rutas; smoke temporal de Settings mostró la opción de instalación sin crear `.isyroot`.
- [ ] Verificar login/instalación en un equipo opt-in y acceso desde otro dispositivo del tailnet; confirmar rechazo desde fuera del tailnet y scopes independientes del Gateway. Estado actual: **NOT_DEMONSTRATED**; no se ejecutaron cambios reales en el equipo.

### M19 — Lenguaje visual de tarjetas y auditorías pendientes

**Origen (2026-10-03):** referencias visuales compartidas por Danny: cajas con
el título sobre el borde de Elia, salida plegable de Gemini y opciones grandes
con foco claro de Crush. Son referencias de diseño, no un port ni pruebas de
sus providers. El resumen de fx fue aportado por Danny (Bridge RESULT 5186);
esta entrega no repitió esa auditoría ni el comando `maintainer check`.

- [x] Comandos del chat agrupados en una tarjeta con **dos filas de salida**.
  El borde lleva el comando; Enter/Espacio o clic en el borde expande y pliega.
  La salida completa retenida y el recibo se consultan al expandir.
- [x] Un comando que alcanza el límite del owner indica que la salida fue
  truncada. La vista compacta no elimina datos ni cambia el resultado del tool.
- [x] La búsqueda encuentra texto fuera de las dos filas y abre la tarjeta.
- [x] Confirmación de comandos con caja interna titulada y opciones grandes;
  Rechazar sigue enfocado inicialmente. Escape/Enter inicial no ejecutan.
- [x] Contadores compactos tipo la caja To-Do de Crush en Multi Harness:
  carpetas y conversaciones separadas. El To-Do de ISyCode se conserva.
- [ ] Reutilizar esos contadores para cambios y resultados, sin inventar
  números ni duplicar paneles de tareas.
- [ ] Extender este lenguaje a selección de modelo y configuración: secciones
  con título sobre el borde, opciones en tarjetas y ayudas breves. Evitar
  convertir todas las respuestas del agente en cajas de altura fija.
- [ ] Diálogos de permisos inspirados en la última captura de Crush:
  herramienta/operación y ruta o destino visibles, argumentos en caja propia,
  botones de una vez/cancelar y alcance explícito. Una opción de sesión solo
  aparece si el owner ya soporta ese contrato; el estilo no crea un grant.
- [ ] Unificar tarjetas de otras tools, estados pendientes/error y resultados
  paginados. La ejecución continúa teniendo el mismo owner y el mismo recibo.
- [ ] Recuperar estas tarjetas al reabrir una sesión a partir de los resultados
  existentes; la entrega actual agrupa comandos nuevos de la TUI.

**fx como complemento del roadmap:** revisar doctor/status JSON y checks
componibles sobre el CLI existente; inspección/resume/fork de sesiones en M7/M16;
delegación en el owner existente; estado MCP en M3/M14; ACP como adapter por
diseñar; referencias paginadas para resultados grandes. Para ISyCo Console,
extender Passport/Inbox/Memory/Session/Locks/Events/Scheduler en su propio
roadmap. No crear paquetes paralelos aquí ni marcar estos ítems como completos
por la presencia de otra CLI. Deny explícito prevalece en todos los casos.

**Validación visual:** 80×24 y 120×40, títulos largos, salida con líneas anchas,
expansión por teclado, búsqueda, estado final y foco de rechazo. La vista previa
usa datos de demostración y no acredita comandos ni servicios reales.

## 5. Orden y puertas de dependencia

```text
M0 contrato/ADR/startup
  → M1 shell visual
  → M2 file browser read-only
  → M3 MCP + Skills reales
  → M15 ISySentinel + Workspace Authority
  → M4 runtime adapters (IsyMotron opcional)
  → M5 approvals/receipts ───────┐
  → M7 persistencia/resume        ├→ M6 acciones con grants
  → M8 Bridge (opcional)          │
  → M9 L1 (opcional, después de M15/M6)
  → M10 navegador semántico CLI (paralelo a M1–M3; solo enlaza capacidades existentes)
  → M11 providers + Roundtrip (providers requieren adapter configurado; review no autoriza acciones)
  → M13 Mobile Host substrate (sesiones requieren adapters y gates M15/M6)
  → M14 Gateway/LSP/broker (Gateway requiere gates local/remoto; Docker usa execution owner tipado)
  → M16 daily-driver product completion + release witnesses
```

M15 es prerequisite de toda acción con efectos: M6 no habilita escrituras hasta conectar Authority, Sentinel y execution owners. M14 puede avanzar en la interfaz read-only, pero sus llamadas remotas necesitan ambos gates (ISySentinel local y Gateway HTTP Sentinel remoto). No se implementa delete/shell como atajo para completar una demo. M8/M9 son extras; no retrasan el valor single-agent de M1–M7.

## 6. Pruebas de producto y calidad

Cada milestone trae pruebas unitarias y de integración para su contrato; no se cierra un milestone por apariencia o porque “arrancó”. Las suites reales se ejecutan en el repo dueño de cada componente y con evidencia guardada en ISyCode. No reutilizar resultados de tests de un checkout modificado como si fueran baseline limpio.

### UX y layout

- Capturas terminales de inicio/chat/plan/Files/Overview y todos los estados de conexión para 80×24, 100×30, 140×40.
- Test de foco teclado en input, rail, selector, modal, preview y retorno al chat.
- Texto en español/Unicode, nombres de archivo largos, wrap, scroll y terminal sin color.
- Chat conserva al menos 68% de ancho a 140 columnas; rail no corta status ni ruta; estado no se comunica solo con color.
- Entrada enviada durante operación aparece en cola o permanece editable; nunca desaparece silenciosamente.

### Integridad y seguridad

- Resolver root una sola vez y probar espacios, symlink, traversal, path absoluto, nombre Unicode, `.git`, `.env`, ignored y archivos gigantes.
- Por cada side effect contar: request, grant, decision, lease, host execution, receipt y verify status. Toda discrepancia bloquea el gate.
- Fallar el Gateway, MCP, Bridge, provider y receipt verifier uno por uno. Un servicio caído no debe ensanchar authority ni disparar otro executor.
- Pruebas de UI aseguran que confirmación no puede dispararse desde el input y que el digest mostrado es el digest ejecutado.
- No ejecutar destructivos contra el repo de usuario en pruebas; solo fixtures temporales/hosts simulados.

## 7. Registro de riesgos

| Riesgo | Mitigación | Gate |
|---|---|---|
| Acoplar ISyCode a internals TS/Bun inestables | MCP/HTTP/CLI con versión; ADR M0 | Spike/ADR aprobado |
| Root del Gateway diferente al directorio de lanzamiento | Identificar root y mostrarlo; roots separados | Fixture root igual/diferente M6 |
| Plan viejo ejecutado por una confirmación nueva | Invalidar en cada transición y ligar digest | Rechazo/cancelación M0 + M5 |
| UI dice “allow” sin recibo verificable | Estados explícitos; ejecutar verificador IsyMotron | Witness receipt M5 |
| Sidebar oculta funciones en terminal pequeña | Breakpoints, Ctrl+B y capturas | M1 layout suite |
| El tree filtra secretos o sale del workspace por symlink | Resolver en host, denylist, no seguir enlaces externos | M2 containment suite |
| OpenISy/IsyVM checkout dirty cambia mientras se integra | Leer solo; revisar diff/contrato al iniciar implementación | Gate M0 por repo |
| Gateway caído induce fallback a filesystem/shell | No fallback; DENY de mutación | Witness degradado M5/M6 |
| L1 `ACTIVE` se confunde con permiso de uso | Presentar estados separados y grant independiente | Witness L1 M9 |
| IsyVM Layer A se toma por sandbox de seguridad | Reutilizar solo referencias UI; IsyMotron gobierna authority | Revisión de frontera M0/M5 |

## 8. Fuera de alcance de la primera versión

- Replicar toda la TUI TypeScript de OpenISy/OpenCode dentro de Python.
- Editor/diff viewer permanente en el panel lateral.
- Terminal shell con privilegios implícitos, `sudo`, delete/chmod o ejecución arbitraria.
- Exponer reasoning interno del modelo como característica de producto por defecto.
- Activar capacidades por confianza en un provider, por una skill o por presencia de un MCP.
- Prometer seguridad de una sandbox IsyVM Layer A.

## 9. Checklist de release inicial

- [ ] M0 ADR y punto de entrada instalable completados.
- [ ] M1 capturas y contratos de layout aprobados.
- [ ] M2 file browser permanece confinado al `cwd` y soporta preview read-only.
- [ ] M3 MCP/Skills reflejan estados reales de OpenISy.
- [ ] M4 ejecución demo pasa por IsyMotron, no por widgets.
- [ ] M5 todos los witnesses de autoridad/receipt/degraded mode pasan.
- [ ] M6 solo habilita mutaciones con los scopes y grants de ambos lados.
- [ ] M7 recuperación no repite side effects ni revive approvals vencidas.
- [ ] M13 solo se declara completo después de adapters reales, sesiones/stream, cancelación, approvals, gestión de credenciales y migración móvil versionada.
- [x] README muestra instalación, configuración, atajos, roots y modo demo.
- [ ] No hay rutas absolutas personales, credenciales en logs, MCPs/skills ficticios ni claims `DEMONSTRATED` sin evidencia reproducible.

## Referencias locales auditadas

- ISyCode: `src/isycode/tui.py`, `src/isycode/gateway_client.py`, `src/isycode/safety.py`, `src/isycode/session.py`, `src/isycode/bridge.py`.
- IsyMotron: `agents/provider.py`, `agents/planner.py`, `agents/executor.py`, `core/isymotron/policy.py`, `core/isymotron/host.py`, `core/isymotron/verify.py`, `hosts/linux/host.py`, `hosts/simulator/engines.py`.
- OpenISy: `packages/opencode/src/mcp/index.ts`, `src/skill/index.ts`, `src/cli/cmd/tui.ts`, `src/l1/` (checkout separado).
- Gateway/Bridge: `gateway/app.py`, `gateway/paths.py`, `gateway/auth.py`, `bridge_core/capabilities/cap.agent_bridge/handshake.py` (componentes separados).
- IsyVM: `core/agent/chat.py`, `ui/panels/workspace.py`, `ui/main_window.py`, `tests/test_ui_layout.py` (prototipo separado).
