# ADR 0002: Qué se reutiliza para Classic autónomo

- **Estado:** propuesto en M0. No está revisado por otra persona y no autoriza autonomía.
- **Fecha:** 2026-10-02
- **SHA inspeccionado:** `db6c86314ce73ddb19e776f03db4a25eb08c9eb4`
- **Plan:** [roadmap Classic/Security](../roadmap-classic-security-ux.md)

## Contexto

El roadmap pide, antes de agregar infraestructura, decidir qué owners, checkpoints y backend ya sirven. Esta nota registra esa decisión de reuso. No cambia permisos ni activa Classic autónomo.

## Decisión

Reutilizar el kernel actual: `WorkspaceAuthority`, `IsySentinel`, `ProductActionGate`, `ActionApprovalStore`, el journal y los execution owners ya mapeados en el inventario M0. La TUI sigue en Textual 8.2.8. Los comandos siguen entrando por `CommandRunOwner` y Bubblewrap; no se añade un segundo motor de política dentro de la UI.

No reutilizar `safety.Budget` como ledger de M3. Sus topes pueden ser `None`, vive en memoria y no es un registro compartido entre procesos. Un tope ausente hoy no deniega.

No tratar un worktree de Git como aislamiento. No usar `git reset --hard`, `git clean` ni un stash destructivo como recuperación.

`CheckpointStore` se queda para el undo de escrituras tipadas. No cubre efectos de comandos. M3 tiene que añadir una promoción distinta; no basta con ampliar `/undo`.

## Alternativas de aislamiento observadas en esta máquina

Medido el 2026-10-02 en este host. No es una evaluación de licencias de productos que no se ejecutaron.

| Opción | Observado aquí | Uso para M2 |
| --- | --- | --- |
| Bubblewrap 0.9.0 en `/usr/bin/bwrap` | Presente. Un `python3` dentro del sandbox devolvió salida, y el flujo M0 corrió `unittest` por `CommandRunOwner`. | Backend actual. M2 todavía tiene que demostrar staging: hoy el workspace va montado escribible. |
| `unshare` | Presente en `/usr/bin/unshare`. No se usó como backend. | No sustituye el owner ni el manifiesto de promoción. |
| fuse-overlayfs, firejail, nsjail | No están en `PATH`. | No se eligen. No hay prueba local. |
| Worktree Git | No aísla ignorados, red, home ni procesos. El propio roadmap lo descarta como única frontera. | Rechazado como aislamiento. |

Si M2 no puede demostrar staging y protección de metadata sobre Bubblewrap, los comandos mutadores autónomos no se habilitan. Ese fallo deja el producto en el comportamiento actual: cada edición y cada comando piden aprobación.

## Referencias de producto

OpenClaw, OpenCode y Crush aparecen en el roadmap como referencias de experiencia y en comentarios de `tui.py` como inspiración visual. En M0 no se ejecutó ninguno con versión fijada, así que no hay paridad que afirmar. La captura de esta sesión muestra la TUI de ISyCode, no esas herramientas.

## Límites del sistema operativo

El flujo se midió en Linux 7.0.0-34-generic, x86_64, ext4 sobre NVMe, Python 3.12.3, Textual 8.2.8, glibc 2.39. Había 12 núcleos y 14 GiB de RAM, con unos 1,4 GiB disponibles y el disco al 91 %. Esta máquina no es la caja de referencia de M9 (4 núcleos, 8 GiB, repo de 10 000 archivos). No se trasladan cifras de latencia de aquí a esa meta.

Windows y macOS no tienen este backend. Un skip de Bubblewrap no aprueba comandos allí.

## Amenazas que este reuso no cierra

- El sandbox actual puede modificar el checkout montado. Un comando aprobado puede borrar ese árbol.
- El preset Classic no escribe los grants. Cambiar a Security apaga el preset y conserva los grants explícitos ya guardados.
- Un `.isyroot` en una carpeta amplia hace que los descendientes sin marcador compartan su autoridad. `/home/danny/Development/ISyCo Git` está en Classic y no dispara el aviso de carpeta amplia.
- `safety.Budget` no impide fraccionar un daño en muchas llamadas.
- El proveedor en vivo no forma parte de esta medición. El flujo usó un proveedor simulado.

## Coste de migrar

M1 puede extraer presentación desde `tui.py` sin nuevo backend. M2 y M3 son los cambios caros: staging, manifiesto y ledger fuera del checkout. Hasta que G4, G5 y G6 estén aprobados, Classic sigue pidiendo aprobación por edición, comando y commit.

## Consecuencias

- El siguiente trabajo de producto que cambie autonomía es M1, y solo después de que un revisor distinto acepte G0.
- Esta ADR no es esa aceptación.
