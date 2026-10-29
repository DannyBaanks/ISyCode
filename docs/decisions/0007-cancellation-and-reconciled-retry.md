# ADR 0007: Cancelación y retry reconciliado

- **Estado:** propuesto en M6. No está revisado por otra persona. No abre el bucle autónomo ni marca G6 como APROBADO.
- **Fecha:** 2026-10-02
- **SHA de partida:** `359ae1e`
- **Plan:** [roadmap Classic/Security](../roadmap-classic-security-ux.md)

## Contexto

El render de un stream, una nota de herramienta y un efecto durable estaban en el mismo camino. Cancelar un comando mata el grupo del proceso, pero una promoción a medias no tenía un punto de parada, y `git.push` autorizaba, llamaba al transporte y luego escribía el recibo. Si la respuesta se perdía, repetir la operación podía publicar o cobrar otra vez. No hay reintento de transporte acotado: o se repite el turno entero, o no hay nada.

## Decisión

El estado durable vive en un journal de operaciones, fuera del workspace, identificado por el digest de la petición. Se marca `effected` antes del efecto. El recibo se escribe solo cuando el resultado quedó persistido. Abrir un recibo devuelve ese resultado y no llama al transporte ni vuelve a cobrar. Abrir un `effected` sin recibo devuelve UNCERTAIN y no repite el efecto. No es exactly-once: sin acuse, no se adivina que no pasó.

Esc sigue cancelando la tarea. El comando en staging mata el grupo, incluidos el hijo y el nieto que no llaman a `setsid`, y la prueba lo mira en `/proc` del host. La promoción consulta un interruptor en cada paso: no aplica el archivo siguiente; si ya aplicó algo, reconcilia (restaura o deja el ledger incierto). Un stream cortado, un `finish_reason` de longitud o unos argumentos que no son un objeto JSON completo no son una tool call. `/retry` no reescribe un borrador nuevo ni reordena el transcript, y no relanza herramientas.

El backoff reintenta solo el connect, como máximo 3 veces en el stream (el tope del helper es 4), con espera acotada y jitter, y se detiene si la tarea se cancela. No reintenta un HTTP distinto de conexión, un redirect, una negación de egress, una tool ni el turno. Un fallo de provider no llama a `set_grant`.

`agent_loop` sigue siendo compactación. Este hito no arranca un supervisor, no enciende red, secretos, commit ni cambios de autoridad por su cuenta.

## Qué no hace

No marca G6 como APROBADO. No deshace una publicación que ya salió: eso queda UNCERTAIN hasta reconciliar. No promete matar un nieto que haya hecho `setsid` fuera del grupo. No mete el reintento dentro del turno de chat. No abre M6A.

## Alternativas rechazadas

- Reintentar el turno o la tool al perder la respuesta. Eso duplica efectos.
- Tratar la nota de herramienta como una orden pendiente al reiniciar.
- Reintentar después de haber escrito bytes de la petición. El connect es el único tramo idempotente que este proceso puede afirmar.
