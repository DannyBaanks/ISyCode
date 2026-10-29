# Auditoría E2E local de ISyCode — 11 de octubre de 2026

El ciclo local de programación funciona, pero la interfaz todavía tiene fallos que afectan decisiones y navegación. Se confirmaron **6 hallazgos: 2 P1 y 4 P2**. El más importante es que la cabecera puede mostrar **Security mientras la política efectiva es Classic**. No se demostró un bypass de IsySentinel: se demostró información de estado incorrecta en la UI.

**Referencia auditada:** `/home/danny/Development/ISyCo Git/ISyCode`, commit `c9bb088533694959dc2d5924612fc4a217c610bd`, Python 3.12.3, Textual 8.2.8, Ubuntu. La suite empezó a las 03:39 del 11 de octubre, hora de Ciudad de México. El directorio `2026-10-11-e2e-1830` es un identificador de corrida, no su hora.

**Alcance:** auditoría de comportamiento y UI/UX de la TUI local. Se usaron workspaces, HOME y directorios de estado aislados. La inferencia fue determinista y simulada; la aplicación, Authority, Sentinel, owners, sesiones, Git, archivos y sandbox de comandos fueron reales. No se modificó código del producto ni configuración de tus cuentas. Las capturas son exportaciones originales de Textual rasterizadas localmente; no son capturas de una terminal física.

## Validación ejecutada

| Verificación | Resultado observado | Evidencia |
| --- | --- | --- |
| Suite establecida en CONTRIBUTING y CI: `pytest -q -m 'not integration'` | 1,875 aprobadas; 3 omitidas; 11 excluidas; exit 0 | [salida completa](suite.log), [JUnit](suite.xml), [comando y entorno](suite-command.json) |
| E2E local con Bubblewrap real: lectura → edición aprobada → unittest → diff | 1 aprobada; exit 0 | [salida](real-sandbox.log), [comando](real-sandbox-command.json) |
| Recorrido interactivo equivalente | Archivo pasó de `value = 1` a `value = 2`; unittest exit 0; diff llegó al modelo simulado; 5 llamadas del fixture | capturas 10–13, [llamadas del fixture](classic-provider-calls.json) |
| Ayuda y versión mediante el launcher | Ambos exit 0; versión 0.1.0 | [salidas y comandos](cli-smoke.json) |
| Cadenas de journals de los 3 fixtures principales | PASS, sin registros no verificables | archivos `fixture-verification-*.json` y `raw-journal-*.jsonl` |
| Comprobación de los hallazgos contra estados y eventos capturados | Todos los testigos confirmados | [verificador](verify_evidence.py), [resultado](evidence-verification.json) |

La suite completa no detectó estos fallos de experiencia. Su aprobación demuestra la cobertura que ejecuta, no que todos los controles sean visibles, que el foco esté en un elemento utilizable o que el estado mostrado coincida con la política.

## Hallazgos priorizados

### F1 — P1: la cabecera conserva el modo anterior después de cambiar permisos

**Reproducir:** abrir en Security → Configuración → Authority & Security → Modo → Classic → confirmar el cambio → rechazar la confianza automática opcional → cerrar menús. La política devuelve `classic`, pero la cabecera conserva `● Security`. Un mensaje atraviesa el gate del provider en Classic y llega al fixture de inferencia mientras la cabecera sigue diciendo Security. En el cambio inverso, Security bloqueó el envío y la cabecera conservó Classic.

**Esperado:** el indicador de modo se actualiza después de guardar la política, antes de devolver el control al usuario. **Impacto:** el usuario interpreta sus permisos a partir de un estado incorrecto. No es evidencia de evasión de permisos; el backend sí aplicó la política efectiva.

**Evidencia:** capturas 24–26 y sus JSON: `24-security-blocked-chat.json`, `25-classic-shown-as-security.json`, `26-chat-allowed-with-security-banner.json`. El fixture de Security→Classic registró una llamada autorizada al provider simulado.

**Causa localizada:** [_change_workspace_mode](</home/danny/Development/ISyCo Git/ISyCode/src/isycode/tui_app_authority.py:122>) llama a `_update_workspace_identity_ui`, que actualiza etiquetas de la barra lateral pero no repinta Banner. [_update_workspace_identity_ui](</home/danny/Development/ISyCo Git/ISyCode/src/isycode/tui.py:835>). El Banner obtiene el modo vigente al llamar `set_compact`; resize o abrir/cerrar el rail lo refrescan posteriormente.

