# M19 — Codex TUI/CLI 0.160.0 medido

Fecha: 2026-10-03  
Evidencia: [`docs/product/codex-tui-cli-audit-2026-10-03.md`](../product/codex-tui-cli-audit-2026-10-03.md)

## Estado

Auditoría local terminada. La auditoría comparativa anterior registró Codex 0.155.1; el binario local medido hoy es 0.160.0. Se revisaron CLI, lifecycle de features, schema generado del app-server, tools de control de tareas expuestas al harness y el `CodexConnector` que ya existe en ISyCode.

La TUI alcanzó a renderizar su pantalla inicial, pero la interacción completa quedó `NOT_DEMONSTRATED` porque el sandbox impidió escribir estado bajo el home Codex normal.

## Hallazgo principal

ISyCode ya tiene la frontera correcta en `src/isycode/codex_connector.py`: usa un `CODEX_HOME` propio, arranca `codex app-server --listen stdio://`, deshabilita capacidades nativas con efectos, permite solo un subconjunto explícito del protocolo y devuelve dynamic tool calls a owners de ISyCode.

La sonda contra Codex 0.160.0 real inicializó correctamente con un home limpio y `account/read` indicó no autenticado. No reutilizó la sesión Codex del operador. M19 amplía compatibilidad, observabilidad y lifecycle; no abre el app-server completo.

## Trabajo, en este orden

- [ ] Pin/probar el subconjunto de app-server que consume `CodexConnector` contra el JSON Schema generado por el binario instalado. Cambio incompatible => provider `unsupported`; nunca ampliar allowlist como fallback.
- [ ] Añadir un prompt inspector local/redacted (`debug prompt-input` o equivalente) que enumere system/developer/context/skills/tool schemas, tamaño y truncado sin llamar al provider ni mostrar secretos.
- [ ] Convertir Work en una superficie tipada de tareas vivas: list/read/status/title/fork/archive/unarchive/follow-up/wait. Reusar sesiones, contrato de eventos M17 y Mobile Host; ninguna operación concede grants.
- [ ] Añadir archive/unarchive como lifecycle reversible de conversación. `delete` conserva su owner destructivo, scope exacto, aprobación y receipt.
- [ ] Añadir salida final opcional validada por JSON Schema al headless para automatización/OpenISy. El schema restringe formato; no habilita tools.
- [ ] Añadir `strict config` y un modo reproducible/ephemeral que pueda omitir preferencias cosméticas, pero jamás Authority, Sentinel, owners, grants ni reglas de seguridad.
- [ ] Registrar lifecycle de capacidades (`stable` / `experimental` / `under-development` / `deprecated` / `removed`) separado de disponibilidad y de `ALLOW/DENY`.
- [ ] Mostrar en diagnóstico/receipt un snapshot normalizado del sandbox efectivo: roots, ejecutable, red y límites. Los perfiles son plantillas, no permisos.
- [ ] Para futuras migraciones de sesiones: inspect/dry-run por defecto, apply explícito, reporte por sesión y límite de I/O. No migrar silenciosamente al arrancar.

## Ya cubierto; no duplicar

La cola visible, `/compact`, árbol/fork y contrato de eventos ya pertenecen a M17. También M17 ya contempla exposición `direct/deferred/hidden`; el `tool_search` medido en esta auditoría respalda esa dirección pero no crea otra capa de tools.

`isycode doctor --json`, búsqueda/rename/fork/export/import/delete de conversaciones, pairing de Mobile Host y folders adicionales con grants propios ya existen o tienen milestone. El conector Codex también existe y ya bloquea herramientas nativas.

## No copiar

- bypass de approvals/sandbox;
- ignore-rules como escape de seguridad;
- hooks/plugins como grants;
- shell/filesystem/process del app-server como atajo;
- permission profiles como autoridad;
- worktrees como frontera de seguridad;
- auto-review de Codex como sustituto de Workspace Authority + IsySentinel.

## Criterios de aceptación

- Un upgrade de Codex que rompa el protocolo requerido falla cerrado y explica el campo/método incompatible.
- El prompt inspector funciona offline, redacta secretos y distingue contenido completo de truncado.
- Archive/unarchive no borra receipts ni transcript; follow-up/fork/wait no repiten efectos ni cambian grants.
- TUI, headless y Mobile Host observan el mismo estado de tarea/eventos sin crear un ejecutor alterno.
- Output schema no cambia el catálogo de tools ni la política de owners.
- Feature lifecycle, disponibilidad y autoridad se muestran como dimensiones distintas.
- El snapshot de sandbox describe evidencia de ejecución; nunca se interpreta como autorización.
