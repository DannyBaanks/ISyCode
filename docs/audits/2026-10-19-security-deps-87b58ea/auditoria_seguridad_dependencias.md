# Auditoría de seguridad, dependencias, configuración, secretos y errores — ISyCode

- **Fecha:** 19 de octubre de 2026
- **Corte:** `87b58ea` (`main` local)
- **Proyecto:** `DannyBaanks/ISyCode`
- **Tipo de revisión:** análisis estático del código y configuración, heurística de secretos sobre archivos rastreados y auditoría de versiones con OSV. No se hicieron pruebas contra proveedores, cuentas ni infraestructura externa.

> **Vigencia (19-10-2026):** este informe conserva el estado del corte `87b58ea`. [PR #62](https://github.com/DannyBaanks/ISyCode/pull/62) (`c033d82`) y [PR #63](https://github.com/DannyBaanks/ISyCode/pull/63) (`1095ad1`) se integraron a `main` después de ese corte. #62 incorporó validación de IDs/remitentes, rechazo de rutas enlazadas y límites de ejecución Hive, además de regenerar el snapshot M15; #63 atendió hallazgos de permisos de TUI y sincronizó líneas del snapshot. Los P1 que aquí figuran abiertos corresponden a `87b58ea`; esta actualización no repitió los probes de explotación contra `1095ad1`. Los resultados de OSV y de secretos siguen limitados al corte original. La reparación TUI portada a esta PR pasó 52 pruebas focalizadas en `87b58ea`, sin repetirse tras el port; queda la CI de esta PR.


## Resumen

`pip-audit` no encontró vulnerabilidades conocidas en tres conjuntos revisados: las dependencias instaladas en el `.venv` local (42 distribuciones), una resolución Linux/Python 3.10 con todos los extras (56) y una resolución Windows/Python 3.12 con todos los extras (47). La resolución parte de los rangos actuales de `pyproject.toml`; como no existe lockfile, no identifica una instalación reproducible de release ni sus hashes.

La pasada heurística sobre **1,759 archivos de texto rastreados** no halló formatos comunes de claves privadas o tokens de alta confianza. No leyó valores de posibles secretos ni escaneó archivos no rastreados, ignorados, binarios o mayores de 12 MB. Por tanto, no certifica que no existan secretos locales ni cubre formatos arbitrarios.

La revisión registró **tres hallazgos de severidad alta previamente reproducidos en Hive**: construcción de rutas desde mensajes no confiables, escape de límites con symlink y lanzamiento de proceso sin owner de ejecución. En el corte `87b58ea`, el commit `74218e3` solo modificó `types.py` para generar timestamps UTC con zona horaria; no añadió validación de IDs o remitentes. Los problemas estaban abiertos en ese corte. PR #62 incorporó después cambios en las rutas afectadas; no se repitieron aquí los probes sobre la versión mergeada.

## Método y evidencia conservada

- Corte de Git inspeccionado: `87b58ea`; la reparación de `74218e3` está incluida localmente. En el momento de ejecutar esta auditoría, el estado remoto no se había actualizado y no se había hecho push.
- Resolver: `uv 0.12.17`, `uv pip compile --all-extras` para Linux/Python 3.10 y Windows/Python 3.12. Las listas resultantes contienen versiones exactas, pero no hashes de artefactos.
- Escáner: `pip-audit 2.10.1`, fuente de vulnerabilidades OSV, en modo estricto. Las listas ya resueltas se analizaron con `--no-deps --disable-pip`; también se escaneó el `.venv` real. El primer intento que dejó a pip instalar el conjunto falló por ejecutarse bajo Python 3.14 y por el paquete exclusivo de Windows desde Linux; se repitió sin instalación, consultando las versiones exactas resueltas. La documentación de [pip-audit](https://github.com/pypa/pip-audit/blob/main/README.md) describe el análisis de requirements y el servicio OSV.
- Secretos: reglas de alta confianza para cabeceras PEM y patrones comunes de AWS, GitHub, Google, Stripe, Slack, OpenAI y Anthropic; el resultado guardado contiene solo conteos/rutas, nunca valores coincidentes.
- Evidencia cruda, listas resueltas, salidas JSON, stderr, comandos, entorno y hashes: [`./`](./).

## Resultados por área

### Dependencias

| Conjunto | Distribuciones auditadas | Hallazgos OSV |
|---|---:|---:|
| `.venv` local, Python 3.12.3 | 42 | 0 |
| Resolución Linux, Python 3.10, todos los extras | 56 | 0 |
| Resolución Windows, Python 3.12, todos los extras | 47 | 0 |

No hay `uv.lock`, `poetry.lock`, `Pipfile.lock` ni `requirements*.txt` en el checkout. Las dependencias directas están expresadas como rangos en `pyproject.toml`; el resultado de hoy puede variar cuando se instale mañana. Tampoco se encontró configuración de Dependabot o Renovate en `.github/`. No hay evidencia de un job de auditoría de dependencias en los workflows revisados.

**Conclusión:** cero CVE/avisos conocidos en los tres conjuntos consultados al momento del escaneo; la actualización y trazabilidad de lo que se publica siguen sin quedar fijadas. El informe Kiro anterior señalaba OWASP A06 como pendiente; la auditoría actual ya consultó un advisory database para los conjuntos indicados, pero no convierte el proyecto en libre de vulnerabilidades.

### Gestión de secretos y credenciales

- `src/isycode/credentials.py` guarda valores de API key mediante el keyring del sistema operativo y metadatos separados en SQLite. Rechaza backends de keyring no seguros, usa permisos privados para el archivo, verifica enlaces duros/symlinks y falla cerrado si el keyring no está disponible.
- `.gitignore` excluye `.env`, `.env.*`, `.isyroot` y estado local, permitiendo explícitamente `.env.example`.
- `SECURITY.md` limita las pruebas a datos y credenciales ficticios, describe la divulgación privada y aclara que publicar código no es una auditoría independiente.
- Resultado heurístico: cero candidatos de alta confianza en los archivos de texto rastreados. La exploración de archivos ignorados/no rastreados y formatos genéricos de credencial queda **NOT_DEMONSTRATED**.

### Configuración y CI

- Los workflows declaran `permissions: contents: read` a nivel general; el job que crea releases pide `contents: write` localmente. Los triggers observados son `pull_request`, `push` y `workflow_dispatch`; no se encontró `pull_request_target`.
- Las acciones usan etiquetas principales, por ejemplo `actions/checkout@v7`, `actions/setup-python@v7`, `upload-artifact@v7` y `download-artifact@v8`, no SHA de commit inmutables. Es una exposición de cadena de suministro de severidad media-baja, mitigada en parte por acciones de organizaciones conocidas y permisos limitados. GitHub indica que fijar una acción a SHA completo es la forma inmutable de referenciar su release; consultar [Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use).
- No se encontró un job que ejecute `pip-audit`, escáner de secretos ni análisis estático de seguridad. `pyproject.toml` sí contiene configuración de Ruff, mypy y coverage, pero los workflows inspeccionados no los ejecutan.

### Manejo de errores y ejecución

El análisis AST contó **134 handlers que capturan `Exception` o `BaseException`** bajo `src/isycode`; **15** empiezan con `pass`, `continue` o `return` sin registrar el error. No hay handlers `except:` desnudos. El conteo es una señal de revisión, no 134 vulnerabilidades: algunos límites deben denegar ante excepciones. Aun así, la supresión sin diagnóstico dificulta detectar fallos; los casos de `hive/router.py`, `hive/manager.py`, `hive/hook_server.py` y `hive/hook_shim.py` merecen prioridad por tratar mensajes y coordinación.

No se encontró uso literal de `shell=True`, `os.system`, `ssl=False`, `CERT_NONE` ni `verify=False` en `src/isycode`. Los subprocesses se lanzan en varios módulos mediante `create_subprocess_exec`; eso evita el shell implícito, pero no sustituye la validación de argumentos ni un owner de efecto. `src/isycode/l1.py` ejecuta código Python candidato, pero el camino observado lo prepara con `CommandRunOwner`, un workspace temporal y `promote=False`; no se ejecutó un payload hostil en esta revisión.

## Hallazgos clasificados

No se demostró un hallazgo crítico en el alcance ejecutado.

| Severidad | Hallazgo | Archivos afectados | Estado |
|---|---|---|---|
| **Alta** | El router forma rutas de entrega desde IDs del mensaje y confía en el remitente declarado. La revisión post-merge anterior lo reprodujo escribiendo fuera del Hive y conservando remitente falsificado. | `src/isycode/hive/router.py`, `src/isycode/hive/types.py` | **Abierto en `87b58ea`; PR #62 incorporó después cambios a esa ruta, no revalidados aquí.** `74218e3` solo cambió la generación del timestamp UTC en `types.py`; el `from_dict` aún acepta los campos serializados y no se añadieron validaciones de ID/remitente. Esta sesión no volvió a ejecutar el probe. Evidencia previa: `vicios-tecnicos/briefings/isicode/2026-10-18-post-merge-hive-audit.md`. |
| **Alta** | Un symlink dentro del outbox permite que el destino real caiga en el espacio de otro agente. | `src/isycode/hive/guard.py` | **Abierto en `87b58ea`; PR #62 incorporó después cambios a esa ruta, no revalidados aquí.** El archivo no fue modificado por `74218e3`; reproducción previa documentada en el mismo briefing. |
| **Alta** | El launcher Hive crea un subprocess sin una solicitud ligada a Authority/IsySentinel, owner acotado y journal de efecto. | `src/isycode/hive/spawn.py:78` y la ruta de lanzamiento Hive | **Abierto en `87b58ea`; PR #62 incorporó después cambios a esa ruta, no revalidados aquí.** La presencia de otros gates en la aplicación no cubre este efecto. La reparación de PR #62 no forma parte de `87b58ea`; #62 se integró después, sin que esta auditoría repitiera el probe. |
| **Media** | No hay lockfile ni hashes para fijar las dependencias que llegan a instalación/publicación; no se encontró automatización de alertas. | `pyproject.toml`, `.github/` | **Abierto como riesgo de reproducibilidad.** El escaneo actual encontró 0 avisos, pero es una foto de versiones resueltas. |
| **Media-baja** | Las acciones de GitHub se referencian por etiquetas de versión, no por SHA inmutable. | `.github/workflows/ci.yml`, `.github/workflows/platform-parity.yml` | **Observación de cadena de suministro.** Configurar pinning verificado y un proceso para actualizarlo. |
| **Media** | Existen 134 handlers amplios y 15 suprimen o abandonan errores sin diagnóstico. | `src/isycode/hive/`, `src/isycode/credentials.py`, `src/isycode/updater.py`, `src/isycode/tui_app_*.py` | **Deuda de observabilidad.** Revisar uno por uno; conservar el comportamiento fail-closed donde sea requisito. |
| **Informativa** | La heurística de secretos no detectó candidatos en texto rastreado. | 1,759 archivos de texto rastreados | **Sin hallazgo en el alcance de la heurística; no es certificación.** |
| **Informativa** | `pip-audit` no identificó vulnerabilidades conocidas en 145 registros de los tres conjuntos revisados. | `pyproject.toml`, `.venv`, evidencia de OSV | **Sin hallazgo de CVE conocido en esta corrida; repetir al fijar versión de release.** |

## Plan de acción

1. Repetir sobre `main` los probes de los hallazgos de Hive con datos ficticios para verificar los cambios mergeados por #62: validar IDs/remitentes, resolver y rechazar symlinks fuera del límite, y bloquear procesos sin owner autorizado.
2. Crear un lockfile y, si el proceso de distribución lo permite, fijar hashes; documentar cómo se actualiza para Linux, Windows y extras opcionales.
3. Añadir un job de auditoría de dependencias contra la resolución bloqueada y configurar alertas de actualizaciones; mantener la salida OSV/PyPI como evidencia del corte.
4. Fijar las GitHub Actions a SHA verificado o a un lock de acciones mantenido automáticamente, conservando los permisos mínimos.
5. Incorporar un escáner de secretos al CI sobre archivos rastreados y documentar la revisión de falsos positivos sin guardar valores sensibles.
6. Revisar los 15 handlers que ocultan errores, empezando por Hive; añadir diagnóstico estructurado y pruebas cuando la supresión no sea parte explícita del comportamiento fail-closed.

## Límites y estado

- No se ejecutó la suite de pruebas; esta tarea fue una auditoría de lectura y análisis de dependencias.
- No se hicieron pruebas con proveedores, OAuth, Gateway real, credenciales reales, APIs externas ni infraestructura de terceros.
- El escaneo OSV cubrió versiones resueltas y el `.venv` local, no una distribución construida ni todas las plataformas/arquitecturas.
- Las tres fallas de Hive proceden de una reproducción independiente previa sobre el corte `594050e`; este informe las registra abiertas porque `87b58ea` no incorporaba las correcciones que después entraron por PR #62 y esta sesión no repitió el probe. El cambio de timestamp en `types.py` no modifica esa conclusión al corte `87b58ea`; PR #62 se integró después y abordó las rutas descritas, sin revalidación de probes en esta sesión.
- Estado Git del proyecto al consolidar: `main` local `87b58ea`, adelante 2 y detrás 1 de `origin/main`; no se hizo push.