**Corrección recomendada:** repintar el indicador desde la política recién guardada; verificar las dos direcciones del cambio sin resize y sin abrir otro panel.

### F2 — P1: F6 oculta Configuración en 80×24

**Reproducir:** terminal 80×24, idioma español, barra lateral cerrada → F6 → intentar pulsar el engranaje. El área del chat mide 52 columnas, pero el engranaje se coloca en `x=62`, fuera de esa área. El clic no abre Configuración; el foco sigue en el árbol. El selector de modelo también queda cortado. Abrir con Ctrl+B o redimensionar sigue una ruta distinta que oculta el botón de modelo y permite acceder al engranaje.

**Impacto:** un atajo principal de archivos deja inaccesible por ratón el acceso a configuración y permisos. **Esperado:** todos los caminos que muestran el rail aplican el mismo ajuste de la barra inferior.

**Evidencia:** capturas 06 y 16, estado de widgets y evento del clic en `classic-events.jsonl`; `main=(0,1,52,23)`, `settings-button=(62,23,5,1)`.

**Causa localizada:** [_set_rail_view](</home/danny/Development/ISyCo Git/ISyCode/src/isycode/tui_app_rail.py:590>) muestra el rail sin programar `_update_model_button_visibility`, que sí se usa en Ctrl+B y resize. **Corrección recomendada:** centralizar el ajuste de controles para todos los caminos de apertura. Verificar visibilidad efectiva y clic, no solo `display=True`.

### F3 — P2: Nueva conversación pierde el foco del editor

**Reproducir:** completar un turno → Sesiones → `+ Nueva conversación` → escribir `abc`. El chat nuevo aparece, pero el foco pasa a `work-refresh`, un botón cuyo rectángulo es `(0,0,0,0)`. El editor no recibe los caracteres. Se reprodujo nuevamente desde otro chat; Ctrl+L recupera el foco.

**Esperado:** tras crear/abrir el chat, el editor visible recibe el foco. **Impacto:** la acción parece funcionar, pero la siguiente interacción natural falla silenciosamente.

**Evidencia:** captura 15, su JSON y eventos de `press a,b,c`. **Causa localizada:** [_start_new_conversation](</home/danny/Development/ISyCo Git/ISyCode/src/isycode/tui_app_sessions.py:811>) y `_show_lane` restauran contenido y visibilidad sin enfocar el editor después de ocultar WorkList. **Corrección recomendada:** transferir el foco después del cambio de layout, en todas las rutas de retorno al chat.

### F4 — P2: onboarding sin límite de altura

**Reproducir:** primer arranque, español, 80×24 → configuración personalizada → espacio recurrente → elegir modo. La tarjeta de modo mide 27 filas en una pantalla de 24. La bienvenida mide 26. El borde inferior y parte de la zona de opciones se recortan. En esta corrida las dos etiquetas de modo todavía se alcanzan a leer: no se afirma que Security sea imposible de elegir. Esc sí seleccionó Security.

**Impacto:** una decisión de permisos aparece pegada al límite de la pantalla, sin margen para textos o rutas más largos. **Esperado:** explicación desplazable con opciones siempre visibles y un máximo de altura.

**Evidencia:** capturas 03–05 y regiones JSON. **Causa localizada:** [QuickStartScreen](</home/danny/Development/ISyCo Git/ISyCode/src/isycode/tui_screens_grants.py:125>) y [WorkspaceModeScreen](</home/danny/Development/ISyCo Git/ISyCode/src/isycode/tui_screens_grants.py:173>) usan `height:auto` sin limitar ni desplazar el cuerpo. **Corrección recomendada:** limitar la tarjeta y reservar espacio para las opciones; probar texto español, rutas largas y alturas pequeñas.

### F5 — P2: la vista previa del rail queda reducida a una línea

**Reproducir:** 80×24 → Archivos → seleccionar `src/helper.py`. La lectura funciona y genera receipt. El estado contiene el código completo, pero el contenedor de preview ocupa `y=20..27` dentro de un Files view que termina en `y=22`. Solo se ve la primera línea de metadata: el código y el receipt quedan fuera de la región visible del padre.

