```bash
python3 '/home/danny/Development/ISyCo Git/ISyCode/.agents/skills/isycode-design/scripts/catalog.py' list
```

Salida real:

```text
isycode-design | ISyCode · Design
isycode-option-boxes | ISyCode · Cajas y opciones
isycode-settings-sidebar | ISyCode · Settings y sidebar
isycode-text-copy | ISyCode · Texto y copia
isycode-icons-motion | ISyCode · Iconos y movimiento
```

# ISyCode Design Skills — guía de uso

**Regla de oro:** cada componente comparte el mismo estándar y los mismos tokens. Una skill describe cómo construirlo; su existencia no demuestra que la TUI ya lo implemente.

Este catálogo conserva la dirección que elegiste: **Contraste esencial**, negro/blanco, foco cian, sidebar plano y Settings por categorías. El perfil del comparador es Ubuntu Sans Mono, Unicode, 14 px y 1.3 de interlineado; la fuente y el tamaño real de la terminal se configuran fuera de Textual.

## Qué skill usar

| Skill | Para qué sirve |
| --- | --- |
| `isycode-design` | Estándar común, colores y selección de la skill adecuada. |
| `isycode-option-boxes` | Cajas de opciones, selectores, listas, formularios y menús. |
| `isycode-settings-sidebar` | Categorías de Settings, pestañas y secciones del sidebar. |
| `isycode-text-copy` | Space para expandir y copia de la selección exacta o de una caja explícita. |
| `isycode-icons-motion` | Símbolos con significado, estados y animaciones con alternativa estática. |

Pídeselo a Codex así; esto es un ejemplo de solicitud, no un comando de terminal:

> Usa $isycode-option-boxes para añadir un selector a ISyCode siguiendo nuestro estándar visual. Conserva la búsqueda, el teclado y el comportamiento actual de la acción.

Las instrucciones del repositorio llevan al estándar y después a la skill del componente. La selección automática depende del contexto; se puede mencionar la skill directamente. Codex documenta la lectura de `.agents/skills` dentro del repositorio y los enlaces simbólicos en su [guía oficial de skills](https://learn.chatgpt.com/docs/build-skills).

## Buscar una skill

```bash
python3 '/home/danny/Development/ISyCo Git/ISyCode/.agents/skills/isycode-design/scripts/catalog.py' search cajas opciones
```

Salida real:

```text
isycode-option-boxes | ISyCode · Cajas y opciones
```

La búsqueda ignora diferencias de mayúsculas y acentos. Todas las palabras deben coincidir en el nombre, resumen o etiquetas.

## Comprobar el catálogo

```bash
python3 '/home/danny/Development/ISyCo Git/ISyCode/.agents/skills/isycode-design/scripts/catalog.py' check
```

Salida real:

```text
OK: 5 skills; fingerprints, references and palette consistent
Scope: authoring catalog integrity; runtime TUI behavior is not checked
```

Esto verifica las huellas de `SKILL.md`, las referencias locales y la paleta compartida. No ejecuta la TUI ni comprueba el portapapeles de la terminal.

## Exponer las skills en este entorno

Ya quedaron enlazadas desde la carpeta local de skills de Codex a las carpetas del repositorio. El siguiente comando es repetible: conserva los enlaces correctos y se detiene si encuentra un destino diferente, sin reemplazarlo.

```bash
python3 '/home/danny/Development/ISyCo Git/ISyCode/.agents/skills/isycode-design/scripts/install-local.py'
```

Salida real:

```text
READY: isycode-design
READY: isycode-option-boxes
READY: isycode-settings-sidebar
READY: isycode-text-copy
READY: isycode-icons-motion
Canonical files stay in the ISyCode repository; reload skills/start a new Codex session to refresh discovery.
```

Los archivos originales permanecen en `.agents/skills/` de ISyCode. Si no aparecen en el selector, inicia una nueva sesión o reinicia Codex; la actualización del selector en una nueva sesión aún no se comprobó aquí.

## Añadir o cambiar una skill

1. Edita la skill especializada; para una capacidad nueva, crea una carpeta con `SKILL.md` y `agents/openai.yaml` siguiendo las existentes.
2. Reutiliza el estándar y los tokens. Si cambias la dirección visual por petición del usuario, actualiza esos recursos compartidos y deja constancia de la nueva decisión.
3. Añade o actualiza su entrada en `isycode-design/references/catalog.json`: nombre, resumen, etiquetas, ruta y SHA-256 del contenido de `SKILL.md`.
4. Repite la comprobación del catálogo y la validación de formato antes de darla por lista. Conserva la evidencia visual anterior; las referencias siguen siendo parte del diseño.

## Cómo interpretar el resultado

| Resultado | Qué significa y qué hacer |
| --- | --- |
| `OK` y código 0 en `check` | El catálogo es coherente; aún faltan las pruebas del componente cuando se implemente. |
| `READY` | Ya existe el enlace correcto; no se volvió a crear. |
| `LINKED` | Se creó un enlace al original del repositorio. |
| `No matching skills` | No hay coincidencias; prueba menos palabras. |
| `Unknown registered skill` y código 2 | `show` recibió un nombre que no está registrado; consulta la lista. |
| Código 1 | Referencia/huella/paleta inválida o destino local en conflicto; revisa el mensaje antes de repetir. |

## Trampas que evitar

- No crear una paleta independiente para cada menú ni copiar las skills a varias carpetas para editarlas por separado.
- No trasladar 14 CSS px directamente a puntos de GNOME Terminal: esa conversión no está comprobada.
- No asumir que SVG animado de Its Hover funciona en un widget de texto: su adaptación a caracteres requiere pruebas propias.
- No confundir el diseño de ISyCode Textual con el producto Qt ISyCode-IDE.
- No marcar como corregidos los gestos de copia/expansión por haberlos documentado. Siguen siendo objetivos a implementar y verificar.
- No confundir estas skills de desarrollo con el paquete de skills que ISyCode muestra dentro de la aplicación.

Las salidas completas, incluido el caso negativo de nombre inválido, están en [validation.log](validation.log). El alcance y las limitaciones están en [validation.json](validation.json).
