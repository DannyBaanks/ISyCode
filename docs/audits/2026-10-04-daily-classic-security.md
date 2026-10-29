# Auditoría de uso diario: Classic, Security y TUI

Fecha: 2026-10-04. Base: `d9a77df6d37445e5b216ba80e1def74279d11f78` más los cambios locales de esta auditoría.
Entorno: Linux, Python 3.12.3, Textual 8.2.8. Revisión de código y pruebas automatizadas; no certificación de seguridad, revisión independiente ni comparación práctica con Codex/OpenCode.

## Hallazgos y reparaciones

| Severidad | Reproducción | Corrección |
| --- | --- | --- |
| Alta | Activar ediciones automáticas, pasar el workspace principal o adjunto a Security, pedir una edición: se escribía sin revisión. | La delegación exige Classic vigente en ambos roots. Security, ausencia de modo y política ilegible la suspenden. Se reevalúa antes de emitir la aprobación. |
| Alta | Un adjunto confiable en Classic podía omitir el modal desde una conversación principal en Security. | La TUI exige que también el workspace principal esté en Classic antes de omitir el modal. |
| Media | Leer un FIFO del repositorio sin un escritor bloqueaba el hilo de lectura; la reproducción excedió cinco segundos. | La apertura POSIX usa `O_NONBLOCK`; la comprobación existente del descriptor rechaza archivos no regulares sin esperar. |
| UX | Security ofrecía “Always allow” y el menú sugería habilitar automatización incompatible con su revisión por acción. | El flujo de edición oculta esa opción y el menú explica la restricción. Enter sigue rechazando por defecto; Escape cancela. |
| UX | El mensaje de workspace temporal no aclaraba si se podía trabajar sin marcador. | Explica que la carpeta es el workspace, `.isyroot` es opcional y el historial no se guarda. |
| UX | El detalle de una sesión podía quedarse en “…” tras abrir el panel: calculaba la vista previa con dimensiones anteriores al layout. El fallo de la suite se reprodujo individualmente. | El componente de detalles notifica su cambio de tamaño y se recalcula la vista previa seleccionada. |
| Verificación | Un test buscaba literalmente una llamada que una refactorización había sustituido por un owner local ejecutado en un thread. | Se sustituyó esa comprobación textual por una lectura real desde la TUI y una revocación posterior que debe bloquear el contenido. Se conservan las comprobaciones de separación entre presentación y política. |

Las regresiones reprodujeron las escrituras indebidas y el bloqueo FIFO antes de los arreglos. El snapshot de cobertura se regeneró por cambios de líneas, conservando su resumen de 78 acciones y cero acciones sin clasificar. No se habilitan nuevas capacidades de ejecución.

## Qué permite realmente Classic

- Sin marcador propio ni ancestro, la carpeta de arranque es el límite del workspace. Ya era posible leer y editar allí mediante los owners; no se necesita crear `.isyroot` para conceder esos permisos.
- Si existe un `.isyroot` ancestro, se usa ese root: revisar el root mostrado es relevante. El marcador identifica el límite; no concede permisos.
- Classic proporciona el preset. La confianza explícita del root habilita el perfil existente para efectos ordinarios; las revocaciones siguen ganando. El roadmap aún no certifica ese perfil.
- Las carpetas adicionales se adjuntan explícitamente desde Settings → Workspace folders. El producto admite hasta ocho hermanas directas y conserva sus identidades y grants separados. Para delegar ediciones, ambos workspaces deben estar en Classic; adjuntar una carpeta no le cambia el modo.
- El acceso libre a cualquier carpeta del disco **no está implementado**. Ampliarlo exige un diseño de alcance y protección de estado/secretos; una lista de nombres de comandos “raros” no sería una frontera suficiente.
- Los comandos usan Bubblewrap, entorno limpio, aislamiento de red/seccomp y staging con promoción controlada. El argumento es un `argv`, sin expansión implícita de shell. Un intérprete puede ejecutar lógica arbitraria dentro de esos límites; la seguridad depende del aislamiento y de los efectos permitidos.
- Sin sandbox no hay fallback al shell del host. Git, integraciones y destinos externos mantienen sus owners y permisos correspondientes.