**Impacto:** el usuario no puede inspeccionar el archivo ni el resultado de lectura en el rail. **Control positivo:** `Abrir vista previa` sí abre un modal completo y legible; captura 18.

**Evidencia:** capturas 17–18 y JSON. **Causa localizada:** [layout de archivos](</home/danny/Development/ISyCo Git/ISyCode/src/isycode/isycode.tcss:88>): el árbol tiene mínimo 6 filas, el preview altura 7, y los demás controles consumen el resto. **Corrección recomendada:** asignar alturas adaptativas o dar a los archivos un panel desplazable; preservar al menos un área útil de lectura.

### F6 — P2: textos críticos sin traducir y traducción que se pierde al repintar

Con español seleccionado, el resumen de edición, los riesgos del comando, el cambio de modo, la recuperación de error y la vista de sesiones aparecen parcial o totalmente en inglés. La Caja de ideas arranca traducida y después de un turno pasa a `Idea box / Capture an idea`. Esto excede nombres de producto que deliberadamente permanecen sin traducir.

**Impacto:** instrucciones de aprobación, irreversibilidad y recuperación pueden no ser comprendidas por el usuario que eligió español. **Evidencia:** capturas 10–12, 14, 18–22, 24–26.

**Causas localizadas:** [resumen de escritura](</home/danny/Development/ISyCo Git/ISyCode/src/isycode/tui_screens_approval.py:216>), [consentimiento de comando](</home/danny/Development/ISyCo Git/ISyCode/src/isycode/tui_screens_approval.py:343>), [cambio de modo](</home/danny/Development/ISyCo Git/ISyCode/src/isycode/tui_app_authority.py:101>) y [repintado de IdeaBox](</home/danny/Development/ISyCo Git/ISyCode/src/isycode/tui_app_sessions.py:312>) contienen texto literal sin `tr`.

**Corrección recomendada:** cubrir primero consentimientos y errores, luego estados dinámicos. Comprobar el idioma después de turnos, cambios de conversación y switches de modo; la traducción del primer render no cubre esos estados.

## Recorrido y salud por paso

| Paso | Recorrido | Salud | Capturas |
| --- | --- | --- | --- |
| 1 | Bienvenida y configuración personalizada | Con recorte de altura | 03 |
| 2 | Elegir espacio recurrente | Funcional; información clara | 04 |
| 3 | Elegir modo; Esc selecciona Security | Funcional, tarjeta recortada | 05 |
| 4 | Intentar listar archivos sin grant en Security | Denegado como corresponde; mensaje del rail recortado | 06 |
| 5 | Overview Classic, configuración y búsqueda de Authority | Funcional; navegación y filtro útiles | 07–09 |
| 6 | Leer y proponer edición; revisar/aprobar cambio | Funcional; rechazo enfocado por defecto; idioma incompleto | 10–11 |
| 7 | Revisar y ejecutar unittest en sandbox real | Funcional; comando exacto, exit 0; idioma incompleto | 12–13 |
| 8 | Sesiones, selección y conversación nueva | Lista y detalles funcionan; nuevo chat pierde foco | 14–15 |
| 9 | F6, archivo y preview ampliado | Rail y barra inferior fallan en 80×24; modal completo funciona | 16–18 |
| 10 | Streaming lento y cola de otro mensaje | Funcional en el fixture | 19 |
| 11 | Cancelar con borrador nuevo | Borrador y cola preservados; la advertencia aclara que el parcial no se guardó | 20 |
| 12 | Error HTTP 401 | Original recuperado; no se reenvía automáticamente; texto inglés | 21 |
| 13 | Classic→Security y nuevo intento de chat | Política aplicada; ninguna llamada adicional al provider; cabecera incorrecta | 22–24 |
| 14 | Security→Classic y chat | Política Classic aplicada; inferencia simulada alcanzada; cabecera incorrecta | 25–26 |

## UI/UX y accesibilidad

Fortalezas observadas: personalidad visual consistente del paisaje y el gato; filtro de configuración útil; diff previo a editar; comando exacto antes de ejecutarlo; rechazo como foco inicial en consentimientos; estado ON/OFF escrito además del color; recuperación del prompt y conservación de borradores.

