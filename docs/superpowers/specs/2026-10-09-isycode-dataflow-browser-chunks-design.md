# Dataflow local para filtrar snapshots grandes del navegador

## Estado

Diseño aprobado en conversación; especificación pendiente de revisión del
usuario antes de preparar el plan de implementación.

## Intención y criterios acordados

ISyCode aún no tiene un runtime Dataflow. ISyCo sí contiene experimentos y
varios sistemas de ejecución, pero pertenecen a otros dominios. El primer
paso será comprobar si un Dataflow local ayuda a procesar snapshots grandes
del navegador, sin portar esos sistemas ni desplegarlo todavía en todas las
herramientas.

El flujo existente de lectura del navegador conserva su carácter de solo
lectura. El agente recibe texto filtrado, marcado como contenido no confiable,
y la persona revisa el texto exacto antes de compartirlo con el modelo.

La primera medición debe responder dos preguntas por separado:

1. ¿El procesamiento por chunks conserva el resultado correcto y evita perder
   contenido útil por el límite actual de salida?
2. ¿Un pool acotado de workers mejora el tiempo de pared frente al mismo
   procesamiento serial, descontando el coste de dividir, serializar y unir?

No se adoptará concurrencia por el mero hecho de que los experimentos de ISyCo
la hayan utilizado. Cada milestone termina con evidencia y una decisión
humana de continuar, ajustar o desechar esa parte.

## Alcance inicial

- Primer consumidor: snapshots de accesibilidad de Playwright en ISyCode.
- Crear una pequeña abstracción local reutilizable de Dataflow para procesar
  una colección ordenada de unidades independientes con concurrencia acotada.
- Dividir el snapshot en bloques que respeten límites del árbol accesible y
  transportar a cada bloque el contexto estructural mínimo que necesite el
  filtro.
- Filtrar cada bloque de forma determinista y volver a unir los resultados por
  su posición original, no por el orden de finalización de los workers.
- Comparar ejecución serial, concurrencia con hilos y concurrencia con
  procesos sobre el mismo corpus. Seleccionar una estrategia solo si los
  datos muestran una mejora suficiente; el umbral se fijará después de medir
  el baseline.
- Mantener un límite explícito de salida total. Si el resultado excede ese
  límite, informar truncación final; el chunking no debe ocultarla.
- Conservar `untrusted`, la revisión humana, el flujo de autorización existente
  y el preset de Playwright de solo snapshot.

## Fuera de alcance

- Aplicar Dataflow a todas las herramientas de ISyCode en esta primera etapa.
- Usar el Dataflow de `tools/graph_engine` para ejecutar comandos o
  subprocesos desde el navegador.
- Portar la cola durable, la base de datos, los leases o los reintentos de
  PROYECTOMAYDA.
- Añadir navegación, clics, JavaScript, acceso a cookies, sesión autenticada,
  red o control del navegador al worker.
- Guardar snapshots crudos o persistir contenido de páginas en disco.
- Afirmar fidelidad semántica completa del filtro o eliminar el límite de
  contexto del proveedor.

## Diseño

### Etapas de Dataflow

El primer runtime modela únicamente este recorrido:

```text
snapshot de accesibilidad
  → segmentador estructural
  → unidades inmutables {índice, texto, contexto}
  → workers de filtrado con concurrencia acotada
  → validación de todos los resultados
  → unión estable por índice
  → límite global + estado de calidad
  → preview humano ya existente
```

El segmentador no debe cortar en medio de una línea ni olvidar si un ancestro
está dentro de una subrama descartada. El worker recibe el contexto mínimo para
que el filtro conserve su comportamiento actual. La unión resuelve duplicados
adyacentes en las fronteras entre chunks y conserva el orden de lectura.

El scheduler será local al proceso de ISyCode, sin bus de red ni almacenamiento
durable. La interfaz deberá permitir ejecución serial y ejecución con un
número limitado de workers. Un tamaño mínimo de trabajo evitará crear workers
para snapshots pequeños. La política de concurrencia predeterminada dependerá
del benchmark, no de una suposición sobre el GIL o sobre el coste de spawn.

### Errores y truncación

- Cada unidad produce un resultado identificado por su índice y con estado de
  éxito o error.
- Un error, timeout o resultado ausente no se convierte en una unión parcial
  que parezca completa: la operación termina como incompleta y la preview lo
  indica.
- Los resultados que llegan en otro orden se reordenan antes de unirse.
- El límite global se aplica después de unir todos los resultados válidos y
  mantiene el estado `INCOMPLETE_TRUNCATED` si todavía fue necesario truncar.
- Nunca se afirma `fidelity_assessed=true` por el hecho de que todos los
  workers hayan terminado.

### Seguridad y privacidad