## Security y límites restantes

Security necesita grants explícitos y revisión de mutaciones. Pasar desde Classic elimina el preset, pero conserva los grants que la persona haya concedido explícitamente: no equivale a “revocar todo”. La preferencia de edición automática queda suspendida y puede volver a aplicarse al regresar a Classic.

Esta revisión no demuestra seguridad absoluta, ausencia de carreras frente a escritores host concurrentes, ni protección contra secretos arbitrarios almacenados bajo nombres corrientes. Los filtros de nombres sensibles no clasifican todo el contenido de un repositorio. Tampoco se midieron el soak de dos horas, participantes humanos, contraste efectivo del terminal ni uso vivo de todos los proveedores.

Los tests de TUI usan el driver de Textual con proveedores simulados para flujos de teclado, rechazo, cancelación, drafts, menús y tamaños reducidos. No sustituyen una sesión manual prolongada en el terminal del usuario. Persisten varias decisiones de onboarding (recurrencia, modo y confianza), y adjuntar proyectos requiere intervención humana; no se afirma paridad de fricción con otra TUI.

## Evidencia y puertas

Comandos de verificación:

```sh
env -u ISYCODE_STATE_HOME XDG_STATE_HOME=/tmp/isycode-audit-final-xdg python3 -m pytest -q -rs -p no:cacheprovider --tb=short
python3 scripts/validate_gates.py --self-test
python3 scripts/validate_gates.py
git diff --check
```

Los validadores de puertas pasan en modo de revisión histórica y dicen explícitamente que no hay puertas aprobadas. M0–M6 siguen EN REVISIÓN; no se avanza ni aprueba ninguna puerta. Esta reparación de prerrequisitos no acredita G4, G8 ni una release.

La primera ejecución en sandbox se interrumpió tras errores de escritura en el estado del usuario. Otra ejecución con `ISYCODE_STATE_HOME` global terminó con 1369 passed, 7 failed y 6 skipped: seis fallos resultaron del override global incompatible con fixtures que seleccionan `XDG_STATE_HOME`, y uno fue el test textual obsoleto. Las 108 pruebas de las áreas afectadas por el override pasaron al retirarlo. Esas ejecuciones no son la evidencia final del cambio.

Una ejecución posterior detectó `test_sessions_filters_and_details_use_real_selected_row` (1382 passed, 1 failed, 6 skipped). Se reprodujo el fallo aislado y pasó después de corregir la invalidación de layout; no se relajó su comprobación del contenido visible. Las ejecuciones intermedias interrumpidas no se cuentan como suites completas.

Resultados finales: **1385 passed, 6 skipped, 8 warnings**, exit code 0, 212.52 segundos. [Salida completa de pytest](2026-10-04-daily-classic-security-pytest.txt).

- Cinco skips requieren un ISyCo Gateway vivo y uno requiere el runtime sandbox TypeScript no instalado. No se atribuye validación a esas integraciones.
- El test `test_real_bubblewrap_keeps_attacks_inside_staging` y las pruebas de egress del sandbox se ejecutaron; no estuvieron entre los skips. La suite también incluye dobles de Bubblewrap para escenarios unitarios: no todos los tests de comandos son pruebas de aislamiento real.
- Los ocho warnings son de `multiprocessing` con `fork()` desde un proceso multihilo en la prueba de ocho workers del ledger. El test terminó correctamente; la advertencia no equivale a demostrar ausencia de deadlocks en todos los entornos.
- Verificaciones dirigidas adicionales: 35 passed en carpetas/cobertura de autoridad y 21 passed en layout/sesiones/UI. La suite completa final incluye estos escenarios.
- `validate_gates.py --self-test`, `validate_gates.py` y `git diff --check`: exit code 0. No se solicitó ni obtuvo aprobación de puertas.

Los cambios quedan locales, sin commit ni publicación. Para revertir, revisar el diff y retirar únicamente estos cambios; no se migraron ni resetearon las políticas, historiales o archivos del workspace del usuario.