Los problemas de foco, recorte y estado afectan uso con teclado, baja visión y comprensión de permisos. No se certifica WCAG ni soporte de lector de pantalla. Los colores de una terminal física dependen de su fuente, tamaño y configuración. Como riesgo adicional, los controles inferiores usan `#9b5de5` sobre `#1e1e1e` en la exportación, aproximadamente 4.04:1. Eso queda por debajo de la referencia 4.5:1 para texto normal, aunque el SVG exporta texto de 20px en negrita; por ello no se cuenta como incumplimiento confirmado. Conviene verificar tamaños reales y fondos reales, además del modo opcional de alto contraste.

Oportunidades de diseño: reducir el texto inicial manteniendo un detalle expandible; hacer visibles los siguientes pasos de recuperación; aprovechar espacio libre para identificar el modelo sin reducir siempre el nombre a ocho columnas. Son mejoras propuestas, no fallos funcionales adicionales confirmados.

## Límites y NOT_DEMONSTRATED

- Inferencia real, OAuth y catálogos de cuentas de OpenAI/ChatGPT, Anthropic, Gateway y otros providers: NOT_DEMONSTRATED. El fixture sustituyó inferencia y suprimió las sondas opcionales de arranque. `Checking the configured model` en capturas no es prueba de una sonda colgada.
- MCP remoto/local conectado, Mobile Host, Bridge de la aplicación, Tailscale, sincronización entre equipos y despliegues: NOT_DEMONSTRATED en esta corrida. La suite local cubre contratos; no sustituye conexiones reales.
- Copia de portapapeles contra el escritorio, selector nativo, lector de pantalla, terminal física, otros sistemas operativos y paquetes publicados: NOT_DEMONSTRATED.
- El E2E con comando real es local. No prueba sandbox en todas las distribuciones ni todas las clases de comando.
- La respuesta del fixture es texto prefijado; no debe interpretarse como juicio del modelo sobre la corrección del cambio. La corrección del ejemplo se comprobó con unittest y el diff real.
- No se corrigieron los hallazgos. El siguiente trabajo recomendado es F1 y F2, seguido de F3 y los layouts estrechos.

## Evidencia y reproducción

`audit_driver.py` arranca la TUI real con HOME/estado y proyecto aislados, recibe acciones JSON y guarda SVG, PNG, estado de widgets y eventos. `render_svg.py` rasteriza el SVG original mediante librsvg/cairo sin red. `verify_evidence.py` comprueba testigos guardados; no es una nueva prueba de producto. Los comandos de la suite y del sandbox están guardados como argv exactos.

La captura 01 se rechazó porque ImageMagick generó un PNG vacío; su SVG se preservó. La 02 se rasterizó correctamente con librsvg como ensayo monocromo, pero no se usa como paso adicional. Las capturas 03–06 son monocromas porque el proceso inicial heredó `NO_COLOR=1`; son válidas para layout y comportamiento, no para evaluar la paleta. Las 07–26 se capturaron con `TERM=xterm-256color`, `COLORTERM=truecolor` y sin NO_COLOR. Todas las usadas se abrieron e inspeccionaron. Los controles decorativos de ventana son parte del exportador Rich, no del producto.

El commit del producto se mantuvo durante toda la corrida y el diff de sus archivos rastreados quedó vacío. Los hashes de fuente están en `source-SHA256SUMS.txt`; los del informe y evidencia en `SHA256SUMS.txt`. Se preservaron journals crudos, negativos y estados capturados. Solo se añadió esta carpeta de auditoría; no se borró ni movió contenido existente.

## Capturas inspeccionadas, en orden

### Captura 03 — Bienvenida en 80×24

F4: la tarjeta mide 26 filas; el borde inferior se recorta. Captura monocroma.

![Bienvenida en 80×24](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/03-first-run-narrow.png>)

### Captura 04 — Espacio recurrente

La elección funciona y explica .isyroot. Captura monocroma.

![Espacio recurrente](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/04-recurrence.png>)

### Captura 05 — Elegir modo

F4: 27 filas en un terminal de 24; Esc sí seleccionó Security. Captura monocroma.