Los workers procesan texto ya capturado; no reciben objetos del navegador ni
credenciales. No pueden invocar herramientas, navegar, leer archivos, escribir
evidence ni hacer llamadas de red. La decisión del Dataflow no concede ninguna
capacidad: ISySentinel, Workspace Authority, aprobaciones y execution owners
conservan sus funciones actuales.

La preview sigue mostrando exactamente el contenido filtrado que se enviaría
al modelo. Si la persona lo descarta, el modelo no recibe los chunks ni el
snapshot original. La evidencia de benchmark usa páginas públicas, fixtures
sintéticos y métricas; no persiste el texto completo de una página privada.

## Milestones y puertas de decisión

Cada milestone se ejecuta y se compara antes de comenzar el siguiente. El
usuario decide explícitamente **continuar, ajustar o desechar** al ver el
resultado. No hay avance automático.

### M0 — Baseline reproducible

Medir el filtro serial actual con fixtures pequeños, grandes y adversariales, y
un corpus de cinco páginas públicas representativas. Registrar tiempo de pared,
tamaño de entrada/salida, truncación, uso máximo de memoria cuando sea medible,
y canarios de contenido útil. No modificar el algoritmo todavía.

**Gate:** aprobar si el corpus, los canarios y el procedimiento se pueden
repetir; ajustar si el baseline o las métricas no permiten comparar; desechar
la línea si no se puede obtener una referencia fiable.

### M1 — Chunks seriales y equivalencia

Implementar segmentación semántica, filtrado serial por chunks y unión estable.
Probar que para snapshots que caben en el límite el resultado coincide con el
filtro anterior; para snapshots grandes, verificar orden, ausencia de bloques
perdidos y estado correcto de truncación global.

**Gate:** no seguir si el nuevo camino pierde contenido, cambia resultados
pequeños sin explicación o marca incompleta como completa.

### M2 — Workers experimentales

Procesar el mismo conjunto de chunks con 1, 2 y varios workers acotados. Medir
serial frente a hilos y procesos persistentes, incluyendo todo el coste de
preparación y unión. Añadir controles de errores, timeout, cancelación y
resultados fuera de orden.

**Gate:** aprobar solo una configuración que mejore tiempo de pared de manera
repetible sin regresiones de contenido ni un coste de memoria inaceptable. Si
no gana, conservar chunks seriales y desechar el pool paralelo.

### M3 — Generalización y adversarial

Repetir la comparación en las cinco categorías de páginas (documentación,
GitHub, noticias, Wikipedia y producto) y en una fixture adversarial que ponga
texto importante en `aside` y ruido dentro de `main`. Revisar las previews y
comprobar que datos importantes, orden y marcas de contenido no confiable se
conservan.

**Gate:** si falla fidelidad en alguna estructura, corregir o declarar ese
perfil no compatible; no ocultar el fallo con un promedio agregado.

### M4 — Decisión de adopción

Comparar el sistema completo con M0: serial actual, chunks seriales y Dataflow
con workers. La decisión documenta beneficios, regresiones, límites y qué
modo quedaría activado. La adopción en otros consumidores requiere otro gate y
su propia prueba; no es parte de este milestone.

**Gate final:** aprobar el primer consumidor de navegador, mantenerlo como
experimento opcional o desechar la concurrencia. Si se decide descartar código,
primero se presenta el manifiesto de archivos a retirar; los cambios no se
borran sin seguir la autorización de destrucción del repo.

## Criterios de aceptación

1. El camino por chunks conserva de forma determinista el orden del snapshot.
2. El comportamiento de snapshots bajo el límite coincide con el filtro
   existente, salvo cambios deliberados documentados y probados.
3. Los chunks grandes no se pierden en silencio; truncación final y errores se
   reflejan en el estado de calidad.
4. Un worker que falla o se retrasa no permite publicar un resultado parcial
   como completo.
5. La concurrencia está acotada y se selecciona con mediciones reproducibles
   frente al baseline serial.
6. No cambia el alcance del MCP Playwright ni las autoridades de seguridad.
7. La preview conserva el carácter no confiable y el consentimiento sobre el
   texto exacto que recibirá el modelo.
8. Cada gate termina con evidencia comparativa y una decisión explícita antes
   de continuar.

## Riesgos y preguntas para implementación

- El snapshot completo llega como texto antes del segmentador; esta primera
  versión limita el coste del filtrado, no la memoria usada al capturar la
  página.
- Un pool de hilos puede no acelerar trabajo Python limitado por CPU; un pool
  de procesos puede perder la ganancia por serialización o arranque. M2 decide
  con datos.
- El filtro actual depende de indentación y subárboles. La segmentación debe
  demostrar que mantiene ese estado a través de fronteras.
- El umbral de tamaño, concurrencia predeterminada y mejora mínima aceptable se
  fijarán con el baseline de M0, antes de aceptar M2.
