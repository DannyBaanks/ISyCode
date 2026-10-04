# ISyCode: interacción visual y controles (2026-10-03)

## Uso

- `/model` o `/models`: proveedores desplegables, búsqueda y nombres legibles; los IDs se muestran en el selector. Después se elige reasoning según metadata del catálogo o compatibilidad documentada. Opciones desconocidas no se inventan. La selección de reasoning es de esta sesión.
- Enter envía; durante una tarea agrega a la cola FIFO. Ctrl+Enter dirige el turno activo: interrumpe la petición y prepara una nueva petición autorizada; una herramienta que ya comenzó termina antes. Ctrl+J/Shift+Enter inserta una línea. El compositor crece hasta cinco líneas y después hace scroll.
- `/queue` revisa y elimina mensajes pendientes; `/queue clear` vacía la cola. Un error no provoca reenvío automático. La cola es de esta ejecución.
- Ctrl+Shift+Enter captura una idea sin enviarla al modelo. `/ideas` abre el backlog para revisar, descartar o promover explícitamente a la cola. Al terminar se anuncia el número de ideas. El backlog es de esta ejecución. No se impone un bloqueo automático de steer por frecuencia.
- Click para enfocar una caja; Enter/Space expande o retrae. Thinking permite ocultar todo con su triángulo, mostrando una vista previa en el título. Hasta dos líneas se muestran completas; textos mayores se previsualizan. La cinta de texto es opcional por caja y desde Settings.
- IdeaBox conserva sus dimensiones y abre la nota completa con Enter/Space. Su encabezado identifica modelo, reasoning y proveedor.
- Herramientas usan colores constantes por operación, además de texto e iconos. Llamadas consecutivas de la misma operación se agrupan como ramas sin quitar sus recibos.
- Ctrl+V pega texto o imágenes desde el portapapeles Linux mediante un owner y autorización. Pegados largos se representan con las primeras veinte letras; el envío conserva el contenido completo. Ctrl+P permite revisar y retirar adjuntos. Las imágenes requieren capacidad de visión verificada y son de esta sesión; no se persisten sus bytes.
- Settings permite desactivar sonidos. Se usan ritmos del bell del terminal: final, aprobación, pregunta, advertencia y error. El terminal debe tener bell audible habilitado; no son tonos nativos diferentes. Audio audible en GNOME: NOT_DEMONSTRATED.
- Subagent agrupa por proveedor. Un fallo clasificado vuelve al selector con diagnóstico; exige otra selección/Launch. Los efectos ya realizados permanecen y se explican. Denegaciones de Authority no se convierten en reintentos que eludan permisos.
- Sessions muestra lista compacta, filtros reales Working/Needs input/Idle y detalles del elemento seleccionado. En anchos menores a 85 columnas del panel oculta los detalles. No interpreta sesiones guardadas como agentes remotos activos. El modelo proviene del estado guardado si existe.
- Multi Harness → Gap map → una opción → Prepare repair Compose: muestra la propuesta completa; Copy reviewed Compose usa el owner del portapapeles. No aplica cambios al harness ni concede permisos. La huella identifica evidencia y NO es una capability. Un agente externo no puede quedar restringido por una cadena en su prompt: los efectos deben pasar por owners y autorizaciones del runtime. Emisión y consumo de una capability específica de reparación entre agentes: NOT_DEMONSTRATED, no implementada por este Compose. Las opciones DO_NOT_MERGE proponen únicamente revisión nativa, sin copiar permisos ajenos.

El agente dispone de `update_session_title`: puede proponer títulos durante los primeros cinco mensajes de usuario. El owner valida la ventana y conserva renombres manuales. Es una instrucción al modelo, no una garantía de que todos los proveedores llamen la herramienta. La identidad estable de sesión permanece igual; no se agregó transferencia de leases por título.

## Diagnóstico y límites

Los errores clasifican credenciales, cuota/saldo, rate limit, modelo, endpoint, red, proveedor y stream usando señales disponibles; no se adivina saldo a partir de todo HTTP 429 ni modelo inválido a partir de todo 404. Se ocultan cuerpos arbitrarios y secretos. Sin código suficiente, el diagnóstico permanece general. Pruebas de proveedores reales con cobro: NOT_DEMONSTRATED.

NIM Nemotron Ultra expone on/off de thinking; no se inventan low/medium/high para ese modelo. Compatibilidad se consulta por modelo, no solo proveedor. Fuentes: [NVIDIA Ultra](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-ultra-550b-a55b), [NVIDIA thinking](https://docs.nvidia.com/nim/large-language-models/1.15.0/thinking-budget-control.html), [OpenAI modelo](https://developers.openai.com/api/docs/models/gpt-6-luna), [Anthropic effort](https://platform.claude.com/docs/en/build-with-claude/effort), [Anthropic vision](https://platform.claude.com/docs/en/build-with-claude/vision).

## Verificación

Antes de las últimas adiciones de Compose/backlog/Sessions: suite completa 1291 passed, 6 skipped, 8 warnings. Registro `/tmp/isycode-ui-complete-suite.log`. Las nuevas superficies se verifican con `test_harness_compose`, `test_idea_backlog`, `test_work_list`, tests de harness y cobertura Authority. El registro final y su SHA-256 se añaden al cerrar la verificación. No se reutilizaron capturas de procesos anteriores como prueba del nuevo código.

Se preservan cambios ajenos en ROADMAP y auditorías anteriores. Ningún archivo eliminado. Authority, Sentinel y recibos siguen siendo el límite de ejecución; roles, skills y prompts no conceden autoridad.

Verificación completa final: **1296 passed, 6 skipped, 8 warnings en 219.73s**. Comando: `PYTHONPATH=src pytest -q -p no:cacheprovider --tb=short`. Registro preservado: `docs/handoff/visual-interaction-2026-10-03-tests.log`. SHA-256: `72c4eb9671a9f92618ba924e293e4b63882fcdb0c3468c2554c05b4140949fb2`. Después se corrigieron únicamente nombres legibles de modelo/proveedor y rechazo de controles en títulos, verificados con pruebas específicas.

Sessions: primer clic previsualiza, segundo clic en la misma fila abre. Flechas seleccionan y actualizan detalles; Enter abre. Al abrir Sessions se enfoca la lista.

Verificación del ajuste final de navegación: 27 passed en 14.87s (`test_work_list` y `test_action_coverage`).

Corrección posterior: Enter/Space en Thinking recorre título de una línea → vista previa de hasta dos líneas → texto completo → título de una línea. Textos cortos alternan entre título y contenido completo. El triángulo conserva ocultar/mostrar y la cinta opcional sigue separada.

Regresión Thinking verificada: 29 passed en 22.65s (`test_focused_box_expansion`, `test_chat_sequence`, `test_action_coverage`).
