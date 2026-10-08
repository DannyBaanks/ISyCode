# G9-06 — Flujo real medido

Desde la raíz del repo, con un output absoluto y nuevo:

```bash
.venv/bin/python scripts/live_g9_06.py --key-workspace /ruta/al/workspace-con-clave --provider nvidia --model nvidia/nemotron-3-ultra-550b-a55b --out /ruta/NUEVA/result.json
```

Requiere autorización para reutilizar la clave y consumir API, además de
bubblewrap real. La clave se carga por el mecanismo de ISyCode, no se imprime ni
se guarda en el informe. El script conserva un workspace temporal con fixture,
state y journal para inspección; no modifica el proyecto del usuario.

La tarea lee dos archivos, corrige calc.py mediante workspace_edit y ejecuta
unittest mediante workspace_run. El harness confirma automáticamente los diálogos
normales de aprobación de esta tarea sintética; no representa participantes
humanos. Provider, modelo, transporte, owners, Sentinel, sandbox y journal son
reales. No se usa el DNS ficticio de los tests herméticos.

Comprobaciones: fallo inicial, lecturas de ambos archivos, edición con recibo,
comando sandboxed exit0, tests originales conservados, prueba posterior
independiente y journal verificado. El modelo tiene un presupuesto de ocho
llamadas y hasta 4096 tokens de salida por llamada; el turno tiene límite de diez
minutos. No confundir turn=completed con PASS: consulta checks y status.

Se registran mensajes contados, tiempos hasta primer chunk, latencias, tokens
reportados, errores, historial completo de tools, fuente final, hashes y journal.
Coste monetario: NOT_AVAILABLE si el provider no lo comunica; no multiplicar por
una tarifa supuesta ni declarar coste cero. Esta prueba demuestra únicamente el
modelo/provider/fixture medido, no todos los providers ni usabilidad humana.

El informe de la primera corrida conserva un FAIL de verificador: esperaba
status=applied, pero el contrato real retorna status=written y receipt. La
corrección está probada; reevaluation.json aplica esa corrección a los mismos
resultados crudos sin reescribirlos ni repetir llamadas. Revisa ambos archivos.

La versión actual rechaza llamadas ajenas al fixture (solo lecturas de sus dos
archivos, edición de calc.py y unittest, además de tools informativas de UI).
La verificación independiente solo ejecuta la función de suma pura esperada y
los tests originales; su proceso no recibe las credenciales. Cambios fuera de
ese scope dan FAIL, no se ejecutan en el host. Las restricciones nuevas están
probadas; la corrida anterior conserva su script ejecutado y no se relabela.
