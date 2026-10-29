# `isycode actualizar` — diseño

## Objetivo

Dar a quien usa ISyCode una orden fácil para poner al día la instalación. En un
checkout de desarrollo, la orden debe enseñar los cambios que llegarían y
proteger el trabajo local. En una instalación de usuario sin checkout, debe
obtener y preparar una copia actual desde el repositorio oficial, sin pedirle a
la persona que conozca Git.

## Comportamiento

### Checkout de desarrollo

1. Resolver el checkout desde el propio paquete/launcher; no usar el directorio
   de trabajo actual, que puede ser cualquier proyecto.
2. Comprobar que el remoto configurado corresponde a ISyCode y consultar su
   rama upstream. No asumir `main` o `master` si Git ya declara otra rama
   predeterminada.
3. Consultar el remoto sin cambiar archivos. Si hay cambios rastreados o no
   rastreados, conservarlos, no integrar commits y presentar un resumen del
   estado local, los commits entrantes y el diff entrante. Señalar con claridad
   que todavía no se actualizó.
4. Si el árbol está limpio y solo hay commits entrantes, avanzar la rama
   únicamente mediante fast-forward. Si hay divergencia, previsualizarla sin
   mutar el checkout. Integrar con un merge commit cuando Git confirme que no
   hay conflictos. La única excepción regenerable es un conflicto aislado en
   `docs/security/m15-authority-coverage.json`: durante el merge, regenerarlo
   desde `authority_coverage_snapshot()` del código ya integrado. Si aparece
   cualquier otro conflicto, remoto incorrecto o fallo de previsualización/red,
   detenerse y mostrar las rutas afectadas.
5. Después de avanzar, sincronizar el entorno virtual del checkout con las
   dependencias declaradas y confirmar la versión instalada. No usar `sudo`, no
   borrar el entorno anterior y no reiniciar ISyCode dentro del proceso actual.

### Instalación de usuario sin checkout

1. Obtener el código del remoto oficial en
   `$XDG_DATA_HOME/isycode/source` (por defecto
   `~/.local/share/isycode/source`). Si ya existe allí un checkout válido,
   actualizarlo con las reglas anteriores.
2. Crear o actualizar un entorno virtual de ISyCode en el mismo espacio de
   datos e instalar el proyecto desde ese checkout.
3. Hacer que el comando `isycode` de la persona llegue a esa instalación solo
   cuando el launcher existente sea claramente propiedad de ISyCode y pueda
   actualizarse de forma acotada. Si el nombre ya pertenece a otra instalación
   o herramienta, conservarlo y mostrar el comando o ajuste de PATH exacto para
   activar la copia preparada.
4. No ejecutar con privilegios, no tocar claves ni permisos del workspace y no
   escribir dentro del proyecto abierto por el usuario.

## Interfaz

- `isycode actualizar`: consulta y realiza la actualización segura que permita
  el estado encontrado.
- `isycode actualizar --check`: consulta y muestra el resumen/diff; puede
  actualizar metadatos/objetos Git necesarios para comparar, pero no cambia la
  rama activa, los archivos del checkout ni instala paquetes.
- Salida en español, con estado final inequívoco: actualizado, ya al día,
  preparado pero requiere enlazar el comando, o detenido para proteger cambios.
- Los fallos incluyen una acción concreta que la persona pueda ejecutar; no
  mostrar trazas con credenciales ni invocar shells para construir comandos.

## Seguridad y límites

- El remoto de bootstrap es el HTTPS canónico
  `https://github.com/DannyBaanks/ISyCode.git`. Para un checkout existente se
  permite el remoto GitHub configurado si identifica este repositorio o un fork
  explícito del usuario; nunca sustituirlo en silencio.
- Git se ejecuta con argumentos separados, directorio de trabajo explícito y
  configuración de hooks/filtros externa desactivada o validada. No se usa
  `pull`, reset, checkout forzado, stash, clean ni rebase.
- El estado sucio se considera dato del usuario, incluidos archivos no
  rastreados. El actualizador no los agrega, mueve ni elimina. Un conflicto con
  nuevos archivos detiene la actualización.
- Ningún conflicto de código o de datos se resuelve automáticamente. Solo se
  permite regenerar el snapshot de cobertura si es la única ruta en conflicto;
  la generación falla o detecta otra ruta y el merge se aborta.
- Los paquetes de sistema (por ejemplo `.deb` o AppImage) no se sustituyen a
  escondidas; si no se pueden administrar desde el checkout de código fuente,
  el comando identifica el formato y explica el método correspondiente.
- `--check` no cambia archivos del checkout ni instala. La actualización normal
  es una solicitud explícita de red y de cambios locales del propio ISyCode.

## No objetivos iniciales

- Actualización automática en segundo plano.
- Saltarse los permisos de Workspace Authority, IsySentinel o el journal para
  operaciones sobre proyectos.
- Actualizar herramientas externas o runtimes de IsyMotron.
- Garantizar firmas de releases: el repositorio no publica actualmente una
  política de firma de commits/releases que este flujo pueda verificar.
- Hacer push, crear commits de usuario o resolver conflictos de código/datos
  automáticamente.

## Criterios de aceptación

1. Un checkout limpio atrasado puede avanzar solo si Git permite fast-forward.
2. Un checkout con cambios rastreados o no rastreados no pierde ni altera esos
   archivos; la salida enumera lo entrante y ofrece el diff que hace falta.
3. La divergencia se integra conservando ambas historias solo cuando no hay
   conflictos, salvo el snapshot generado que se reconstruye por su función
   canónica. Cualquier otro conflicto, remoto inesperado o fallo de red no muta
   HEAD ni deja cambios de merge sin resolver.
4. Un usuario sin checkout obtiene un clon y un entorno aislado reproducibles;
   los comandos existentes ajenos se conservan.
5. `--check` no altera el checkout ni el entorno virtual; cualquier escritura
   necesaria queda limitada a metadatos/objetos del repositorio Git.
6. Las pruebas usan repositorios Git temporales y remotos locales, sin depender
   de GitHub ni de credenciales reales.
7. La salida de ayuda y README explican el comando y sus límites en español.

## Preguntas para revisión

- ¿Debe el flujo de instalación sin checkout escribir el launcher del usuario
  automáticamente cuando `~/.local/bin/isycode` ya existe como script generado
  por `pip`, o debe detenerse y pedir que se confirme ese reemplazo?
- Para un checkout con cambios locales, ¿basta con mostrar el diff y detenerse,
  dejando que la persona vuelva a ejecutar `isycode actualizar` tras guardar
  sus cambios?
