# Verificación de ISyCode IDE

## Correcciones e iconos — 11 de octubre

`polish-accepted-regression-20261011.log`: **228 passed**, con comando, exit y
SHA-256 en su JSON. `qt-polish-20261011-complete/` contiene renders nativos
de ambas vistas, menús y actividad de GitHub en cuatro tamaños, incluido el
mismo viewport de los mockups (1672×941). Son datos ficticios, sin llamadas
a cuentas. El informe [design-qa.md](../../design-qa.md) registra comparaciones,
correcciones y diferencias con las referencias; no afirma identidad de píxeles.

Los tests nuevos cubren destinos distintos sin perder borradores, controles
compactos, actividad remota parcial, enlaces fijos, SVG/ASCII y recibos de
los assets. `polish-packaged-final-20261011.json` verifica AppImage, Qt, namespaces,
ayuda TUI y recursos originales incluidos en el ejecutable congelado.

## Entrega anterior

La suite `full-suite-delivery-0540.log` terminó con **203 passed**. El JSON adjunto
registra comando, timestamp, exit y SHA-256. Los tests aíslan configuración
y keyring por caso; no hacen generación real ni actualizan repos del usuario.

| Capacidad | Evidencia y alcance |
|---|---|
| GUI aprobada | `qt-release-final/`: renders Qt de pantallas y ambas vistas en 1024×768, 1366×768 y 1920×1080, con proyecto y chat ficticios. Manifiesto con hashes. |
| HiDPI | Capturas escala 2 en `qt-hidpi-final/`, con manifiesto público. |
| Providers | Fixtures de streaming Ollama/Google, formato de tool calls y finalización; tests de endpoints. Anthropic comprueba el SDK instalado con HTTP local y rechaza redirects. Compatibilidad de modelos/cuentas reales: NOT_DEMONSTRATED. |
| Conversaciones | Qt/TUI reanudan el almacén compartido con provider/modelo guardados y selección explícita cuando faltan; pruebas de eventos, exclusión de turnos, selector y clear aditivo. |
| Migración | Idempotencia, conflictos conservados y origen sin modificar en proyectos fixture. |
| Autoridad | PLAN, switches, rechazos, argumentos modificados, permiso exacto y revocación. |
| Propuestas | Hashes, batch obsoleto sin escribir, fallo parcial y recuperación revisada sin borrar archivos nuevos. |
| Comandos | Linux namespaces reales: sin red, sin secreto de entorno/home, sin enlace externo; checkout original intacto. No hay fallback al host. |
| GitHub | Git real y gh/red fixture: upstream distinto de la rama local, dirty, base cambiada, archivos ignorados conservados, ff-only y hooks deshabilitados; catálogo privado. Cuentas/repos reales: NOT_DEMONSTRATED. |
| Suscripciones | Subproceso fixture verifica frontera dinámica/nativa/API/cancelación. Codex y Claude instalados responden sin login con home propio. OAuth/generación real: NOT_DEMONSTRATED. |
| Paquete | PyInstaller/AppImage self-check comprobó Qt y namespaces sin cuenta. Herramienta/runtime de AppImage fijados por los digests oficiales guardados aquí. |

Los resultados negativos anteriores permanecen en el workspace privado. El
build instalado no implica compatibilidad con otras distribuciones Linux;
el host de build y checks es Ubuntu 24.04 x86_64.

Referencia de empaquetado: [appimagetool oficial](https://github.com/AppImage/appimagetool).
Guía de operación y límites: [GUIA.md](../../GUIA.md).

Revisión independiente y correcciones: [final-review.md](final-review.md).
Las once regresiones iniciales conservan resultados RED y GREEN, con hashes.
La cancelación HTTP conserva respuesta parcial; la cancelación del comando
termina sus descendientes reales en namespaces. La instalación aditiva conserva
archivos existentes; el instalador se prueba con un HOME temporal.
