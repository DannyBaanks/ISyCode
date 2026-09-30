# Handoff para Claude Code: segunda revisión de ISyCode

Hola Claude. Queremos una segunda mirada independiente y crítica al estado actual de ISyCode. La idea es que revises nuestras hipótesis como cuando el proyecto apenas nacía: busca fallos y supuestos débiles, aunque contradigan lo que Danny, Codex o tú mismo hayamos propuesto antes.

## Checkout y referencias

Este handoff está guardado en la rama `feature/private-tailnet-setup`.

- Línea principal publicada: `master` en `60acea2` — cierre de superficies de autoridad M15 y preferencias globales del usuario.
- Línea de acceso privado publicada: `feature/private-tailnet-setup` — configuración guiada de acceso privado con Tailscale y simplificación visual de los permisos.
- Ambas ramas comparten una base anterior, pero siguen separadas a propósito. No las fusiones ni hagas rebase durante esta revisión. Lee las dos referencias y compáralas; los archivos de TUI y seguridad tienen cambios relacionados en ambas.

## Tu tarea

Haz una **revisión de solo lectura**. No edites archivos, no reformatees, no instales dependencias, no ejecutes servicios ni cambies permisos. Primero inspecciona las instrucciones del repo (`AGENTS.md` y documentos aplicables), luego revisa las diferencias de ambas ramas contra su base común y sigue los flujos relevantes hasta sus puntos de entrada y pruebas.

Evalúa especialmente:

1. **Autoridad y seguridad:** IsySentinel debe seguir siendo deny-by-default. `.isyroot` descubre e identifica el workspace; no concede autoridad. Los defaults globales son preferencias de usuario, no grants. Las credenciales no deben aparecer en logs, exportaciones ni handoffs.
2. **Acceso remoto:** Tailscale debe permanecer privado y opt-in. Comprueba pairing, expiración, autenticación, scopes y validación en cada operación. No des por demostrado que un test simulado prueba un flujo real de red o dispositivo.
3. **Permisos comprensibles:** la UI debe mostrar estados ON/OFF simples, pero la representación amigable no puede ocultar scopes, denegaciones ni pedir menos confirmación de la que exige el motor.
4. **Separación global/workspace:** los defaults de usuario deben sobrevivir al cambio de carpeta; la autoridad, sesiones y estado ligado a workspace no deben trasladarse accidentalmente a otra ruta.
5. **M15 y evidencia:** comprueba que el inventario versionado, los owners de acciones y los receipts correspondan al runtime real. Señala todo estado `NOT_DEMONSTRATED` que la documentación o la UI pudiera presentar como hecho probado.
6. **Calidad de producto:** flujos de inicio, selección de provider/rol, Files, sesiones y Settings. Busca errores de teclado/mouse, cancelación, estados vacíos y caminos sin salida.

## Formato del resultado

No cambies código. Devuelve un informe corto y priorizado:

- Hallazgos `P0`/`P1` primero, con archivo y línea, escenario de explotación o fallo y evidencia reproducible.
- Después `P2`/`P3` de UX, compatibilidad o mantenimiento.
- Distingue claramente **demostrado**, **inferido** y **no demostrado**.
- Si no encuentras hallazgos, explica qué superficies inspeccionaste y qué límites impiden afirmar una seguridad completa.
- Cierra con una recomendación: qué conviene corregir antes de combinar las dos líneas y qué puede quedar para después.

No intentes agradarnos ni confirmar decisiones previas: una revisión que encuentre una hipótesis rota es un buen resultado.

## Evidencia local previa

Antes de este handoff se reportó que la suite completa pasaba en ambos checkouts: 173 pruebas en `master` y 328 en la rama privada. La cobertura de tests no demuestra por sí sola pairing real, transporte Tailscale ni operación desde un iPhone. Revisa los comandos y resultados disponibles si necesitas validar qué se ejecutó.
