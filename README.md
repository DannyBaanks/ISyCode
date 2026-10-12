# ISyCode

**Tu proyecto, tu terminal, tus decisiones.**

Un agente de programación para leer código, proponer cambios, ejecutar pruebas
y revisar Git desde una sola terminal. Conversa con el modelo que elijas,
conserva tus sesiones localmente y controla qué puede hacer en cada proyecto.

[Empezar](#empieza-en-tu-proyecto) · [Guía de uso](docs/GUIA.md) ·
[Documentación](docs/reference/README.md) ·
[Reportar un problema](https://github.com/DannyBaanks/ISyCode/issues)

![ISyCode: inicio con paisaje y panel lateral del proyecto](docs/screenshots/2026-10-12-product/complete/01-overview.png)

*TUI real en un proyecto de ejemplo. [Capturas y reproducción](docs/screenshots/2026-10-12-product/GUIA.md).*

## Trabaja sin salir de la terminal

- **Del código al cambio.** Busca archivos y símbolos, lee contexto, revisa
  propuestas de edición y ejecuta comandos cuando los permisos lo permiten.
- **Un modelo a tu elección.** Providers como OpenAI, Anthropic, NVIDIA NIM y
  OpenRouter, además de endpoints locales con Ollama o llama.cpp.
- **Conversaciones que continúan.** Sesiones guardadas, cola de mensajes,
  búsqueda y recuperación de turnos interrumpidos.
- **Control por proyecto.** Modos Classic y Security, revisión de cambios,
  permisos por capacidad y registro de las acciones.
- **Una interfaz coherente.** Panel lateral plano, Settings por categorías,
  selección de texto precisa y opciones de alto contraste, ASCII y movimiento reducido.
- **Extensiones opcionales.** MCP local, ayuda LSP, Skills y Multi Harness
  para consultar otros entornos de agentes.

La interfaz está disponible en español, inglés y chino simplificado. Las
sesiones y preferencias se guardan en tu equipo; al usar un provider remoto,
el contexto enviado se procesa en ese servicio.

## Empieza en tu proyecto

Necesitas **Python 3.10 o posterior** y Git. Instala ISyCode desde el código:

```bash
git clone https://github.com/DannyBaanks/ISyCode.git
cd ISyCode
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
isycode
```

Con el entorno activado, entra en la carpeta de tu proyecto y ejecuta `isycode`.
Para Claude nativo, instala también el extra con
`python -m pip install -e '.[anthropic]'`.

1. Elige un workspace **recurrente** para guardar conversaciones o **temporal**
   para una sesión puntual, y selecciona Classic o Security.
2. Abre **Configuración → Conversación → Proveedores y modelos** y configura
   el provider que usarás.
3. Pide una tarea concreta: «Explícame este módulo» o «Añade esta prueba».
   Revisa las propuestas y habilita las capacidades que necesites.

La ejecución aislada de comandos requiere **bubblewrap y libseccomp en Linux**.
Consulta [instalación y actualización](docs/reference/installation.md) para
configuración, diagnóstico y plataformas.

**v0.1.0 · desarrollo activo.** La instalación desde el código es la vía disponible;
consulta [compatibilidad y verificación](docs/reference/verification.md) antes
de depender de una integración o plataforma específica.

## Todo en su lugar

**Configuración** reúne Conversación, Preferencias, Permisos y Conexiones.
Busca una opción y consulta su explicación sin recorrer una lista interminable.

![Configuración de ISyCode con categorías y preferencias](docs/screenshots/2026-10-12-product/complete/03-settings.png)

**Archivos** combina navegación, búsqueda y vista previa del proyecto con el
estado de la lectura.

![Panel de Archivos con un archivo en vista previa y recibo de lectura](docs/screenshots/2026-10-12-product/complete/02-files.png)

## Elige cómo trabaja el agente

**Classic** prepara las capacidades habituales de programación. Al confiar
explícitamente en una carpeta, las ediciones ordinarias y los comandos aislados
pueden continuar sin preguntar en cada paso. Los commits y otras operaciones
que requieren revisión conservan sus confirmaciones.

**Security** empieza con las capacidades apagadas y permite habilitarlas una
por una. Puedes cambiar de modo y revisar permisos en
**Configuración → Permisos → Authority & Security**.

Ambos modos conservan IsySentinel y el registro de acciones.
[Permisos, aprobaciones e integraciones](docs/reference/authority-and-integrations.md).

## Atajos para el día a día

| Acción | Atajo |
| --- | --- |
| Enviar / nueva línea | `Enter` / `Ctrl+J` |
| Detener un turno o volver | `Esc` |
| Abrir comandos | `/` o `Ctrl+P` |
| Mostrar el panel lateral | `Ctrl+B` |
| Expandir o contraer una caja enfocada | `Space` |
| Abrir las opciones de copia de una caja | Doble clic |
| Copiar exactamente el texto marcado | Selección con el ratón + `Ctrl+C` |

[Flujos, providers y todos los atajos](docs/reference/workflows.md).

## Aprende, participa y mejora ISyCode

- [Guía de uso en español](docs/GUIA.md): primeros pasos y trabajo diario.
- [Referencia del producto](docs/reference/README.md): instalación, comandos,
  permisos e integraciones.
- [Estándar visual y Design Skills](.agents/skills/isycode-design/SKILL.md):
  criterios compartidos para ampliar la TUI.
- [Contribuir](CONTRIBUTING.md): preparar el entorno y presentar cambios.
- [Seguridad e investigación](SECURITY.md): pruebas en entornos propios y
  cómo reportar vulnerabilidades de forma privada.
- [Issues](https://github.com/DannyBaanks/ISyCode/issues): errores y propuestas.
- [Roadmap](docs/ROADMAP.md): evolución del producto.
