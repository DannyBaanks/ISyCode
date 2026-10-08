# Canario real: recuperación (ADR 0008), cápsula (ADR 0009) y catálogo NVIDIA

- **Fecha:** 2026-10-08. Catálogo de 05:08:32Z a 05:15:41Z; canario de 05:16Z a 05:21Z.
- **Provider:** NVIDIA NIM (`integrate.api.nvidia.com`), con la clave guardada de Danny.
- **Modelos:** `z-ai/glm-5.3-flash` (A1, A2, C) y `openai/gpt-oss-20b` (B; ventana oficial de 131 072 tokens).
- **Autorización:** Danny Baanks, 2026-10-08 ("VALE HAGAMOS LAS PRUEBAS CON NVIDIA").
- **Entorno:** Ubuntu 24.04, Python 3.12, Textual 8.2.8. Código: `main` en `c5eac67` y, solo para la segunda corrida de B, el arreglo de esta misma rama (ver abajo).

## Cómo se ejecutó

`canary.py` usa la `TUIApp` real con `run_test()`, el turno de chat real (`_run_chat`), `ProviderNetworkOwner`, Workspace Authority, IsySentinel y el journal real, contra el provider real. El camino al provider no está simulado. El script solo envuelve `provider_complete` para registrar el tamaño y el sha256 de cada request, su uso de tokens y su error.

- **Clave:** se lee una vez desde el almacén guardado, dentro del proceso, y nunca se imprime ni se escribe. Se comprobó que no aparece en ninguno de estos archivos.
- **Estado aislado:** todo el estado de ISyCode (preferencias, sesiones, journal) vive en un directorio temporal. Ese estado no se copia aquí.

Dos condiciones se prepararon a propósito y se declaran:

1. **A1 y A2 usan una ventana simulada de 16k tokens**, guardada en las preferencias aisladas, para que la cápsula se active sin mandar un request enorme. El modelo y el provider son reales.
2. **C corta un stream real del lado del cliente**, después de recibir 3 fragmentos reales. No se puede provocar a voluntad un corte del lado del servidor.

## Resultados

| Escenario | Qué se probó | Requests (chars → tokens de entrada) | Resultado |
|---|---|---|---|
| A1 | Historial de 40 mensajes que no cabe en la ventana. Slot *small* en otro provider, así que solo se usa la cápsula. | 1 chat: 25 589 → 7 687 | **PASS.** El request no llevaba la petición original (`has_request_0: false`), solo la cápsula. El modelo respondió `ZAFIRO-7319`, la palabra clave que solo estaba en esa petición vieja. Journal PASS. |
| A2 | Lo mismo, con el slot *small* en el mismo provider (notas narrativas). | 1 resumen: 42 643 → 8 416; 1 chat: 23 198 → 7 177 | **PASS.** Se resumieron 28 mensajes y el chat llevó las notas, no los mensajes viejos. Respondió `ZAFIRO-7319`. Journal PASS. |
| C | Corte de stream a mitad de respuesta. | 2 chats, **idénticos** (sha256 `3a3b928a…`): 3 411 → 3 314 | **PASS.** Hubo 1 reintento automático y la respuesta salió completa: "✓ Response recovered after 1 automatic retry · no tool effects repeated". Journal PASS. |
| B (control) | 590 127 chars, que sí caben. | 1 chat: 590 127 → **117 038** | Aceptado. Con este texto el tokenizador midió unos 5,0 chars/token; la estimación de ISyCode (3) es más conservadora. |
| B (antes del arreglo) | 896 367 chars, por encima de la ventana real. | 1 chat → **HTTP 400** | **FAIL, ya corregido.** NIM no nombra el contexto: responde `max_tokens must be at least 1, got -50994`. ISyCode lo clasificaba como `REQUEST` (terminal), así que la cápsula no se activó y el turno se cerró sin respuesta. |
| B (con el arreglo) | El mismo request de 896 367 chars (mismo sha256 `17ce86cf…`). | 1 chat → 400 `CONTEXT`; reenvío: 8 696 → 3 452 | **PASS.** Se reconoció como `CONTEXT` y se reenvió una vez con la cápsula (se quitaron 40 mensajes). Respondió `ZAFIRO-7319`. Journal PASS. |

**El arreglo** está en `src/isycode/provider_errors.py`. Un mensaje `max_tokens must be at least 1, got -<n>` (o `max_completion_tokens`) se clasifica como `context_length_exceeded`. Solo coincide con un valor **negativo**: `got 0` sigue siendo un error de parámetro. `errbody.py` es la sonda que capturó ese texto; un request rechazado no consume tokens.

**Consumo aproximado** de toda la prueba: unos 150k tokens de entrada y menos de 1k de salida. El 78 % corresponde al control de B que sí cabía (117k).

## Catálogo NVIDIA (`nvidia-availability-2026-10-08.jsonl`)

Comando: `python -m isycode.vision_probe --workspace <tmp> --provider nvidia --availability-only --timeout 45`. Cada modelo recibe "Reply OK only" a través del mismo owner. Esta herramienta guarda, como antes, la observación `chat_available` en el estado real del usuario: así el selector sigue ocultando los modelos que dan 404.

| | 2026-10-03 | 2026-10-08 |
|---|---|---|
| Modelos en el catálogo | 81 | 80 |
| Disponibles | 17 | **18** |
| 404 en el endpoint de chat | 55 | **55** (los mismos) |
| Sin demostrar | 9 | **7** |

Cambios:
- Ya no está en el catálogo: `nvidia/riva-translate-4b-instruct-v1.1`.
- Pasaron a disponibles: `z-ai/glm-5.3-flash`, `poolside/laguna-xs-2.1` y `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`.
- Pasó de disponible a sin demostrar: `nvidia/nemotron-3.5-content-safety` (timeout).

Los 7 sin demostrar:
- 4 por timeout: `deepseek-ai/deepseek-v4.1-flash`, `meta/llama-guard-4-12b`, `nvidia/llama-3.1-nemoguard-8b-content-safety` y `nvidia/nemotron-3.5-content-safety`;
- `nvidia/ai-synthetic-video-detector`: HTTP 500;
- `nvidia/nemotron-parse`: HTTP 400;
- `nvidia/llama-3.1-nemoguard-8b-topic-control`: stream cortado.

Como en la medición anterior, un 404 en esta cuenta y este endpoint no es una deprecación oficial ni vale para otros endpoints.

## NOT_DEMONSTRATED

- **Corte del lado del servidor, 5xx y 429 reales:** no se pueden provocar a voluntad. C usa un corte del lado del cliente sobre un stream real.
- **Ahorro por caché de prompts** de NIM o de cualquier otro provider: no se midió.
- **La ventana de A1/A2 es simulada.** La activación por ventana real solo quedó demostrada por el camino de rechazo (B).
- **Otros providers:** solo se probó NVIDIA NIM. Anthropic, OpenAI y Groq pueden redactar el rechazo de otra forma.

## Archivos

Sus hashes están en `SHA256SUMS.txt`.

- `canary.py`, `errbody.py`: los scripts que se ejecutaron.
- `canary-A1.json`, `canary-A2.json`, `canary-C.json`, `canary-B-fit-117k.json`, `canary-B-before-fix.json`, `canary-B.json`: un informe por corrida, con tamaño, sha256 y uso de cada request.
- `nvidia-availability-2026-10-08.jsonl`, `catalog-run.log`, `catalog-window-utc.txt`: el catálogo.
