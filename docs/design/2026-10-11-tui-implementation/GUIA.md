```bash
PYTHONPATH='/home/danny/Development/ISyCo Git/ISyCode/src' python3 -m isycode.launcher tui
```

Ejecuta esto desde la carpeta del proyecto donde quieras trabajar. Usa este
checkout directamente, aunque el comando `isycode` instalado apunte a otra copia.

**La regla:** marca el texto que quieres copiar. **Space** expande una caja;
el doble clic abre el menú de copia. Ninguno de los dos copia automáticamente.

## Arranque comprobado

El comando inicial se ejecutó en una terminal PTY de 80×24, con proyecto y estado
temporales, sin claves de provider y sin aceptar opciones de permisos. La pantalla
mostró este texto real:

```text
Bienvenido a ISyCode · ¿cómo quieres empezar?
```

El comprobador guardó la salida completa y devolvió:

```text
Real CLI PTY start; isolated project/state, no approval choices submitted.
output bytes: 30161 exit: 0 bounded stop: False
```

Eso verifica el arranque y la salida con Ctrl+Q. Los gestos se probaron con Textual
Pilot. El portapapeles del escritorio y la fuente de tu terminal necesitan revisión
en tu sesión real; no se certifican con las capturas.

## Recorrer la interfaz

- Abre **Configuración** con el engranaje. Conversación, Preferencias, Permisos y
  Conexiones quedan a la izquierda. Tab cambia de zona; las flechas recorren las
  opciones y Enter abre la elegida. La búsqueda encuentra opciones en todas las
  categorías.
- En una caja de texto, haz clic para enfocarla y pulsa **Space**. En un campo
  editable, Space sigue escribiendo un espacio. Enter conserva las acciones de
  botones, listas y envío de mensajes.
- Marca un rango con el mouse y pulsa **Ctrl+C**. Si marcas dos líneas, se copian
  esas dos líneas. No se agrega el resto de la caja por falta de selección.
- El doble clic abre **Copiar texto**. **Copiar selección** toma el rango marcado;
  **Copiar caja completa** es una opción aparte. Esc cancela y restaura la selección.
  El permiso de portapapeles sigue aplicando a ambas acciones.
- En **Archivos**, la lectura previa separa nombre/recibo del código. La ventana de
  lectura tiene botones independientes para selección y archivo completo.
- En Preferencias, **Movimiento reducido** deja estáticos los símbolos y detiene
  el desplazamiento compacto de texto. La preferencia se guarda para próximas
  sesiones.
- En el inicio de un proyecto, puedes enfocar el texto explicativo con Tab y
  desplazarte con las teclas de navegación; las decisiones permanecen visibles.

## Para editar siguiendo el estándar

Desde el repositorio:

```bash
python3 scripts/sync_design_tokens.py
```

Salida real:

```text
Design tokens match the accepted skill palette.
```

Lee la skill de diseño y la del componente antes de agregar menús. Este comando
comprueba que la paleta empacada sigue los tokens aceptados; no cambia permisos.

## Cómo leer los estados

| Lo que aparece | Qué significa / qué hacer |
|---|---|
| No hay texto seleccionado | Marca un rango; copiar selección permanece desactivado. |
| Copiar caja completa | Copia explícita del contenido retenido, sujeta al mismo permiso. |
| Movimiento reducido | Información conservada con símbolos estáticos. |
| Símbolo neutral / disponible | Disponibilidad; no prueba que una acción terminó con éxito. |
| Advertencia o error con causa | Revisa el texto del estado; el color no es la única señal. |
| Falta permiso de portapapeles | La copia pasa por Authority y Sentinel; el modelo no puede habilitarla. |

## Trampas

- La fuente la controla tu terminal. El perfil aceptado es Ubuntu Sans Mono con
  Unicode; 14 píxeles del navegador no son automáticamente 14 puntos de terminal.
- Its Hover usa SVG y React. La TUI adapta la idea a caracteres; las animaciones
  del comparador no se importan directamente.
- En Settings y los selectores, doble clic sigue abriendo opciones. La regla de
  Space y copia pertenece a las cajas de contenido.
- Las capturas usan datos de prueba. Un recibo ilustrativo de la galería no
  demuestra una ejecución real de comandos o modelos.
- El registro histórico G8 necesita reconciliación. Esta entrega no aprueba una
  publicación ni cambia ese registro para hacer pasar la suite.
