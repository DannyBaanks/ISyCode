# ADR 0012: GUS Context, memoria de continuidad entre compactaciones

- **Estado:** propuesto. Las decisiones C1–C3 son de Danny (2026-10-23). Todavía no hay código; el primer paso es el experimento MC0.
- **Fecha:** 2026-10-23
- **SHA de partida:** `3470b19` (`main` tras el PR #75)
- **Relacionadas:**
  - [ADR 0009](0009-continuity-capsule.md): la cápsula de continuidad y las tres capas de compactación;
  - [ADR 0011](0011-gus-maintainer.md): GUS Maintainer.

## Contexto

Danny quiere separar el modelo que trabaja del modelo que conserva la continuidad del trabajo.
Hoy el mismo modelo, o el slot `small`, resume el historial viejo en notas narrativas y libres. El ejecutor las recibe como contexto.
El problema no es que el resumen sea feo, sino que puede sonar impecable y haber perdido justo la condición que evitaba romper el proyecto.

Lo que ya existe (ADR 0009):

- **Dentro del turno:** `compact_turn` reemplaza los resultados viejos de herramientas por un texto corto.
- **Entre turnos:** lo que no cabe se resume con el slot `small`, pero solo si es del mismo proveedor que el chat. La compactación automática nunca manda la conversación a un proveedor que no elegiste para ella.
- **Si no hay resumen:** entra la cápsula de continuidad, determinista y sin tokens. Lleva las peticiones del usuario, las notas de herramientas ya redactadas, las tareas, el Idea box y los cambios y comandos con su resultado.
- **Siempre:** la conversación guardada conserva la transcripción completa.

## Decisiones del owner

- **C1 — Consentimiento por workspace.** GUS Context se activa explícitamente en cada workspace. Al activarlo se muestra a qué proveedor y modelo va la conversación. Sin esa activación sigue la compactación actual, con su regla de no mandar la conversación a otro proveedor.
- **C2 — Slot propio.** GUS Context tiene su propio slot de modelo, distinto del de GUS Maintainer, para que cada uno use el modelo que le conviene (ventana grande para memoria, buen modelo de código para mantener).
- **C3 — Experimento primero.** Nada se integra antes de medir (MC0).

## Decisión propuesta

1. **Dos perfiles con el mismo nombre.**
   - *GUS Maintainer* (ADR 0011) mantiene ISyCode en una rama.
   - *GUS Context* mantiene la continuidad de cualquier conversación, en cualquier workspace donde se active. La restricción D3 del ADR 0011 no aplica aquí.

   No comparten slot (C2), permisos ni transcripción.
2. **Cero acciones.** GUS Context no recibe ninguna acción de workspace, Git, red ni integraciones. Lee lo que ISyCode le entrega y devuelve datos.
   - Su salida es texto escrito por un modelo: nunca es una decisión del usuario, una aprobación ni un grant.
   - Lleva la misma cabecera de «datos no confiables» que la cápsula.
3. **Registro de continuidad, no resumen libre.** Cada compactación produce un registro estructurado con secciones fijas:
   - `DEMOSTRADO`: hechos con referencia a un recibo del journal o a un SHA;
   - `DECIDIDO`: decisiones del usuario, citando el mensaje donde las tomó;
   - `PENDIENTE`;
   - `BLOQUEOS`;
   - `NO DEMOSTRADO`;
   - `PRÓXIMA ACCIÓN`.

   Cada entrada lleva su referencia al historial original.
4. **ISyCode verifica lo que se dice demostrado.** Una entrada en `DEMOSTRADO` solo se conserva si su recibo o su SHA existe y ISyCode lo puede verificar. Si no, pasa a `NO DEMOSTRADO`. Una entrada en `DECIDIDO` debe citar un mensaje del usuario que exista. La interpretación del modelo nunca sube de categoría por sí sola.
5. **Recuperación por tarea.** El ejecutor recibe solo la parte del registro relevante para su tarea, con referencias para volver al historial, los commits y los recibos. La ventana de GUS Context no es el almacenamiento: el registro y la transcripción completa sí lo son.
6. **Sin consentimiento, nada cambia.** Si GUS Context no está activado, o su slot está vacío o no cumple, la compactación se comporta como en el ADR 0009.

## Plan

| Hito | Trabajo | Puerta |
| --- | --- | --- |
| **MC0** | Experimento (abajo) | Resultado medido y revisado por Danny; decide si se sigue |
| **MC1** | Slot `context` y activación por workspace (C1, C2) | Sin activación no sale nada; la activación nombra proveedor y modelo |
| **MC2** | Registro de continuidad y verificación de `DEMOSTRADO`/`DECIDIDO` | Ninguna entrada sin referencia verificable queda como demostrada o decidida |
| **MC3** | Recuperación por tarea para el ejecutor y los subagentes | La petición nunca excede la ventana del ejecutor; las referencias resuelven |

## MC0 — Experimento

Pregunta: ¿un registro de continuidad hecho por GUS Context conserva más de lo que importa que el `/compact` actual, sin inventar?

- **Corpus.** Conversaciones de desarrollo largas, con hechos sembrados y su verdad conocida:
  - decisiones del usuario;
  - pruebas que fallaron y su causa;
  - pruebas que pasaron, con su comando;
  - restricciones («no toques X», «no hagas push»);
  - pendientes;
  - rutas e identificadores exactos;
  - una afirmación del modelo que nunca se demostró.
- **Brazos.**
  - (a) `summary_messages` actual con el slot `small`.
  - (b) registro de GUS Context.

  Los dos con varias compactaciones seguidas sobre la misma conversación.
- **Medición.** Un ejecutor nuevo recibe solo el resultado de cada brazo y responde preguntas fijas. Se mide:
  - qué fracción de cada categoría sobrevive;
  - cuántas restricciones se pierden;
  - cuántas cosas se inventan: decisiones que el usuario no tomó, o pendientes que aparecen como hechos;
  - cuántas afirmaciones no demostradas quedan como demostradas;
  - el costo en tokens.
- **Criterio.** Inventar decisiones o promover lo no demostrado cuenta como fallo, aunque el brazo recuerde más. El umbral para seguir se fija con Danny al ver los números, no antes.
- **Límite honesto.** El experimento necesita proveedores reales. El arnés y la puntuación se prueban sin red; los resultados con modelos solo cuentan cuando se corren de verdad y se guardan con el SHA y los modelos usados.

## Consecuencias

- Con C1, la regla de privacidad del ADR 0009 sigue siendo el comportamiento por defecto. Mandar la conversación a otro proveedor es una elección explícita y visible.
- GUS Context agrega costo de tokens por compactación. El experimento lo mide antes de decidir.
- El registro estructurado y su verificación sirven aunque se use un solo modelo: es mejor memoria de ingeniería que un resumen libre.
