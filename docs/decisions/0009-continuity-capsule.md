# ADR 0009: Cápsula de continuidad

- **Estado:** propuesto (pendiente de revisión de Danny Baanks).
- **Fecha:** 2026-10-07
- **Pedido:** Danny Baanks, 2026-10-07: un motor que cubra cada pérdida de contexto con un coste mínimo ("SI TODAS").
- **Relacionadas:** [ADR 0007](0007-cancellation-and-reconciled-retry.md) y [ADR 0008](0008-automatic-continuity-recovery.md).

## Contexto

La auditoría del 2026-10-07 encontró cinco problemas:

1. **No había compactación automática.** `/compact` solo resumía cuando se lo pedías, y `compact_turn` existía pero nadie lo llamaba. Una conversación larga crecía hasta que el provider la rechazaba.
2. **El rechazo no se recuperaba.** "Request too long" llegaba como un 400 y se clasificaba como `REQUEST`, que es terminal. El turno se perdía.
3. **Las notas de herramientas viajaban enteras en cada request.** `tool_history` se reenviaba completo en cada turno, con el texto de cada archivo leído y sin tope. Era el mayor gasto de contexto de una sesión larga.
4. **Cambiar a un modelo con ventana menor, o reanudar una sesión larga, mandaba todo igual.** Nada se ajustaba a la ventana del modelo.
5. **Los subagentes empezaban sin contexto.** No sabían qué pidió el usuario, qué tareas había ni qué se había tocado. Solo recibían las notas tras un error.

## Decisión

ISyCode arma una **cápsula de continuidad** (`isycode/continuity_capsule.py`).

**Qué es.** Un mensaje de sistema construido de forma determinista con datos que ISyCode ya tiene:

- las peticiones anteriores del usuario, recortadas;
- las notas narrativas, si existen;
- la lista de tareas y el Idea box;
- lo que se cambió, cada cambio con el resultado que reportó la herramienta;
- los comandos, con su código de salida;
- lo que se leyó;
- los últimos resultados de herramientas, recortados.

**Qué cuesta.** Armarla no cuesta tokens ni hace llamadas al provider.

**Sus límites.**

- Tiene un presupuesto de caracteres y siempre lo respeta.
- Cuando recorta, deja dicho cuántas entradas omitió.
- No lleva ids de llamadas, aprobaciones ni grants.
- Sale de las notas ya redactadas.
- Le dice al modelo que es información posiblemente vieja y que verifique el estado actual antes de actuar.

**Presupuesto por modelo.** El historial y las notas pueden ocupar la mitad de la ventana del modelo, a unos 3 caracteres por token.

- Si la ventana es desconocida, se asume una de 128k tokens.
- El mínimo es de 24k caracteres.
- Si todo cabe, el request queda **exactamente igual que antes**.

**Las cuatro pérdidas que cubre:**

| Pérdida | Qué hace ISyCode |
|---|---|
| Conversación larga | Al empezar el turno, si el historial no cabe, manda los mensajes recientes (empezando en un mensaje del usuario) y la cápsula en lugar de los viejos. Las notas completas se reemplazan por su resumen en la cápsula. |
| Rechazo "too long" | Clase nueva `CONTEXT`: códigos `context_length_exceeded`/`string_above_max_length`, mensajes conocidos de OpenAI, vLLM/NIM y Anthropic, o un HTTP 413. Se reenvía **una sola vez**: los mensajes de sistema y el turno actual se conservan, lo anterior pasa a la cápsula y los resultados viejos del turno quedan como stubs con su `tool_call_id`. Es seguro por la misma razón que la ADR 0008: el paso falló antes de despachar herramientas. Un segundo rechazo cierra el turno como antes. |
| Cambio a un modelo con ventana menor | El presupuesto se calcula en cada turno con la ventana del modelo activo, así que un modelo más chico recibe la cápsula sin hacer nada más. |
| Sesión reanudada | La sesión guardada se carga completa y el primer turno aplica la misma regla. |
| Subagente | El hijo recibe una cápsula de hasta 6000 caracteres como mensaje de sistema, antes de su tarea. |

**Notas narrativas (opcional, coste bajo).** Cuando el historial no cabe, el slot de modelo "small" resume los mensajes viejos de forma incremental con el mismo `_summarize_older` de `/compact`. La petición pasa por `ProviderNetworkOwner` y queda en el journal. Eso ocurre **solo si ese slot usa el mismo provider que el chat**: la compactación automática nunca manda la conversación a un provider que el usuario no eligió para ella. En cualquier otro caso (otro provider, sin credencial, denegado o fallido), la cápsula determinista cubre sola los mensajes viejos.

**Qué se guarda.** El transcript guardado no cambia: los mensajes se agregan sin borrarse. La cápsula y las notas narrativas son contexto del request, no historial.

## Evidencia real (2026-10-08)

Canario contra NVIDIA NIM en [`docs/evidence/continuity-canary-2026-10-08/`](../evidence/continuity-canary-2026-10-08/README.md):

- **Cápsula sola y con notas narrativas:** PASS.
- **Rechazo real por tamaño:** PASS, después de agregar la redacción de vLLM/NIM (`max_tokens must be at least 1, got -N`) a la clase `CONTEXT`.
- **Corte de stream:** PASS.
- **Estimación de tamaño:** con texto repetitivo se midieron unos 5 caracteres por token, así que la estimación de 3 es conservadora.

## Qué no hace

- No cambia grants, autoridad, aprobaciones ni el journal.
- No reintenta herramientas.
- No reintenta `CONTEXT` más de una vez, ni lo mete en la política de retrasos de la ADR 0008.
- No manda la conversación a otro provider para resumirla. Para el subagente, el provider es el que el usuario elige al lanzarlo; ese provider ya recibía la tarea, y ahora también recibe la cápsula acotada.
- No promete ahorro por caché de prompts. La cápsula es determinista y va siempre en la misma posición, lo que ayuda a un caché por prefijo si el provider lo tiene. No se midió el caché de NVIDIA NIM ni de otros providers: **NOT_DEMONSTRATED**.
- La estimación de 3 caracteres por token es conservadora, no una medición. Si el provider rechaza el request igual, se recupera con el paso `CONTEXT`.

## Qué reemplaza

La frase de `docs/daily-use-readiness.md` y del README que decía que ISyCode no compacta el historial automáticamente. `/compact` sigue igual.
