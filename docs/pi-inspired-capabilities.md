# Funciones para evaluar después de la integración visual

Fecha: 2026-10-03. Propuesta basada en el changelog compartido por Danny y las
[referencias de codemode](https://github.com/earendil-works/pi/blob/v1.0.0/packages/coding-agent/docs/codemode.md)
y [modelos de Pi](https://github.com/earendil-works/pi/blob/v1.0.0/packages/coding-agent/docs/models.md).
Este documento describe diseño pendiente; no habilita capacidades nuevas.
La sonda de CLI del 2026-10-03 y los ítems que no son imágenes viven en
[M17 del roadmap](ROADMAP.md). Este archivo no las sustituye.

| Prioridad | Idea | Adaptación para ISyCode | Criterio para entregarla |
|---|---|---|---|
| 1 | Generar y editar imágenes | Un artefacto con vista previa, modelo elegido y archivo recuperable desde la conversación | Generación real, cancelación, límites de tamaño y formato, guardado autorizado y recuperación al reabrir |
| 2 | Catálogo por capacidad | Separar modelos de chat, imagen y clasificación; mostrar solo operaciones que el adapter sabe ejecutar | Una credencial válida no debe hacer aparecer capacidades que no existen |
| 3 | Herramientas bajo demanda | Resumen corto al iniciar; cargar esquemas e instrucciones cuando se soliciten | Medir tokens antes/después y verificar que el inicio no espera por MCP opcionales |
| 4 | Errores con siguiente paso | Explicar el argumento esperado, el modelo disponible o el ajuste necesario | La guía debe corresponder al error real, sin reintentar operaciones automáticamente |
| 5 | Conversaciones largas | Previsualizaciones limitadas por líneas visibles, caches de uso y persistencia desde el primer mensaje | Medir memoria y latencia con una conversación grande; recuperar una sesión interrumpida |

## Primera entrega propuesta: imágenes

El modelo de chat solicita una operación con prompt, modelo de imagen y, para
edición, referencias a archivos existentes. Un owner dedicado revisa la llamada,
la credencial del provider, el host permitido y el destino de escritura antes
de ejecutarla. La UI muestra estado y cancelación durante el trabajo.

El resultado se valida como imagen, con límites explícitos de bytes y píxeles.
Se guarda un archivo y una referencia de artefacto en la sesión; el historial
no conserva cadenas base64 enormes. La tarjeta permite inspeccionar el resultado
y conocer el modelo utilizado. Si el terminal no puede mostrarlo, la misma
tarjeta ofrece abrir el archivo. Se contabiliza el uso que devuelve el provider;
un costo desconocido se muestra como desconocido.

No se requiere adoptar un ejecutor JavaScript para esta primera entrega. Si se
añade orquestación por scripts después, las llamadas seguirán pasando por los
owners existentes; se limitarán recursos y se distinguirán lecturas paralelas
de escrituras dependientes. Los resultados parciales deberán registrar qué
operaciones sí ocurrieron antes de una cancelación o un error.

## Conservar

El ASCII de bienvenida sigue siendo un recurso local de inicio. La generación
de imágenes es una operación separada y no se ejecuta para dibujar el logo.
OAuth para nuevos providers/MCP, modelos virtuales y clasificación automática
necesitan contratos y pruebas propios antes de ofrecerlos en el menú.
