# ISyCode — coherencia de menús y copia de texto

Fecha: 2026-10-11. Estado: exploración visual solicitada; dirección pendiente de selección. Este documento amplía los seis hallazgos de `docs/audits/2026-10-11-e2e-1830/AUDITORIA.md`. No implementa ni da por corregidos esos fallos.

## Objetivo solicitado

Unificar el estilo de sidebar, Settings y todas las familias de cajas y menús. Tomar el alto contraste de las referencias del usuario como base: texto legible, fondos oscuros simples y bordes consistentes. Settings es la prioridad visual. Mantener la identidad de la TUI y el paisaje y gato del chat para la futura composición; esta fase contiene únicamente los menús aislados.

Entregar tres propuestas independientes, una imagen completa por propuesta con todas las familias representadas. El usuario elegirá una; después se compondrán los menús elegidos sobre su pantalla real para revisar encaje. La composición posterior y la implementación no forman parte de esta entrega inicial.

## Interacción añadida al plan

| Gesto | Comportamiento propuesto |
| --- | --- |
| Clic simple en una caja de contenido | Enfoca; no expande ni copia. |
| Space sobre una caja enfocada | Expande o contrae. Es el único gesto de expansión de las cajas de contenido. |
| Space dentro de un campo editable | Inserta un espacio; no captura la expansión del contenedor. |
| Doble clic en una caja de texto | Abre un menú de copia. No expande ni escribe directamente al portapapeles. |
| `Copiar caja completa` en ese menú | Copia el texto de esa caja después de la elección explícita del usuario. |
| Arrastrar el ratón sobre texto | Marca un rango visible; no expande ni dispara copia de la caja completa. |
| `Copiar selección` o Ctrl+C con selección | Copia solamente los caracteres marcados, aunque sean un fragmento de una línea o dos líneas. No añade el resto de la caja. |
| Escape en menú de copia | Cierra sin copiar y conserva selección/foco utilizables. |

La selección parcial y la copia de caja completa son acciones distintas y deben tener etiquetas distintas. Sin selección, `Copiar selección` queda deshabilitado: nunca se sustituye silenciosamente por copiar todo. El menú puede indicar `2 líneas seleccionadas` y mostrar el fragmento que se copiará. El gesto de doble clic se desambigua del arrastre antes de abrir el menú. Enter mantiene la activación de botones y opciones; deja de expandir las cajas de contenido.

La copia conserva exactamente el rango del contenido textual: Unicode, espacios, tabulaciones y saltos de línea seleccionados. No agrega títulos, bordes, números de línea ni escapes ANSI. El rango debe corresponder a lo que el usuario marcó incluso con ajuste de línea, scroll o Markdown. En una caja de salida contraída solo se puede marcar lo visible; copiar su contenido completo es la acción explícita separada.

Se conserva Workspace Authority, IsySentinel, el owner de portapapeles y su journal. Ni un gesto ni el cambio visual amplían permisos. Ajustar el origen de una copia completa requerirá validar el contrato actual del owner; no se simula una selección ajena al usuario. Seguir `docs/roadmap-classic-security-ux.md` para las partes de UX de permisos.

## Familias representadas en cada lámina

1. Sidebar Overview: estado, Sentinel, MCP, LSP, skills y conexiones; filas sin marcos anidados.
2. Sidebar Files: búsqueda, árbol, acciones y preview útil.
3. Settings: conversación, preferencias, permisos y conexiones; categorías claras sin repetirlas en cada fila.
4. Proveedores y cuentas; selección y estado activo.
5. Modelos: lista, modelo vigente y detalles.
6. Authority & Security: modo, permisos y nota de aprobaciones por acción.
7. Multi Harness: hosts, conversaciones y propuestas de reparación.
8. Sesiones: buscar, abrir, renombrar y nueva conversación.
9. Ideas, cola y texto pegado: contenido ampliable y acciones de revisión.
10. Salida de comandos/procesos: estado, salida retenida y receipt.
11. Aprobación de edición/lote/commit: diff y acciones explícitas.
12. Aprobación de comando/MCP/conexión: destino o comando y alcance visible.
13. Preview de archivo y panel de texto: rango seleccionable y menú de copia nuevo.
14. Paleta y selectores de rol, contexto y razonamiento: misma plantilla de lista/búsqueda/detalle.
15. Formularios de conexiones/MCP/Gateway/LSP y claves: misma plantilla de campos; secretos enmascarados.
16. Bienvenida, modo y avisos: misma plantilla de decisión; no recortar botones.
17. Journal, detalles y búsqueda: misma plantilla de resultados y evidencia.

