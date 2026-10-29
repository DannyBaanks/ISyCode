```bash
python3 -u -m http.server 8781 --bind 127.0.0.1 --directory '/home/danny/Development/ISyCo Git/ISyCode/docs/design/2026-10-11-icons-typography'
```

La regla: este comparador sirve únicamente la carpeta de diseño en tu equipo. **No cambia ISyCode, la fuente de tu terminal, permisos ni conexiones.** Los datos de las cajas son ejemplos.

## Abrirlo

Ejecuta el comando de arriba en una terminal. Fue ejecutado durante esta entrega y produjo:

```text
Serving HTTP on 127.0.0.1 port 8781 (http://127.0.0.1:8781/) ...
```

Abre [el comparador](http://127.0.0.1:8781/preview.html). Si ya está abierto, recarga la página para cargar esta revisión. Mantén abierta la terminal del servidor mientras lo usas. Esta revisión se comprobó por archivos y HTTP; el navegador automático rechazó el acceso a la pestaña de error, así que la revisión visual de las animaciones queda pendiente.

## Tu configuración elegida

La página inicia con **Ubuntu Sans Mono · Unicode · 14 px · interlineado 1.3**, sobre la primera propuesta de alto contraste. Puedes variar los controles para comparar. Las tres muestras superiores conservan su propia fuente para que veas sus diferencias reales.

El tamaño está en píxeles de navegador. No equivale automáticamente al número que aparece en las preferencias de GNOME Terminal. Ubuntu Sans Mono conserva el texto; una copia local de DejaVu Sans Mono muestra los símbolos que faltan. Ese ajuste del navegador requiere comprobación aparte en una terminal real.

## Recorrer los ejemplos

- **Settings:** cambia entre Conversación, Preferencias, Permisos y Conexiones. La categoría queda a la izquierda y los valores y ayuda a la derecha.
- **Inicio y salida:** revisa el estilo común para resultados, Skills e Idea box. El comando mostrado no se ejecuta.
- **Caja y selección:** marca texto y pulsa **Ver selección**. Muestra el rango marcado. **Ver caja completa** es una acción separada. Aquí todavía no se escribe al portapapeles.
- **Resumen / Archivos:** compara las dos vistas del sidebar. El árbol contiene nombres ilustrativos.
- **Its Hover:** pasa el mouse, enfoca con Tab o pulsa cada ejemplo. El icono SVG muestra la referencia animada y los caracteres de la derecha muestran una idea para la terminal. No se ejecutan comandos, copias ni conexiones.
- **Reducir movimiento:** deja los iconos estáticos. También se respeta la preferencia de movimiento reducido del sistema.

## Cómo leer los estados

| Lo que aparece | Qué significa / qué hacer |
| --- | --- |
| Fuente local cargada | El navegador terminó de cargar la fuente indicada. |
| Error cargando alguna fuente | No se ha confirmado la carga; comprueba que abriste la página desde este servidor. |
| Listo / disponible / configurado | Información neutral del ejemplo; no demuestra una comprobación real. |
| ✓ Completado | Estilo de un resultado correcto; en el producto debe depender de un resultado confirmado. |
| △ No disponible | Aviso con una causa específica, sin depender sólo del color. |
| Sin configurar / Sin comprobar | No supone que una conexión funciona. |
| No hay texto seleccionado | Marca el rango; no se reemplaza la selección por toda la caja. |
| Movimiento reducido | La información se conserva sin animación. |

## Trampas que conviene evitar

- Si la página muestra que no se puede acceder, el servidor puede haberse detenido al terminar una sesión. Arráncalo con el comando inicial y recarga manualmente.
- Si el puerto ya está ocupado por este comparador, usa la página que ya sirve. No arranques otro servidor sobre el mismo puerto.
- Descargar estas fuentes para el comparador no las instala en el sistema. Los iconos de Nerd Fonts requieren una fuente parcheada; tu elección Unicode usa otra ruta.
- Its Hover está diseñado para SVG y React/Motion. En una TUI de caracteres se adapta el movimiento; no se pega el componente React directamente.
- El archivo LICENSE de Its Hover es Apache 2.0, aunque algunos metadatos todavía dicen MIT. Los avisos originales están conservados en `licenses/`.
- Las ayudas de Space y doble clic muestran el contrato futuro: **Space expande; doble clic abre el menú de copia; copiar selección toma sólo lo marcado**. No demuestran que ya esté implementado en ISyCode.

El [plan completo](INVESTIGACION.md) relaciona esta dirección con todas las familias de menús y los hallazgos de la auditoría.
