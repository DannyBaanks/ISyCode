# Handoff: GUS MK6, MC0 y freeze (2026-10-23)

Para la siguiente sesión. Danny decidió terminar toda la lista de GUS (MK6 y MC0) y después entrar en **freeze**: no se agregan features hasta pulir de punta a punta lo que ya existe.

## 1. Estado de los PRs

| PR | Contenido | Qué falta |
|---|---|---|
| **#81** | GUS completo: MK4 y MK5a–d. La cadena #82–#86 ya se mergeó dentro de su rama `claude/gus-mk4-button` | CI en verde, y Danny lo mergea con **"Create a merge commit"**, no squash |
| **#80** | ADR 0013 (GUS en L1, conoce L0) | Solo documentación y es independiente; se mergea cuando esté en verde |
| ya en `main` | MK0–MK3 (#75–#77, #79), ADR 0012 (#78) | — |

Si `main` avanza, a #81 y #80 se les trae `main` (merge, nunca rebase) y se espera CI.

## 2. Qué hace GUS hoy (después de #81)

- `/gus` o el botón GUS abre su ventana. Se habilita por workspace, solo en el repositorio de ISyCode.
- `/gus branch <tema>` crea `gus/<tema>`, siempre con aprobación. Guarda el commit base y la huella de L0.
- **En una rama `gus/*`, GUS edita con sus herramientas sin preguntar.**
  - Sus herramientas: leer, editar, borrar, mover, comandos en sandbox y git status/diff/commit.
  - `GusL0Boundary` (IsySentinel) rechaza L0 y todo lo que esté fuera de su rol, también en la promoción de comandos.
  - Cada turno queda en un `TurnJournal`, así que `/undo` lo deshace.
  - La huella de L0 se compara antes y después del turno; si cambió, el turno se deshace solo.
- `/gus seal` corre V/T/A/L/S y sella o rechaza la generación. La evidencia queda en el estado privado.
- Activar el trabajo de GUS es el merge de Danny.

Las referencias son el roadmap (`docs/roadmap-gus.md`, sección MK5) y los ADR 0011, 0012 y 0013. Hay una enmienda al ADR 0010: Classic también concede deshacer un turno, y pregunta antes.

## 3. Lo que sigue

### MK6: SEAM de GUS y dogfood

**SEAM.** Auditoría con roster fijo y evidencia encadenada (SHA-256 por caso, como el SEAM de OpenISy; ver ADR 0013, punto 5). Cada caso debe terminar en *deny* o *ask*, nunca en *grant* (GK6-01). Casos:

1. Escritura directa a L0.
2. L0 por un comando en el sandbox.
3. L0 por symlink o hardlink.
4. L0 por movimiento o borrado, incluida una carpeta que contiene L0.
5. Un cambio L1 que llama una API directa saltándose un owner (lo detecta la puerta A).
6. Inyección en un archivo del paquete de contexto.
7. Salirse del workspace.
8. Leer credenciales.
9. Cambiar de modo a mitad del turno.
10. Un mensaje más grande que la ventana.

Varios ya tienen pruebas sueltas (`test_gus_guard.py`, `test_gus_work.py`, `test_gus_context_pack.py`, `test_gus_session.py`). El trabajo es juntarlos en un runner con roster fijo, cadena de evidencia y un reporte. Caso nuevo a probar en particular: cambiar a Security a mitad de un turno de GUS tiene que volver a preguntar o negar.

**Dogfood.** Al menos 5 cambios reales a ISyCode hechos con GUS, con un proveedor real y revisados por Danny, sin regresiones (GK6-02). Necesita a Danny presente.

### MC0: experimento de GUS Context (ADR 0012)

Arnés probado sin red que compara el registro de continuidad (DEMOSTRADO, DECIDIDO, PENDIENTE…) contra el `/compact` actual. El umbral para seguir se fija con Danny al ver los números.

### Freeze (después de MC0)

Plan aceptado por Danny. Durante el freeze solo entran arreglos, pruebas y documentación, y cada bug arreglado trae su prueba.

1. **ADR del freeze** con esa regla.
2. **Acelerar el CI**, primero lo barato:
   - `ci.yml` corre dos veces por commit (`push` en `**` y `pull_request`); que `push` corra solo en `main`;
   - `timeout-minutes` en los jobs de Linux (uno quedó colgado 3 h);
   - medir con `pytest --durations=30`;
   - después evaluar `pytest-xdist`.
3. **Inventario** de lo que existe: estable, frágil o sin pruebas.
4. **Matriz E2E:**
   - modos: Classic, Flow y Security;
   - proveedores, incluido uno local;
   - plataformas: Windows, Linux y macOS;
   - idiomas: en, es y zh;
   - tamaños de terminal;
   - fallas de red;
   - carpetas adicionales.
5. **Cacería de bugs:** primero seguridad, después datos, después UI.

## 4. Deuda conocida (para el freeze)

- **Foco de diálogos.** La familia `ApprovalScreen` (`tui_screens_approval.py`, incluida `CommitApprovalScreen`) enfoca el primer botón solo en `on_mount`. Es la misma carrera que colgaba CI: Textual puede mover el foco al cuerpo con scroll. Se arregla con `AUTO_FOCUS`, como ya tienen `AutomaticEditsWarningScreen`, `GusScreen` y `GusBranchApprovalScreen`.
- **Pruebas con tiempos ajustados.** Ya se arreglaron 8:
  - foco de la advertencia;
  - doble clic en `CopyTextArea`;
  - doble clic en las cajas;
  - scroll del chat (dos);
  - detalle de la lista de conversaciones;
  - plazo de `map_ordered`;
  - animación de Home.

  El patrón: una sola pausa o una cota de reloj que un runner cargado no cumple. Hay que esperar la condición, no el tiempo. Dos de los ocho eran bugs reales de la app: el doble clic y `map_ordered`.
- **Sellar requiere un sandbox con dependencias.** Las puertas T y A corren con el Python del sistema dentro de bwrap; si le faltan pytest, rich o textual, quedan `NOT_RUN`. Además el tope de un comando es 600 s, así que la suite completa la corre CI.
- **`provider_supports_tools`.** Su docstring está desactualizado: Ollama sí soporta herramientas.

## 5. Notas para trabajar en el contenedor

- Correr las pruebas sin proxy: `env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy python -m pytest`.
- En este contenedor fallan unas 25–27 pruebas por el sandbox, bwrap y proxy. Compara contra esa lista antes de culpar a un cambio. La prueba `test_a_real_command_in_a_gus_turn_cannot_promote_an_l0_change` solo pasa en CI de Linux.
- **Snapshot m15.** Se regenera con `json.dumps(action_coverage.authority_coverage_snapshot(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"`. Sin `sort_keys` el diff es enorme.
- **Pin del manifiesto.** `tests/test_gus_l0.py::PINNED_MANIFEST` cambia cuando cambia L0. El manifiesto y su prueba son L0.
- **`TUIApp`** está en 88 métodos con un contrato de 80; no debe crecer. Los métodos nuevos van en mixins (`tui_app_gus.py`).
- **Cadenas de PRs:**
  - para cerrarlas, se mergean de arriba hacia abajo en sus ramas base, **una por una** (en paralelo se cruzan);
  - el de abajo entra a `main` con merge commit;
  - `main` exige que la rama esté al día ("behind").
