# G9-05 — Prueba con cinco personas reales

Estado inicial: **BLOCKED** hasta observar cinco participantes. El paquete está
listo para ejecutar; preparar el protocolo no completa el gate. No sustituir
participantes por agentes, respuestas inventadas o la prueba automatizada G9-06.

## Preparación del moderador

Usa cinco personas distintas, IDs P01–P05; registra experiencia previa sin
nombres, claves ni datos personales. Cada una usa la misma versión de ISyCode,
el mismo modelo/provider disponible, su propia carpeta nueva y credencial ya
configurada. Declara versión/commit, SO, hardware, backend, modo Classic y modelo.
Anota interrupciones, red caída y asistencia, sin excluir luego malos resultados.

Desde el repo crea el fixture individual (ruta nueva):

```bash
.venv/bin/python scripts/setup_g9_usability.py /tmp/g9-persona-P01-NUEVO
```

Crea un fixture por persona. No reutilices el proyecto de alguien más. Abre una
terminal en esa carpeta y ejecuta `isycode`. Nunca compartas claves con el
moderador ni las muestres en grabaciones. La credencial debe estar disponible
antes del inicio; si no lo está, deja el caso fuera de ejecución y el gate BLOCKED.

## Medición

Arranca el cronómetro cuando la persona comienza a abrir/configurar ISyCode en
la carpeta. Onboarding termina cuando composer, provider y coding tools están
listos y la persona confirmó conscientemente el trust de su carpeta de prueba.
Registra tiempo real, sin descontar confusión. No le indiques dónde hacer clic:
si pide/recibe instrucciones operativas, anótalas como ayuda. El consentimiento
inicial y explicar el objetivo no cuentan como ayuda para resolver tareas.

Cuenta después del trust cada modal ordinario de lectura, edición, ejecución y
restauración, incluida la revisión de undo de la tarea 3 si aparece. Registra
tipo/momento/motivo y también el total de todos los modales. Onboarding y trust
inicial ocurren antes del inicio de esta cuenta. No excluyas un modal rutinario
por haber solicitado la operación, ni lo rebautices para cumplir cero: si la
recuperación abre un modal ordinario, el criterio puede fallar y debe conservarse.

Máximo por tarea: 10 minutos. El límite sirve para comparar, no cambia el criterio
oficial. Al agotarse, completed_without_help=no; registra causa y evidencia.
El moderador puede intervenir por seguridad, pero la tarea pierde el atributo
sin ayuda. No toques archivos ni autorices acciones por la persona.

## Tarjetas que recibe cada participante

**Tarea 1 — Corregir un programa.** Usa ISyCode para averiguar por qué falla
`python3 -m unittest -v`, corregir solo calc.py y comprobar que los tres asserts
pasan. No modifiques test_calc.py. Puedes redactar tu propio prompt. Éxito:
archivo correcto, tests originales conservados y ejecución real exit0 visible.

**Tarea 2 — Encontrar información.** Averigua con las herramientas de ISyCode
el código del proyecto y el identificador de release en los archivos de esta
carpeta. No modifiques archivos. Éxito: ALPHA_42 y CANARY_RELEASE_7 acompañados
de las rutas reales notes.txt y docs/release.txt; no una respuesta sin lectura.

**Tarea 3 — Revisar y recuperar un cambio.** Pide cambiar review.txt de
status=original a status=changed. Mira el diff que muestra ISyCode. Usa `/undo`
para revisar y revertir exclusivamente ese cambio. Éxito: la persona identifica
la modificación, revisa la recuperación y confirma status=original mediante
lectura real; calc.py sigue corregido. La revisión de undo se registra y cuenta si es un modal ordinario. Si no se puede hacer undo, anota FAIL, no restaures a mano.

Después de cada tarea, anota si mensajes anteriores desaparecieron, cambió el
orden, quedaron spinners activos, se perdió un borrador o el Idea Box dijo algo
contrario a lo realizado. Son hallazgos de UI, aunque la tarea termine.

## Registro y evaluación

Copia observations-template.csv a una carpeta nueva de evidencia. Completa sus
15 filas con observaciones reales. Valores yes/no; tiempos en segundos; número
de modales ordinarios no negativo. Repite el mismo onboarding en las tres filas
de una persona. human_observed=yes es una atestación del moderador, nunca un
campo que el modelo pueda completar por sí mismo.

Para cada fila guarda un archivo de observación con tiempos, prompt, resultado,
ayuda, todos los modales y capturas/transcript relevantes ya revisados para no
contener secretos. evidence es la ruta relativa a ese archivo desde el CSV.
Conserva resultados negativos. Firma el registro con identidad del moderador y
fecha; no edites evidencia cruda para acomodar el resultado. Calcula SHA-256 del
CSV y cada archivo. Anexa un registro de las cinco sesiones reales.

```bash
.venv/bin/python scripts/evaluate_g9_usability.py /ruta/NUEVA/observations.csv
```

Aceptación oficial: al menos 4/5 personas completan **cada tarea** sin ayuda,
mediana de onboarding <=120s con credencial disponible y cero modales ordinarios
tras trust. Datos incompletos: BLOCKED; medición completa que incumple: FAIL.
El evaluador comprueba consistencia y umbrales; no prueba que las personas
existan ni otorga aprobación al gate. Hace falta revisión independiente.