![Elegir modo](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/05-mode-narrow.png>)

### Captura 06 — Archivos sin grant

Listado denegado en Security; el rail recorta el mensaje. Captura monocroma.

![Archivos sin grant](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/06-security-files.png>)

### Captura 07 — Overview Classic

Paisaje, compositor y estados en 140×40. La sonda de modelo se suprimió en el fixture.

![Overview Classic](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/07-classic-overview-140x40.png>)

### Captura 08 — Configuración

El filtro y agrupación permiten encontrar Authority.

![Configuración](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/08-settings.png>)

### Captura 09 — Permisos en Classic

ON/OFF se comunica con texto y color; estados de las integraciones diferenciados.

![Permisos en Classic](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/09-authority-classic.png>)

### Captura 10 — Aprobar edición

Diff real y rechazo enfocado por defecto. F6: resumen sin traducir.

![Aprobar edición](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/10-edit-approval.png>)

### Captura 11 — Aprobación estrecha

El diff y acción principal caben; la etiqueta de confianza se parte y pierde su atajo visible.

![Aprobación estrecha](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/11-edit-approval-80x24.png>)

### Captura 12 — Consentimiento de comando

Comando exacto y riesgos antes de ejecutar. F6: título y explicación en inglés.

![Consentimiento de comando](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/12-command-approval.png>)

### Captura 13 — E2E local completado

Lectura, edición, unittest con exit 0 y diff real; inferencia simulada. F6: IdeaBox perdió su traducción.

![E2E local completado](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/13-chat-complete.png>)

### Captura 14 — Lista de sesiones

Selección y detalle legibles en 140×40; F6: varios estados sin traducir.

![Lista de sesiones](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/14-sessions.png>)

### Captura 15 — Conversación nueva

F3: el foco está en work-refresh oculto; abc no aparece en el editor.

![Conversación nueva](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/15-new-chat-lost-focus.png>)

### Captura 16 — F6 y barra inferior

F2: el engranaje queda fuera del área principal y no se abre con clic.

![F6 y barra inferior](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/16-files-80x24-settings-hidden.png>)

### Captura 17 — Lectura en el rail

F5: el archivo se leyó, pero solo aparece metadata; código y receipt están recortados.

![Lectura en el rail](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/17-file-preview-clipped.png>)

### Captura 18 — Vista ampliada

Control positivo: el modal sí muestra el código; lectura y cierre funcionales.

![Vista ampliada](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/18-full-file-preview.png>)

### Captura 19 — Streaming y cola

El segundo mensaje queda en cola mientras el primero sigue pendiente en el fixture.

![Streaming y cola](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/19-live-queue.png>)

### Captura 20 — Cancelación

Borrador nuevo y cola preservados; el parcial no se agregó a historial. F6: explicación en inglés.

![Cancelación](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/20-cancel-keeps-draft.png>)

### Captura 21 — HTTP 401 simulado

Original restaurado, sin reenvío automático. F6: diagnóstico y recuperación en inglés.

![HTTP 401 simulado](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/21-provider-error-recovery.png>)

### Captura 22 — Cambiar a Security

Confirmación explícita con cancelar como foco inicial. F6: consentimiento sin traducir.

![Cambiar a Security](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/22-security-switch-confirm.png>)

### Captura 23 — Authority en Security

Modo y política cambiados; los OFF constan en el JSON. En 80×24 el menú requiere desplazarse.

![Authority en Security](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/23-security-grants-off.png>)

### Captura 24 — Security deniega

No hubo llamada adicional al fixture; prompt preservado. F1: cabecera conserva Classic.

![Security deniega](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/24-security-blocked-chat.png>)

### Captura 25 — Cambiar de Security a Classic

F1: texto informa Classic y política classic, pero cabecera continúa Security.

![Cambiar de Security a Classic](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/25-classic-shown-as-security.png>)

### Captura 26 — Chat con indicador desactualizado

F1: una solicitud autorizada en Classic llega al fixture mientras el indicador dice Security.

![Chat con indicador desactualizado](</home/danny/Development/ISyCo Git/ISyCode/docs/audits/2026-10-11-e2e-1830/26-chat-allowed-with-security-banner.png>)

