# Logos de proveedores — 11 de octubre de 2026

Alcance pedido: empezar por los iconos de la barra superior siguiendo el mockup
seleccionado. La captura adicional de Providers incluye el catálogo y Mis conexiones.

## Entrega

- SVG de NVIDIA, OpenAI/ChatGPT, Anthropic, Claude, Gemini, Grok, Groq, Ollama,
  LM Studio, Mistral, DeepSeek y OpenRouter.
- Misma identidad en barra superior, catálogo, conexiones guardadas, encabezado
  de la conexión y selector de suscripciones. El nombre permanece visible.
- Logos de color conservan su color; los monocromos se pintan claros en el tema oscuro.
- Tamaños 22/24/28 px con rasterización a doble resolución en Qt.
- Protocolos compatibles y endpoints desconocidos conservan el icono genérico.
  El logo no indica autenticación, disponibilidad ni capacidades del modelo.
- Endpoints conocidos prevalecen sobre el nombre editable de una conexión.
  No se deduce el proveedor del nombre del modelo servido por un tercero.

Origen: [Lobe Icons](https://github.com/lobehub/lobe-icons), commit
`c385b2b8d1f9e19aa86e628d4e23c91ee1111a47`,
[licencia MIT](https://github.com/lobehub/lobe-icons/blob/c385b2b8d1f9e19aa86e628d4e23c91ee1111a47/LICENSE).
Bytes originales, licencia, URLs y SHA-256 en `ui/assets/providers/`.
Las marcas pertenecen a sus titulares; no implican afiliación.

## Siguientes cambios pedidos, pendientes

1. Provider: lista visible al hacer clic, flecha y estado; selección clara en la barra.
2. Modelos: lista seleccionable y buscable con el catálogo descubierto, sin depender
   exclusivamente de las flechas del teclado. Revisar persistencia y propagación
   del catálogo entre Providers y la barra superior.
3. Conversaciones: acciones por conversación (renombrar, exportar y gestionar),
   título acotado con elipsis y tooltip, scroll vertical dentro de una caja limitada.
4. Continuar la jerarquía, espaciado y superficies del mockup aprobado.

Esta entrega agrega identidad visual. Los problemas de selección y conversaciones
siguen pendientes; no se presentan como corregidos por agregar los logos.

Comprobaciones de entrega: sintaxis Python, XML de SVG, diff y empaquetado con
los assets/licencia incluidos. Sin nuevas pruebas automatizadas ni solicitudes a
las cuentas. **NOT_DEMONSTRATED**: revisión visual de la aplicación instalada
y regresión funcional de los selectores.
