# ADR 0005: Perfil quiet de Classic, sin autonomía falsa

- **Estado:** propuesto en M4. No está revisado por otra persona y no autoriza red, secretos ni el bucle autónomo.
- **Fecha:** 2026-10-02
- **SHA de partida:** `338d25004c023cdf0679ee46941dacd57dca0e9a`
- **Plan:** [roadmap Classic/Security](../roadmap-classic-security-ux.md)

## Contexto

Classic ya concede un preset y sigue pidiendo una aprobación por edición y por comando. M4 pide quitar esa pregunta en el trabajo local ordinario después de un onboarding, sin convertir eso en «todas las tools encendidas». G5 (red y secretos) y G6 (bucle, cancelación y retry) no están hechos. Abrir esas capacidades aquí sería autonomía falsa.

## Decisión

La confianza es un registro fuera del checkout, en `workspace-trust/`, atado al path resuelto y al dispositivo e inodo del root. Hace falta la frase exacta `trust this workspace`, y solo la escribe el gesto humano de la pantalla de onboarding. No hay una acción ni una tool del modelo que la escriba.

Con el registro en `trusted` y el modo Classic vigente, estas acciones no piden aprobación por llamada: listar, leer, buscar, inyectar contexto, escribir, restaurar, borrar, mover y `workspace.command.run` cuando el sandbox resuelve. El ledger, IsySentinel, el journal y las denegaciones explícitas siguen aplicando. Un comando sin sandbox se queda apagado y el texto dice que no hay fallback al host.

Siguen pidiendo su frontera, o se niegan: commit, secretos, credenciales, provider, configuración del workspace, cambios de autoridad, y cualquier acción fuera de esa lista. Security no consulta el registro. Una revocación `enabled: false` gana al momento. Volver a Classic en el mismo root no repite el onboarding. Una copia, un root movido, un directorio reemplazado, una política ilegible o una carpeta amplia no heredan la confianza.

Headless sigue ofreciendo solo lecturas y git status/diff. No usa este perfil para editar sin una persona.

## Qué no hace

No sube el presupuesto. No abre red, MCP, commits ni el bucle del agente. No marca G4 como APROBADO. No convierte el botón «Always allow…» de una carpeta en un permiso permanente de todas las tools; ese camino sigue siendo el de antes y no es este perfil.

## Alternativas rechazadas

- Saltar toda `approval_required` en Classic. Eso apagaría commits, secretos y autoridad.
- Tratar `.isyroot` o `AGENTS.md` como confianza. El marcador es identidad, no un permiso.
- Identidad solo por inodo. Un directorio movido conservaría el inodo y heredaría la confianza; el plan lo rechaza.
- Identidad solo por path. Reemplazar la carpeta en el mismo path heredaría el registro.
- Ofrecer las escrituras en headless porque el gate ya no pide token. Ahí no hay persona en el turno.