Las láminas son un catálogo de familias y estados representativos, no un inventario completo de cada opción del producto ni evidencia de funcionalidad implementada.

## Secuencia de trabajo

1. Mostrar tres láminas; seleccionar una o combinar rasgos mediante una nueva revisión visual.
2. Componer la dirección elegida sobre las capturas reales del usuario; revisar Settings, sidebar abierto/cerrado y cajas de texto.
3. Derivar estilos compartidos para títulos, superficies, bordes, filas, selección, foco, botones, ayuda y estados semánticos. Mantener información además del color.
4. Corregir F1 y F2 de la auditoría (modo mostrado y Configuración fuera de pantalla), luego F3 (foco), F4/F5 (altura/preview) y F6 (idioma).
5. Implementar el contrato de gestos en ExpandableBox, ThoughtBlock, CommandOutputCard y los paneles de texto relevantes, sin alterar el teclado de los campos editables ni botones de consentimiento.
6. Validar selección/copia con rango parcial, dos líneas, ajuste de línea, Unicode, scroll y cajas contraídas. Comprobar que doble clic no cambia expansión y que Space no escribe al portapapeles.
7. Verificar contraste, foco y controles visibles en 80×24, 100×30 y 140×40, con español, alto contraste y modo ASCII. Verificar el portapapeles real en la terminal del usuario además de fixtures locales.

## Puntos de código observados para el trabajo posterior

- `src/isycode/tui_widgets.py`: ExpandableBox y CommandOutputCard usan Enter/Space y segundo clic; SelectableText extrae el rango por `selection.extract(self.selection_text)` y envía Ctrl+C al owner.
- `src/isycode/tui_theme.py`: HIGH_CONTRAST_CSS ya usa negro, blanco y bordes legibles; la capa común debe cubrir también menus y estados dinámicos.
- `src/isycode/isycode.tcss` y CSS de pantallas: varias superficies, bordes y resaltados literales necesitan una fuente común.
- `src/isycode/clipboard_owner.py`: acepta orígenes de selección/ruta y aplica autoridad; revisar un origen explícito para copia completa antes de implementarlo.

## Criterio de aceptación de esta fase

Tres imágenes visibles, cada una con una familia coherente de menús y Settings prominente. Referencias originales y prompts preservados, hashes verificables. Solo material de diseño añadido; sin cambios al código del producto. La elección del usuario queda pendiente.

## Láminas finales para elegir

- [Propuesta 1](propuesta-1.png): Contraste esencial.
- [Propuesta 2](propuesta-2.png): Paneles por tarea, versión corregida que incluye Authority & Security.
- [Propuesta 3](propuesta-3.png): Consola modular, versión corregida que marca dos líneas en el ejemplo de copia.

La numeración corresponde a las tres direcciones completas aceptadas. Las versiones incompletas de la segunda y tercera se conservaron en `rejected/` y no son opciones adicionales. `selection-map.json` enlaza cada número a su fuente exacta y hash.

Generación: herramienta integrada Image Gen, tres conceptos independientes y dos correcciones dirigidas. Prompts originales en `prompts.json`; correcciones en `repair-prompt.txt` y `selection-repair-prompt.txt`. Se inspeccionaron y preservaron las siete referencias del usuario; se adjuntaron cinco por generación inicial debido al límite de la herramienta. La resolución solicitada fue 3840×2160; las salidas son 1672×941 sin reescalado artificial.

Los textos, estados y cifras dentro de las imágenes son ilustrativos. El plan de interacción es la referencia normativa; una imagen generada no demuestra funcionamiento, contraste exacto ni accesibilidad de una terminal real. Se revisaron las familias visibles, Settings, el panel de permisos y la selección de dos líneas. La implementación y la composición sobre la pantalla real esperan la selección del usuario.
