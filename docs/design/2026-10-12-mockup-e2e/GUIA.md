# Abrir los menús integrados de ISyCode

Desde el proyecto que quieres usar:

```bash
isycode
```

**Regla:** previsualizar una opción no la aplica. Revisa el valor y confirma con
el botón indicado; los permisos y las aprobaciones siguen siendo necesarios.

El comando instalado se probó en una terminal real de 80×24 con estado temporal,
sin claves. El clic en Settings abrió el menú y el proceso terminó con código 0,
sin traceback. [Resultado y condiciones](evidence/native-complete-result.json).

## Ver el resultado

- [Galería de la versión revisada, 140×40](screens-reviewed-140x40/index.html).
- [Menús a 80×24](screens-80x24/index.html).
- [Menús a 100×30](screens-100x30/index.html).

Las imágenes son exportaciones de Textual con datos de ejemplo aislados. No son
otra implementación HTML del producto. La página sólo permite ver las capturas.

## Comandos comprobados

Para consultar las opciones del comando instalado:

```bash
isycode --help
```

Inicio de la salida real:

```text
ISyCode · terminal workspace agent

Usage:
  isycode                 Start the chat TUI in the current directory
  isycode tui              Start the chat TUI
  isycode cli              Browse actions by semantic category
  isycode doctor [--json]  Inspect local dependencies/configuration; no network calls
```

[Salida completa](evidence/installed-help.txt).

La captura final se generó desde el checkout con este comando:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/capture_design_gallery.py --out docs/design/2026-10-12-mockup-e2e/screens-reviewed-140x40 --columns 140 --rows 40 --locale es
```

Salida real:

```text
Real Textual captures: /home/danny/Development/ISyCo Git/ISyCode/docs/design/2026-10-12-mockup-e2e/screens-reviewed-140x40
```

El script exige un directorio de salida nuevo. Para repetirlo, cambia `--out`;
no reemplaces las capturas guardadas. Usa sólo datos temporales y no envía
prompts ni ejecuta acciones del proyecto.

## Usar las cajas

| Acción | Resultado |
| --- | --- |
| Espacio sobre una caja de contenido | Expande o contrae la caja. |
| Arrastrar el ratón sobre texto | Marca el rango exacto. |
| Ctrl+C con texto marcado | Solicita copiar únicamente la selección. |
| Doble clic sobre una caja | Abre el menú de copia. |
| Copiar selección | Copia lo marcado; sin selección queda desactivado. |
| Copiar caja completa | Copia todo el contenido retenido de esa caja. |
| Enter en una lista o botón | Activa esa opción; no es el gesto de expansión de texto. |
| Esc | Cancela o vuelve sin aplicar una opción previsualizada. |

En Configuración, elige una categoría o busca una opción. **Proveedor** y
**Modelo** muestran valores actuales y abren selectores independientes. En
Modelos, el primer clic muestra los detalles; **Usar modelo** confirma la
fila previsualizada. Si un catálogo se actualiza, esa fila conserva su identidad.

Los diálogos de revisión mantienen **Cancelar/Rechazar** y **Aprobar/Ejecutar**
visibles mientras desplazas el contenido. Una propuesta de edición muestra el
diff completo; el owner sigue decidiendo qué se aplica y cuándo.

## Leer los estados

| Estado | Significado y siguiente paso |
| --- | --- |
| Actual | Selección guardada o default que usaría el provider; no prueba conexión. |
| Sin configurar | Falta configuración; abre el formulario correspondiente. |
| No disponible | Revisa la causa mostrada, como ejecutable ausente o sandbox. |
| Skills disponibles | Catálogo consultable; no indica ejecución ni permiso. |
| ON/OFF en Permisos | Valor de la capacidad de este workspace; revisa su alcance antes de cambiarlo. |
| Botón Elegir desactivado | No hay una fila válida visible, o el modelo previsualizado salió del catálogo. |

## Si todavía aparece la interfaz anterior

Una TUI que ya estaba abierta conserva su código. Ciérrala y vuelve a ejecutar
`isycode`. El enlace local ahora abre `main/scripts/isycode`, que carga `src/`
del checkout **ISyCode**; no abre el worktree anterior. El enlace previo quedó
guardado en `isycode.backup.20261013T030508Z.814965` dentro de `~/.local/bin/`.

El perfil de tu terminal decide la fuente y el tamaño. La preferencia visual es
Ubuntu Sans Mono; el comparador usó 14 px e interlineado 1.3. Textual no cambia
ese perfil y los px del navegador no equivalen automáticamente a puntos de
la terminal. ASCII y movimiento reducido se eligen desde Preferencias.

No borres preferencias, claves ni conversaciones para actualizar la apariencia.
Las conexiones externas y la copia real al portapapeles del escritorio tienen
condiciones propias: las pruebas de esta integración usaron providers simulados
y un servidor X11 privado para comprobar la copia con xclip. Marcar dos líneas
copió sólo esas líneas, también al arrastrar en sentido inverso. La opción de
caja completa copió todo el texto mediante su acción explícita. Esto no alteró
tu portapapeles ni certifica la configuración de tu escritorio.

[Informe técnico y evidencia](REPORT.md).
