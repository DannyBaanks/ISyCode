# M9 — paquete para revisión, 2026-10-08

Estado: **BLOQUEADO**, sin aprobación independiente ni autorización de release.
Código de la aplicación evaluado: 57ba3cf. Las herramientas de medición y su
corrección se conservan como artefactos de método, separadas del código probado.

| Puerta | Resultado actual | Evidencia / límite |
| --- | --- | --- |
| G9-01 | PASS en regresiones seleccionadas | 130 tests, intérprete base de la misma venv mediante PYTHONPATH para evitar el shebang con espacios; validador histórico exit0. No es una nueva full suite. |
| G9-02 | EN_REVISION | Medición anterior 87f9fe1 favorable, conservada como HISTORICAL; no ejecutada de nuevo en este paquete ni terminal físico. |
| G9-03 | EN_REVISION | Medición anterior usa task.cancel() y pgrep; no demostrar latencia de tecla Esc física a partir de ese dato. No se repitió aquí. |
| G9-04 | EN_REVISION | Soak corregido de dos horas aún activo; snapshot de progreso no es evidencia final. |
| G9-05 | BLOQUEADO / EN_REVISION | Protocolo, cinco fixtures independientes y evaluador preparados; cero sesiones humanas observadas en este trabajo. |
| G9-06 | PASS, flujo acotado | NVIDIA real: lecturas, workspace_edit con receipt, unittest real en bubblewrap exit0; tests intactos y verificación posterior independiente. |

## Flujo NVIDIA

Modelo nvidia/nemotron-3-ultra-550b-a55b, cuatro llamadas; 29.696s totales,
16918 tokens de entrada y 352 de salida reportados; latencias 3.281–8.189s.
La fuente inicial restaba; el test falló antes. La fuente final suma, el test
original se conserva y pasa. Journal PASS. Provider, red, tools, owners y
bubblewrap son reales; las aprobaciones de los diálogos son automatizadas para
este fixture sintético. Esto no cuenta como prueba con personas.

Coste monetario NOT_AVAILABLE: no comunicado por el provider. No se inventó
un precio. El workspace temporal se conserva en la ruta registrada por result.json.

Error del verificador: esperaba status=applied/decision=ALLOW. La herramienta
retorna status=written/receipt. result.json y run.log conservan ese FAIL original;
reevaluation.json aplica el contrato correcto a los mismos resultados. Todos sus
checks pasan. No se modificó evidencia cruda ni se repitió el flujo de red.

## Validación histórica y release

El validador anterior comparaba scripts/soak_g9.py histórico con el checkout
modificado. Se reprodujo el fallo con un repo de test y se comprobó el blob real
7323570:scripts/soak_g9.py: SHA256 1355f1ac9c2669c746666bd25b06438dc8c73c82daf37dd5d8df56270bbdde0f,
exactamente el hash del manifiesto original.

Ahora, para referencias src/scripts/tests cuyo contenido actual no coincide,
la validación **histórica** puede recuperar un archivo regular del commit
sha_evaluado y exigir el hash original. Artefactos de método que ya coinciden
con su hash conservan la semántica existente. La evidencia cruda se sigue
verificando en disco. No se reescribieron manifiestos ni hashes históricos.

--require-approved sigue comprobando contenido del checkout actual, aceptación
independiente y estados aprobados. Devuelve exit1; el test de control confirma
que una fuente nueva no hereda aprobación y que evidencia cruda alterada falla.

## Usabilidad humana

Guía: docs/usability-g9/GUIA.md. Tres tareas: corregir y verificar, buscar datos,
revisar cambio y undo. CSV vacío para P01–P05; no inventar participantes ni tiempos.
Umbrales: 4/5 por tarea sin ayuda, mediana <=120s con credencial disponible,
cero modales ordinarios después del trust (incluida restauración si abre modal).
El evaluador valida observaciones del moderador, no identidad humana. Los datos
sintéticos de sus tests son únicamente controles de software.

## Pendiente / NOT_DEMONSTRATED

- Resultado final de dos horas del soak corregido y su evaluación RSS.
- Cinco participantes reales y aprobación independiente de M9.
- Nuevas mediciones G9-02/03, terminal físico y caja de referencia 4 cores/8GiB.
- Coste monetario y extrapolación a otros modelos/providers.
- Full suite nueva del repo para los cambios de método de este paquete.

Cada comando, estado y negativo se conserva en commands.json y los logs.
El gate.yaml expresa el bloqueo actual; nunca eleva un pendiente a PASS.

## Comprobaciones finales del método

28 tests focalizados PASS en focused-latest.log, incluidos bloqueo de evidencia
humana por symlink, datos incompletos/umbrales, fuente histórica frente a release,
recibos ausentes y comando timed out. 130 regresiones seleccionadas PASS fueron
medidas antes de estas adiciones finales de tests; ambas corridas se conservan.

La versión del runner lista para próximas corridas limita tools a lectura de
calc.py/test_calc.py, edición de calc.py y unittest; tools de UI solo informativas.
Antes de la verificación independiente, exige tests intactos y AST de la función
pura de suma; no ejecuta código arbitrario del modelo en el host ni propaga la
clave al proceso de verificación. Las restricciones están probadas por unit tests.
La corrida NVIDIA ya realizada está documentada por script-executed.py, sin
atribuirle retroactivamente restricciones añadidas después.

El evaluador exacto de reevaluation.json se conserva en evaluator-at-reevaluation.py:
fue recuperado de la misma fuente antes de los helpers nuevos y su SHA256 coincide
byte por byte con el hash que ya constaba en reevaluation.json.
