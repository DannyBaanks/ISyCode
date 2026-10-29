# ADR 0014: el freeze — pulir de punta a punta lo que existe

- **Estado:** aceptado. El plan es decisión de Danny (2026-10-23); este ADR lo registra tal como quedó en el [handoff](../handoff/gus-mk6-freeze-2026-10-23.md) (§3.4 y §4).
- **Fecha:** 2026-10-24
- **Referencia:** el freeze está definido en [ROADMAP §FS](../ROADMAP.md); el modelo L0/L1 y la activación por merge de Danny están en el [ADR 0013](0013-gus-l1-l0.md).

## Contexto

Danny decidió el 2026-10-23 terminar primero la lista de GUS (MK6 y MC0) y después mantener un periodo de **freeze**: no se agregan features; se pule de punta a punta lo que ya existe. La suite hermética supera las 2,400 pruebas y el CI corre en Linux, Linux con Textual 8, Windows, y empaqueta en las tres plataformas; el freeze existe para que ese estado se vuelva confiable en vez de crecer.

## Decisión

Durante el freeze solo entran **arreglos, pruebas y documentación**, con estas reglas:

1. **Cada bug arreglado trae su prueba** — la prueba que fallaba antes del arreglo va en el mismo cambio.
2. **GUS también lo respeta.** Este ADR entra solo en su paquete de contexto (el índice de títulos de `docs/decisions/` lo incluye); en el freeze GUS trabaja en L1 y acepta lo mismo: arreglos, pruebas, textos y traducciones — nada de features.
3. **CI más rápido (primer PR del freeze):**
   - una corrida por commit — `push` solo en `main`, no en todas las ramas;
   - `timeout-minutes: 30` en los jobs de Linux (uno llegó a colgarse 3 h);
   - medir la suite con `pytest --durations=30`;
   - después evaluar `pytest-xdist -n auto`, revisando que las pruebas de TUI no compartan estado.
4. **Inventario de lo que existe** con su estado: estable, frágil o sin pruebas.
5. **Matriz E2E:** modos (Classic, Flow, Security), proveedores (incluido uno local), plataformas (Windows, Linux, macOS), idiomas (en, es, zh), tamaños (80×24, 100×30, 140×40), fallas de red y carpetas adicionales.
6. **Cacería de bugs en orden:** primero seguridad, después datos (perder texto o historial), después UI.

## Consecuencias

- La deuda en L0 (pantallas de aprobación, owners, CI, este mismo ADR) la cambian Danny o una sesión normal, nunca GUS; el handoff lo deja dicho y se mantiene.
- El freeze no relaja las puertas existentes: los grants, el sandbox, el SEAM y las aprobaciones siguen igual, y cada cambio pasa por el CI completo.
- Salir del freeze lo decide Danny. Activar lo pulido sigue siendo su merge; el rollback sigue siendo revertir ese merge (ADR 0013, L2).
- El ADR del freeze, el inventario y la matriz E2E son documentación del producto pulido, no features.
