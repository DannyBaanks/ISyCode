# ADR 0011: GUS, el modelo mantenedor de ISyCode

- **Estado:** aceptado por Danny el 2026-10-23 (hito MK0). Aceptar el ADR no aprueba ninguna puerta `GK`; cada puerta se evalúa con evidencia ligada a un SHA.
- **Fecha:** 2026-10-23
- **SHA de partida:** `e5ab364` (`main` tras el PR #73)
- **Plan:** [roadmap de GUS](../roadmap-gus.md)
- **Decisiones del owner:** D1–D4 resueltas el 2026-10-23 (ver «Decisiones»).

## Contexto

Danny quiere un modelo dedicado a mantener, actualizar y reparar ISyCode: pedirle «agrega esto a ISyCode» y que lo haga sin romper nada, con el contexto del proyecto ya establecido.
La referencia es GUS de ISyCo-Worlds.
Ahí el rol vive en un archivo con permisos en el frontmatter, el loader se niega a cargarlo si pide más de lo aprobado, tiene proveedor/modelo/key propios y su salida es inerte hasta que una persona la aprueba.

Hoy en ISyCode:

- Los roles del catálogo se envían como contrato de guía con cada mensaje y no conceden nada.
- Existe un solo slot de modelo opcional, `small`, que se usa para compactar. Las API keys se guardan por proveedor, no por slot.
- La compactación tiene tres capas (ADR 0009):
  - recorte de resultados viejos de herramientas dentro del turno;
  - resumen o cápsula automática entre turnos;
  - `/compact` manual.

  Nada queda fijado: lo que no cabe se resume o se condensa.

## Decisiones

- **D1 — Alcance: edita en su rama.** GUS edita archivos y corre tests en el sandbox sin preguntar, pero solo dentro de una rama propia. Las rutas protegidas siempre piden revisión humana. Nada llega a `main` ni se publica sin Danny.
- **D2 — Credencial: otro proveedor o modelo local.** El slot de GUS elige proveedor y modelo, incluidos `ollama`, `lmstudio` y `llamacpp`, y usa las keys por proveedor que ya existen. No se agrega una key por slot, así que no se toca el manejo de credenciales (ADR 0006).
- **D3 — Workspace: solo el repo de ISyCode.** GUS se ofrece únicamente cuando el workspace es el repo de ISyCode. Su contexto fijo sale de archivos de ese repo.
- **D4 — Nombre: GUS.** Mismo nombre que en ISyCo-Worlds. Son productos y repos distintos y no comparten código ni estado.

## Decisión

1. **Rol, no autoridad.** GUS es un rol declarado en `src/isycode/agents/gus.md` con permisos en el frontmatter.
   El loader rechaza el rol si declara acciones fuera de su política: push, credenciales, provider/configuración, autoridad, modo, integraciones o red para comandos.
   Con GUS activo, Workspace Authority, IsySentinel, owners, effect ledger y journal deciden exactamente igual que sin él.
2. **Rama propia.** GUS solo edita si el checkout está en una rama `gus/<tema>`; en cualquier otra rama, sus ediciones piden aprobación.
   Hoy el owner de Git solo tiene `git.status`, `git.diff`, `git.commit` y `git.push`, y no crea ramas.
   MK5 agrega una acción propia para crear y cambiar a una rama `gus/*`, siempre con aprobación. Hasta entonces, la rama la crea la persona.
   Sus ediciones y comandos son las mismas acciones que Flow ya ejecuta sin preguntar, y quedan en el `TurnJournal`. GUS nunca hace push.
3. **Rutas protegidas.** Un cambio en cualquiera de estas rutas pide aprobación siempre, también en Flow:
   - `security.py`, `workspace_authority.py`, `actions.py`, `action_runtime.py`, `approvals.py`, `action_audit.py`;
   - los owners;
   - las pantallas de aprobación;
   - `docs/decisions/`, `docs/security/` y `AGENTS.md`.

   La lista vive en código con una prueba que la fija.
4. **Contexto fijo fuera de la compactación.** Cada turno lleva un paquete de contexto leído por un owner de lectura con recibo y digest:
   - `AGENTS.md`;
   - el `SKILL.md` de diseño;
   - el estándar visual;
   - el índice de títulos de ADR.

   Se envía como el contrato de rol y se descuenta del presupuesto de historial antes de compactar. La compactación y la cápsula solo tocan la conversación.
   El registro privado `vicios-tecnicos` no entra: es otro repo y D3 limita el contexto al repo de ISyCode.
5. **Ventana mínima de 32k tokens.** Medición en `bd1da4b` sobre el paquete candidato: 14 284 caracteres, unos 3 600–4 800 tokens.

   | Ventana del modelo | Presupuesto de historial | El paquete ocupa |
   | --- | --- | --- |
   | 8 192 | 24 000 caracteres (mínimo fijo) | 60 %; además, el mínimo ya excede media ventana |
   | 32 768 | 49 152 caracteres | 29 % |
   | 131 072 | 196 608 caracteres | 7 % |

   Con una ventana conocida menor de 32 000 tokens, el slot no se guarda y lo dice; el umbral deja pasar los modelos de 32 000 y de 32 768. Con una ventana desconocida, se aplica el supuesto de 128k de la cápsula y se avisa.
   Tampoco se guarda un modelo que el catálogo marca sin tool calls: GUS edita mediante herramientas.
6. **No es L1.** L1 (`l1.py`, acciones `l1.*`) es el pipeline con puertas para herramientas escritas por el modelo, donde crear una herramienta no la activa ni la concede.
   GUS no crea herramientas: cambia el código de ISyCode en una rama con las acciones de workspace y Git que ya existen.
   Su rol no puede pedir acciones `l1.*`.
7. **Conversación propia.** GUS guarda su transcripción aparte del chat, con tope, como en ISyCo-Worlds. No se crea un sistema de lanes nuevo.

## Consecuencias

- No hay superficie nueva de credenciales ni de red. El costo está en el rol, el slot, el paquete de contexto y la lista de rutas protegidas.
- Un modelo local chico (menos de 32k) no sirve para GUS. Es preferible a uno que olvide el contexto a mitad del trabajo.
- La rama propia aísla el trabajo de GUS del de la persona. Integrarlo sigue siendo una revisión humana normal.

## Pendiente

- `GK0-01` y `GK0-02` se evalúan con evidencia en `docs/evidence/gus/MK0/<sha>/`. Publicar este ADR no las aprueba.
