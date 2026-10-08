# MCP local en real: preset `context7` (2026-10-08)

- **Autorización:** Danny Baanks, 2026-10-08 ("VALE SIGAMOS CON EL MCP").
- **Entorno:** Ubuntu 24.04, Node 24.21.0, npm 11.19.0, Python 3.12.3, Textual 8.2.8. ISyCode en `main` (`8b6653c`); detalles en `environment.txt`.
- **Script:** `mcp_witness.py`. El resultado está en `mcp-witness-context7.json`.

## Qué fue real y qué no

**Real:**
- la descarga npm del paquete fijado `@upstash/context7-mcp@4.1.1` (no estaba en la caché de npx);
- el proceso del servidor y su handshake JSON-RPC por stdio (`initialize`, `tools/list`);
- `tools/call`, que llega al servicio context7 por la red;
- `LocalMCPOwner`, Workspace Authority, IsySentinel, las ventanas de aprobación de la TUI y el journal.

**Simulado:** solo el modelo de chat. Se le indica que pida la herramienta MCP, para que lo que se prueba sea el servidor y no un provider. No se gastaron tokens.

El estado de ISyCode (preferencias, `mcp.json`, grants y journal) vivió en un directorio temporal.

## Resultados

| Paso | Qué pasó | Resultado |
|---|---|---|
| `/mcp add context7` | Escribe el preset fijado en el `mcp.json` privado. No arranca nada. | PASS |
| `/mcp start context7` | Pregunta dos veces: el permiso del servidor (`TailscaleConfirmScreen`) y el comando exacto (`LocalMCPConfirmScreen`). Las dos se aprobaron con `y`. | PASS. Descargó, arrancó y completó el handshake en **16,1 s**, con 2 herramientas: `resolve-library-id` y `query-docs`. |
| Llamada rechazada (`n`) | El modelo pidió `mcp__context7__resolve-library-id`. | PASS. El modelo recibió `{"status": "rejected_by_user"}` y **no hubo decisión ni recibo `mcp.local.invoke`**: nada llegó al servidor. |
| Llamada aprobada (`y`) | La misma llamada (`libraryName: textual`). | PASS. Respuesta real de 1 731 caracteres (sha256 `a25e9653…`) que empieza con `Title: Textual`, `Context7-compatible library ID: /textualize/textual`; `is_error: false`. |
| Después de `stop` | El modelo vuelve a pedir la herramienta. | PASS. Ya no se le ofrece ninguna `mcp__*` y la llamada responde "that MCP tool is not available". |
| Journal | `verify()` | **PASS.** 14 decisiones, 13 recibos. Para MCP: `mcp.local.start` ALLOW + recibo, y `mcp.local.invoke` ALLOW + recibo, solo de la llamada aprobada. |

## NOT_DEMONSTRATED y riesgos

- **Timeout de arranque de 30 s** (`START_TIMEOUT_S`) que incluye la descarga npm. Aquí tardó 16,1 s. En una red lenta o con un paquete grande, el primer arranque puede fallar con "handshake failed"; el segundo arranca con la caché. No se midió en red lenta.
- **Preset `playwright`:** no se probó, porque necesita navegadores además del paquete npm.
- **Un modelo real eligiendo la herramienta:** no se probó, porque el modelo fue simulado. Que el modelo vea la herramienta ya está cubierto por la suite.
- **Límites del servicio context7** sin clave (`service limits apply`): no se midieron.

## Archivos

Sus hashes están en `SHA256SUMS.txt`.

- `mcp_witness.py`: el script que se ejecutó.
- `mcp-witness-context7.json`: los eventos y las ventanas de aprobación, con la tecla usada en cada una.
- `environment.txt`: las versiones del entorno.
