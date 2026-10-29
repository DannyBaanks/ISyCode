# ADR 0004: Ledger de efectos fuera del checkout

- **Estado:** propuesto en M3. No está revisado por otra persona y no autoriza autonomía.
- **Fecha:** 2026-10-02
- **SHA de partida:** `fa501e16db0f4e54e7b96255c027c7c24903191b`
- **Plan:** [roadmap Classic/Security](../roadmap-classic-security-ux.md)

## Contexto

M2 copia el workspace y promueve un diff medido, archivo por archivo. Esa promoción no es atómica: un crash a mitad deja una parte aplicada y no hay tope acumulado. `safety.Budget` no sirve: sus topes son `int | None` y `None` significa ilimitado.

## Decisión

El ledger vive en el estado de ISyCode, fuera del checkout: `effect-ledger/<dispositivo>-<inodo>.json`, con un lock y preimágenes en `preimages/`. La identidad es el dispositivo y el inodo del directorio resuelto. Renombrar la carpeta o abrirla por un symlink no abre otro saldo. Un directorio nuevo sí es otra identidad.

Cada límite es un entero finito, versión `LIMITS_VERSION = 1`:

| Límite | Valor | Por qué |
| --- | --- | --- |
| Rutas por operación | 4000 | Por encima de la promoción de ~200 archivos que ya ejercita M2, y por debajo de un borrado del árbol entero. |
| Borrados por operación | 2000 | Una sola llamada no puede vaciar un workspace grande. |
| Bytes por operación | 32 MiB | Cubre ediciones y comandos de un día; no cubre reescribir dependencias. |
| Rutas únicas acumuladas | 20000 | Se cuentan una vez. Repetir la misma ruta no abre cupo nuevo. |
| Borrados acumulados | 10000 | Cada borrado promovido cuenta, también si la ruta ya se tocó. |
| Bytes acumulados | 256 MiB | Cada commit suma. Repetir una edición no sale gratis. |

Una llamada más grande que el tope se niega entera y suma 0. Mil llamadas de una unidad se detienen en el tope. Partir el trabajo no lo rebasa. Esos dos caminos no aplican la misma cantidad: el primero aplica cero.

La promoción toma el lock y lo suelta al terminar o al morir el proceso. El orden es reserva, copia de preimágenes, plan, aplicar, commit. Si el proceso muere antes del commit y el plan no está completo, la siguiente apertura restaura sus propias preimágenes y no cobra. Si el plan quedó completo, cobra una vez. Si los bytes no coinciden ni con la preimagen ni con el destino, el estado queda `uncertain` y no hay más reservas hasta que una persona escriba exactamente `reset effect ledger`. Ese método no es una acción ni una tool.

Las escrituras, borrados, movimientos y undo tipados reservan antes de consumir la aprobación. Si el tope niega, la aprobación sigue válida. El crash entre el `replace` de un solo archivo y el commit puede no cobrar ese archivo: el replace ya es atómico y no hay journal por byte. Queda dicho aquí.

Los directorios vacíos se borran después del commit. Si el proceso muere en ese hueco, el archivo ya está cobrado y el directorio vacío puede quedar.

## Qué no hace

No sube el tope, no lo lee del entorno y no lo expone al modelo. No usa `git reset`, `git clean` ni un stash destructivo. No abre Classic sin aprobación. No marca G3 como APROBADO.

## Alternativas rechazadas

| Opción | Por qué no |
| --- | --- |
| Reusar `safety.Budget` | `None` es ilimitado. M3 lo prohíbe. |
| Identidad por hash de la ruta | Renombrar la carpeta pondría el saldo a cero. |
| Worktree o `git reset` para deshacer | No conserva sucio, untracked ni el índice, y el roadmap lo prohíbe. |
| Completar hacia adelante un plan a medias | Inventaría el resto del diff después de un crash. |
