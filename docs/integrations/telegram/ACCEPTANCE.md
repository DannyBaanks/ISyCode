# Continuación y aceptación local — rama feat/telegram-native-service

Estado: implementación local del camino principal, con aceptación hermética focalizada; **no aprobado como release ni desplegado**.

Se recuperó la rama del agente anterior en el worktree `/tmp/isycode-telegram-native`, sin modificar el checkout de uso diario. Se completaron persistencia, grants, revisión, transporte, sesiones nativas, scheduler, CLI de configuración/servicio y renderización agrupada. Los commits previos del agente y el diseño aprobado se conservaron. El código reutiliza los owners nativos; no revive el bot legado.

## Evidencia

- `evidence/regressions.txt`: regresión ampliada de runtime, herramientas, Telegram, sesiones, permisos, comandos, Git, launcher y escritura TUI. Ejecutada antes del último ajuste de progreso.
- `evidence/final-focused.txt`: ejecución final de los módulos Telegram, runtime, herramientas y dos verificadores de cobertura (snapshot y límites de owner).
- `evidence/progress.txt`: ejecución posterior al agrupamiento del progreso y orden de reintento.
- `evidence/commands.txt`: comandos, entorno y revisiones comprobadas.
- `evidence/sha256.txt`: hashes de los logs y fuente del mapa de cobertura.

Las pruebas usan estado aislado y no llaman a un bot real ni a un proveedor real. El comando de prueba en Flow se ejecutó en un workspace temporal explícitamente configurado para el fixture. Los tests de escritura/edición comprueban bytes reales y recibos.

## Pendiente de aceptación completa

- Ejecutar una baseline realmente inmutable y la suite hermética completa sobre el HEAD final. El log del agente anterior `/tmp/isycode-telegram-native-baseline.log` es una corrida mezclada con cambios durante la ejecución (no es baseline limpia): registró un timeout en `test_e2e_matrix` Classic y una aserción de código fuente en `test_workspace_write_tui`, esta última cubierta por la regresión focalizada posterior. El intento previo del verificador completo de cobertura excedió el timeout de 30 segundos; los verificadores focalizados sí pasan. No se ocultan esos fallos ni se declara una suite global verde.
- Revisar paridad integral de contexto/compacción y loop de TUI/headless; probar reapertura visual en Textual, no sólo a través de ChatSessionOwner. Completar las pruebas de modos, recuperación y adaptaciones opcionales que exija el diseño. No hay revisión independiente por otro modelo de toda la rama ni aprobación formal de release.
- Completar prueba real de emparejamiento/proveedor/keyring, compatibilidad Windows/macOS y despliegue de servicio sólo con autorización separada. No se inició servicio, no se usaron credenciales reales ni se publicaron commits.

No modificar los logs históricos para aparentar una aceptación completa. El plan y spec aprobados permanecen como checklist de cierre.
