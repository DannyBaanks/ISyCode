# ADR 0008: Recuperación automática de un paso de chat

- **Estado:** propuesto. Reemplaza parcialmente la [ADR 0007](0007-cancellation-and-reconciled-retry.md). Reabre `G6-05`, pendiente de revisión independiente.
- **Fecha:** 2026-10-07
- **Autorización para reabrir:** Danny Baanks, 2026-10-07 ("SI OK").
- **Plan:** [roadmap Classic/Security](../roadmap-classic-security-ux.md)

## Contexto

La ADR 0007 dejó el turno de chat sin reintento. Cuando un stream se cortaba o el provider devolvía un 503, el turno se detenía y había que usar `/retry` a mano, aunque no hubiera ningún riesgo de repetir efectos. La garantía era correcta, pero la experiencia era molesta.

Dentro de un turno, las herramientas se ejecutan solo después de que una respuesta del provider llegó completa. Por lo tanto, si falla el request o el stream de un paso, ese paso todavía no despachó ninguna herramienta. Los efectos anteriores ya están en los mensajes del turno, cada uno con su recibo.

## Decisión

Cuando un paso falla con una clase recuperable, ISyCode reenvía los mismos mensajes de ese paso. Es una continuación protegida: una generación nueva y un request nuevo, que pasa por `ProviderNetworkOwner` y queda en el journal como cualquier otro.

1. **El parcial se descarta.** Lo que el paso alcanzó a transmitir (texto mostrado, razonamiento y buffers) nunca se registra en el historial.
2. **Retraso fijo por clase, sin backoff exponencial.** El retraso es el mismo antes de cada intento:

   | Clase | Retraso | Intentos |
   |---|---|---|
   | STREAM | 0.75 s | 4 |
   | NETWORK | 1.5 s | 3 |
   | TIMEOUT | 2 s | 3 |
   | PROVIDER (5xx) | 3 s | 3 |
   | RATE_LIMIT (429) | 7 s | 3 |

3. **`Retry-After`.** Se respeta si es válido y no pasa de 15 s; nunca se usa un retraso menor al de la clase. Si el provider pide más de 15 s, la recuperación se detiene y se le dice al usuario, en lugar de bloquearlo en silencio.
4. **Clases terminales, sin reintento.** Credenciales, cuota, permiso, configuración, request inválido, autoridad, imágenes y steering. También los errores deterministas sin status (URL, credencial o frame inválidos, argumentos demasiado grandes, respuesta HTTP malformada), los errores dentro del stream con código desconocido, y lo que no se reconoce.
5. **Al agotar el presupuesto** se cierra el turno igual que antes: el prompt queda guardado y `/retry` está disponible. El aviso dice cuántos intentos se hicieron y que ningún efecto se repitió.
6. **Esc durante la espera** cancela el turno y no hay más intentos.
7. **Un steering en cola** se aplica en el paso reintentado, que es el siguiente límite seguro. El reintento no reordena el steering.
8. **El aviso de recuperación** va a la barra de estado ("↻ … retrying in Xs (n/m)") y a una nota tenue en el transcript. Nunca entra al historial del modelo ni a los mensajes guardados.

Esto reemplaza dos frases de la 0007: *"No mete el reintento dentro del turno de chat"* y la alternativa rechazada *"Reintentar el turno … al perder la respuesta"*. El resto sigue vigente:

- el journal de operaciones;
- UNCERTAIN cuando hay efecto sin recibo;
- `/retry` no relanza herramientas;
- el reintento de connect en `TransportRetry`. Se conserva sin cambios: es un tramo sub-segundo (tope de 0.2 s), sigue fijado por la evidencia aprobada de G6 y no es el reintento del turno.

## Qué no hace

- No recupera la misma respuesta: los streams compatibles con OpenAI no se pueden reanudar.
- No reintenta un paso que ya despachó herramientas, porque ese caso no existe en este punto del bucle.
- No reintenta subagentes ni `isycode -p` (headless). Siguen como antes.
- No cambia grants ni autoridad.
- No marca G6 como APROBADO.

## Criterio nuevo de G6-05

Retraso fijo por clase con presupuesto pequeño y `Retry-After` acotado. Las clases terminales no se reintentan. Esc cancela la espera. El reintento automático de un paso nunca repite una herramienta ya despachada. Los fallos de provider no cambian la autoridad.
