# Informe consolidado de auditoría — ISyCode

- **Fecha de consolidación:** 19 de octubre de 2026
- **Proyecto:** `DannyBaanks/ISyCode`
- **Corte revisado:** `87b58ea` (`main`, merge local de `74218e3`)
- **Alcance:** integrar las auditorías disponibles, distinguir lo corregido de lo pendiente y registrar la evidencia de la reparación de navegación/búsqueda en repositorios grandes.

> **Vigencia (19-10-2026):** este documento conserva el estado del corte `87b58ea`. [PR #62](https://github.com/DannyBaanks/ISyCode/pull/62) (`c033d82`) y [PR #63](https://github.com/DannyBaanks/ISyCode/pull/63) (`1095ad1`) se integraron a `main` después de ese corte. #62 incorporó validación de IDs/remitentes, rechazo de rutas enlazadas y límites de ejecución Hive, además de regenerar el snapshot M15; #63 atendió hallazgos de permisos de TUI y sincronizó líneas del snapshot. Por ello, los P1 abiertos aquí describen `87b58ea`, no el estado actual de `main`. Esta actualización no repitió los probes de explotación contra `1095ad1`. Los resultados de OSV y de la heurística de secretos también pertenecen al corte `87b58ea`. El arreglo TUI incluido en esta PR se portó desde `74218e3`: sus 52 pruebas focalizadas pasaron en el corte original, pero no se volvieron a ejecutar después del port; la CI de esta PR debe validarlo.

## 1. Resumen ejecutivo y estado

La auditoría de arquitectura, seguridad y dependencias ya está consolidada para `87b58ea`. El escaneo OSV no encontró avisos conocidos en tres conjuntos de dependencias; la heurística aplicada a archivos rastreados no encontró patrones comunes de secretos; y se registraron los controles presentes y las limitaciones del análisis. Esto **no cierra la evaluación de seguridad**: en `87b58ea` estaban abiertos tres hallazgos de severidad alta en Hive (rutas derivadas de mensajes no confiables, escape por symlink y lanzamiento de subprocess sin owner de ejecución). PR #62 incorporó después cambios para esos límites; esta actualización no repitió sus probes sobre `main`.

### Trabajo de código completado

La reparación de truncamiento de la TUI y búsqueda en repositorios grandes quedó en el commit `74218e3` y se integró localmente a `main` en `87b58ea`. El cambio amplía el recorrido ordenado por niveles, excluye directorios de dependencias/worktrees, eleva límites de exploración, conserva JSON válido al truncar y ajusta el descubrimiento de repositorios hijos.

La verificación focalizada registrada para esa reparación fue:

- `python3 -m pytest tests/test_git_owner.py tests/test_hive.py tests/test_model_button.py tests/test_workspace_grep.py` — 52 aprobadas.
- `git diff --check 594050e..87b58ea` — sin errores.
- `74218e3` es ancestro de `87b58ea`.

En el corte de código `87b58ea`, la rama local estaba 2 commits adelante y 1 detrás de `origin/main`; no se hizo push. Este dato describe ese corte, antes de guardar localmente el informe y su evidencia. Las pruebas anteriores verifican la reparación focalizada; no son una validación de los hallazgos de Hive ni de toda la aplicación.

### Alcance y límites

La auditoría de seguridad/dependencias de este informe se ejecutó sobre el corte local `87b58ea`; guardó comandos, entorno, requirements resueltos, salidas JSON y hashes. Se verificaron los 11 archivos del manifiesto SHA-256 y todos coincidieron. No se ejecutaron pruebas nuevas, la suite completa, workflows CI, proveedores reales, OAuth, Gateway, credenciales reales ni infraestructura externa. Las tres fallas de Hive fueron reproducidas en una auditoría previa sobre `594050e`; como la reparación posterior no está en `87b58ea`, aquí se mantienen abiertas sin volver a afirmar una reproducción en este corte.

## 2. Arquitectura observada

- **Autoridad y decisiones:** Workspace Authority administra grants por workspace; IsySentinel aporta decisiones deny-by-default; `ProductActionGate` valida solicitudes y los execution owners realizan las acciones autorizadas. Las credenciales y los providers no son grants.
- **Efectos y auditoría:** los owners y adaptadores aíslan lectura, escritura, Git y comandos; los journals/ledgers registran resultados. La implementación depende de límites y cobertura correctos por owner.
- **Interfaz:** CLI/TUI construida sobre Textual. `TUIApp` compone varios mixins para sesiones, chat, providers, workspace, permisos, herramientas y rail. La separación ayuda a ubicar responsabilidades, aunque existe acoplamiento entre mixins y módulos extensos.
- **Proveedores y continuidad:** adaptadores para providers, transporte de streaming, sesiones y recuperación de turnos.
- **Hive:** coordinación local de agentes por inbox/outbox, router, hooks y lanzamiento de procesos. La superficie de lanzamiento y sus límites de escritura tienen hallazgos de seguridad aún abiertos; la existencia de Sentinel en otras rutas no los resuelve por sí sola.

## 3. Seguridad y dependencias

### Dependencias y secretos

`pip-audit 2.10.1` consultó OSV sobre las dependencias instaladas en el `.venv` local (42), una resolución Linux/Python 3.10 con todos los extras (56) y una resolución Windows/Python 3.12 con todos los extras (47). El resultado fue 0 avisos conocidos en los 145 registros combinados. Las dos resoluciones se generaron desde los rangos vigentes en `pyproject.toml`; no existe lockfile ni hashes de artefactos, por lo que los resultados son una foto de las versiones compatibles, no una certificación de un release reproducible.

La heurística de alta confianza revisó 1,759 archivos de texto rastreados y no halló patrones comunes de claves privadas ni tokens. No escaneó archivos ignorados/no rastreados, binarios, archivos de más de 12 MB ni formatos arbitrarios: no demuestra que no haya secretos locales.

### Controles y configuración

- `src/isycode/credentials.py` usa el keyring del sistema para valores de claves, separa metadatos en SQLite, rechaza backends inseguros y falla cerrado cuando el keyring no está disponible.
- `.gitignore` excluye `.env`, `.env.*`, `.isyroot` y estado local, y permite `.env.example`. `SECURITY.md` delimita las pruebas seguras y la divulgación.
- Los workflows declaran `contents: read` de forma general y `contents: write` solo en el job de release. No se encontró `pull_request_target` en los triggers revisados.
- Las acciones de GitHub usan etiquetas de versión mutables en vez de SHA completos. Es una mejora pendiente de cadena de suministro; GitHub documenta el SHA completo como referencia inmutable en [Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use).
- `pyproject.toml` contiene configuración de Ruff, mypy y coverage; no se encontró evidencia de que los workflows los ejecuten ni de jobs de escaneo de dependencias o secretos.

### Hallazgos de Hive

La auditoría post-merge anterior reprodujo tres problemas P1 en fixtures sobre `594050e`. El commit local `74218e3` solo cambió `types.py` para generar timestamps UTC con zona horaria; no agregó validación de IDs o remitentes. `router.py`, `guard.py` y `spawn.py` no cambiaron. Los tres hallazgos estaban abiertos en `87b58ea`:

1. El router forma rutas desde IDs de mensaje no confiables y conserva el remitente declarado por el payload (`src/isycode/hive/router.py`, `src/isycode/hive/types.py`).
2. Un symlink del outbox puede resolver fuera del espacio permitido de un agente (`src/isycode/hive/guard.py`).
3. El launcher inicia un subprocess sin un owner de ejecución acotado y autorizado (`src/isycode/hive/spawn.py`).

El corte `87b58ea` no incluye los cambios que luego se integraron mediante PR #62 (`c033d82`). La guía de esa reparación está en `docs/audits/2026-10-18-hive-repair/GUIA.md`; este informe no vuelve a probar los casos contra la versión mergeada.

## 4. Calidad, pruebas y mantenibilidad

La revisión estructural señaló módulos planos y extensos, métodos grandes como `ChatMixin._run_chat`, el tamaño de `action_runtime.py` y acoplamiento entre mixins. El arreglo de truncamiento no descompone todavía esos módulos.

El análisis estático del AST contó 134 handlers que capturan `Exception` o `BaseException`, de los que 15 empiezan con `pass`, `continue` o `return` sin diagnóstico. No se encontraron `except:` desnudos. Es una señal para revisar mantenibilidad y observabilidad, no 134 vulnerabilidades. El análisis tampoco encontró usos literales de `shell=True`, `os.system`, `ssl=False`, `CERT_NONE` ni `verify=False` en `src/isycode`.

Las 52 pruebas focalizadas corresponden al arreglo local de TUI/búsqueda. No se ejecutaron durante esta auditoría de seguridad/dependencias, y no validan los hallazgos de Hive. La suite completa y la matriz CI quedan pendientes.

El informe post-merge previo también registró fallos del snapshot M15 en su corte. `docs/security/m15-authority-coverage.json` cambió en el merge local, pero su generador y prueba dedicada no forman parte de la verificación focalizada aquí; en `87b58ea` quedaba **por verificar**; PR #62 lo regeneró y #63 sincronizó sus líneas. Este informe no vuelve a ejecutar el generador ni la prueba dedicada.

## 5. Hallazgos priorizados

| Severidad | Hallazgo | Archivos afectados | Estado al corte `87b58ea` |
|---|---|---|---|
| Alta (P1) | Router forma rutas desde IDs no confiables y confía en el remitente del mensaje. | `src/isycode/hive/router.py`, `src/isycode/hive/types.py` | Abierto; reproducción previa documentada sobre `594050e`; `types.py` solo tuvo un cambio de timestamp en `74218e3`, sin validación de identidad/ID. |
| Alta (P1) | Symlink del outbox puede escapar del espacio del agente. | `src/isycode/hive/guard.py` | Abierto; reproducción previa documentada; sin cambio en `74218e3`. |
| Alta (P1) | Hive lanza subprocess sin owner acotado que pase por Authority/IsySentinel y registre el efecto. | `src/isycode/hive/spawn.py` | Abierto; no cubierto por corregir solo la interfaz. |
| Media | No hay lockfile ni hashes para fijar las dependencias instaladas/publicadas. | `pyproject.toml`, proceso de distribución | Abierto como riesgo de reproducibilidad; OSV halló 0 avisos en las versiones resueltas y `.venv`. |
| Media-baja | Las GitHub Actions se referencian con etiquetas mutables, no SHA inmutable. | `.github/workflows/` | Pendiente de pinning verificado y mantenimiento. |
| Media | 134 handlers amplios; 15 no registran el error antes de continuar/retornar. | `src/isycode/` | Deuda de observabilidad; revisar caso por caso, preservando fail-closed. |
| Media / verificación | Estado del snapshot M15 después de regenerar el artefacto. | `docs/security/m15-authority-coverage.json`, `tests/test_action_coverage.py` | Por verificar en `87b58ea`; PR #62 lo regeneró y #63 sincronizó sus líneas. Esta PR no volvió a ejecutar el generador ni la prueba dedicada. |
| Informativa | Heurística de secretos sin candidatos de alta confianza en 1,759 archivos de texto rastreados. | Archivos rastreados incluidos por la pasada | Sin hallazgos dentro de ese alcance; no es certificación. |
| Informativa | `pip-audit` no encontró avisos OSV conocidos en 145 registros entre tres conjuntos. | `pyproject.toml`, `.venv`, evidencia bajo `docs/audits/` | Sin avisos conocidos en la corrida del 19-10-2026; repetir al preparar releases. |
| Corregido | TUI/listados y búsqueda en repositorios grandes truncaban resultados; la salida podía invalidar JSON. | `src/isycode/action_runtime.py`, `src/isycode/workspace_pack.py`, `src/isycode/tui_app_rail.py`, `src/isycode/git_owner.py` | Corregido en `74218e3`, integrado en `87b58ea`; 52 pruebas focalizadas aprobadas. |

## 6. Plan recomendado

1. Repetir los probes de los tres P1 de Hive sobre el `main` actual para confirmar los cambios mergeados por #62: validar IDs y remitentes, rechazar enlaces fuera del límite e impedir lanzamientos sin owner autorizado.
2. Confirmar M15 con el generador canónico y su prueba dedicada después de las actualizaciones de #62/#63; esta PR no vuelve a ejecutar esa verificación.
3. Añadir lockfile y hashes compatibles con el proceso de release; automatizar OSV sobre esa resolución y alertas periódicas.
4. Fijar acciones de GitHub a SHA verificados, con permisos mínimos y mecanismo explícito de actualización.
5. Incorporar escaneo de secretos al CI con revisión de falsos positivos que no exponga valores sensibles.
6. Revisar los 15 handlers sin diagnóstico, priorizando Hive; luego habilitar en CI los gates configurados de Ruff/mypy/coverage.
7. Ejecutar suite completa y CI tras los cambios de Hive y M15, registrando resultados por plataforma.

## Fuentes

- `auditoria_arquitectura_calidad.md` (18-10-2026): arquitectura, calidad, pruebas y plan técnico.
- `auditoria_seguridad_dependencias.md` (19-10-2026): auditoría OSV, secretos, configuración y errores; salidas y requisitos resueltos en `docs/audits/2026-10-19-security-deps-87b58ea/`.
- `ISyCode/AUDITORIA_CODIGO.md`, `ISyCode/AUDITORIA_HALLAZGOS.txt`, `ISyCode/AUDITORIA_RESUMEN.md` (18-10-2026): resumen de la revisión Kiro; afirmaciones de seguridad no tomadas como certificación independiente.
- `vicios-tecnicos/briefings/isicode/2026-10-18-post-merge-hive-audit.md`: hallazgos Hive y snapshot en el corte `594050e`.
- `vicios-tecnicos/briefings/isicode/2026-10-18-hive-repair.md` (nota histórica externa): alcance del cambio que después se integró mediante PR #62; el corte `87b58ea` no lo contiene.
- Diff local `594050e..87b58ea`, commit de reparación `74218e3`, y pruebas focalizadas indicadas arriba.

### SHA-256 de las notas fuente

```text
f76355305b5e8721ead224d9f958f12e5515c78e19ec15c4d55f637db9006ee2  auditoria_arquitectura_calidad.md
621d400cc3269ca50b83c4b790fbd1207d360ace24692409897e468be975ddc0  ISyCode/AUDITORIA_CODIGO.md
bb1ac69b37599154d8b35fa76e4e67888ce5009f1c7328970c5320a7e93c6407  ISyCode/AUDITORIA_HALLAZGOS.txt
f965259ad931b13996b476df46ea98d64971b93a13373d3300b40b6b06189fbd  ISyCode/AUDITORIA_RESUMEN.md
e24cb156104667806babe3838116a893c27606d0958fcd6281a8c3bbf372ad98  vicios-tecnicos/briefings/isicode/2026-10-18-post-merge-hive-audit.md
ccd1f0897df164cb32dd66ec5f52533825f52b91a90562664d5f6dae201a4440  vicios-tecnicos/briefings/isicode/2026-10-18-hive-repair.md
eb30ff4f233fabc47cf71e7fbb6e87b159d3899c352506809cacf7fe6cc886de  auditoria_seguridad_dependencias.md
228dd8c24df0c7fe6f4a76c7a76af0aae25ce1bc4e346802e1005843d73dc924  docs/audits/2026-10-19-security-deps-87b58ea/SHA256SUMS.txt
```
