# Integración local de ramas de ISyCode

Fecha: 2026-10-03.

Antes de integrar, se conservaron los cambios de ambos checkouts en
`/tmp/isycode-integration-backup-20261003` y en los commits `e317613`
(checkpoint compartido) y `da2adca` (trabajo de Gemini).
`docs/handoff/` conserva sus archivos sin incorporar al commit.

## Decisiones

- `feat/tui-layout-and-ergonomics`: integración real de código. Se conservaron
  historial con restauración del borrador, Ctrl+J/Alt+Enter, escritura de una
  fila y una barra de acciones compacta. Se corrigieron CSS inválido y el
  contenedor horizontal ausente. Idea box usa el estado y las notas del agente.
- El ASCII local de bienvenida y las tarjetas de Multi Harness se conservaron
  del checkpoint compartido. El inicio se archiva al comenzar la conversación;
  leer mensajes antiguos no vuelve a activar el seguimiento automático.
- La barra lateral conserva sus controles en cajas internas, con bordes tenues.
  Providers, Role y Context siguen disponibles desde Settings.
- Las cinco ramas remotas `feat/long-session-stability`, `feat/ordered-chat-steps`,
  `feat/session-continuity-and-usage`, `feat/sibling-workspace-folders` y
  `feat/tui-visual-polish` no tienen patches únicos según
  `git log --right-only --cherry-pick HEAD...<rama>` antes de integrarlas.
  Se registra su ascendencia conservando el código actual.
- `feature/private-tailnet-setup` conserva commits previos a la reorganización
  de rutas. Su funcionalidad entró por PR #1 y recibió correcciones posteriores
  en main: instalación, login, inspección y Serve con owners y contratos.
  Se registra esa rama sin reemplazar las implementaciones actuales por las
  antiguas. Las demás ramas locales/remotas ya eran ancestros del checkpoint.

## Validación

Las 17 pruebas específicas de secuencia de chat, bienvenida y layout pasan.
Suite completa: `python3 -m pytest -q --tb=short` → exit 0, **1223 passed,
6 skipped, 8 warnings** en 171.62 s. Las advertencias son de `fork()`
en el test multiproceso del effect ledger. Salida preservada en
`/tmp/isycode-integration-tests-final.log`, SHA-256
`296559af536fe1d6fff1073977b4d4539b5134dba84f80a343a4cb9a99c0635c`.
La vista previa se exportó desde la TUI real en modo de prueba, a 160×48;
se verificaron también geometría y navegación a 80×24 y 120×40.
El launcher instalado apunta al checkout principal mediante symlink.
No se ejecutaron servicios externos ni generación de imágenes.

Las ideas de Pi están en [pi-inspired-capabilities.md](pi-inspired-capabilities.md).
Son propuestas pendientes y no capacidades entregadas.
