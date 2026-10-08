# Guía del soak G9-04

Ejecuta desde la raíz de ISyCode con su entorno virtual:

```bash
.venv/bin/python scripts/soak_g9.py /tmp/mi-soak-NUEVO.json
```

Elige una ruta nueva por ejecución. No reutilices estados o evidencia histórica.
Se crea mi-soak-NUEVO.state.json para progreso. Tras tres restarts y dos horas
**efectivas**, el resultado final aparece en mi-soak-NUEVO.json con status y checks.
Los mensajes de los workers reiniciados quedan en mi-soak-NUEVO.json.workers.log.
Si corre en primer plano, el primer worker termina al lanzar su sucesor; eso no
significa que el soak completo haya terminado. Consulta state.json y el archivo
final, no solo el exit0 del primer worker. Conserva y calcula SHA256 del resultado.

Cada ciclo verifica una escritura, restaura el contenido anterior mediante undo
con aprobación simulada para ese fixture y verifica el journal. No modifica tu
proyecto. El modelo es simulado; no prueba un provider real ni usuarios humanos.
RSS actual se mide con /proc y baseline warm tras diez ciclos por worker.

G9_SOAK_SECONDS permite diagnósticos cortos, pero estos devuelven FAIL si no
cumplen las dos horas, cien ciclos, tres restarts y demás criterios. Un contador
sin excepciones no equivale a PASS. No cambies el script durante una ejecución:
el siguiente worker rechazará un SHA256 distinto. Ante un estado corrupto,
conserva la evidencia y comienza una ejecución con otra ruta.

La corrida vieja y sus hashes siguen siendo históricos; no demuestran las
comprobaciones incorporadas ahora. G9-06 usa un provider real y es otra prueba.
