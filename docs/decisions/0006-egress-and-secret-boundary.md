# ADR 0006: Egress cerrado y secreto solo en su destino

- **Estado:** propuesto en M5. No está revisado por otra persona. No autoriza red universal, el bucle autónomo ni marcar G5 como APROBADO.
- **Fecha:** 2026-10-02
- **SHA de partida:** `8b701239df9bb0a62b4de4b09f7ad55a9808f75a`
- **Plan:** [roadmap Classic/Security](../roadmap-classic-security-ux.md)

## Contexto

El sandbox de comandos compartía el namespace de red del host y se apoyaba en seccomp. El transporte del provider usaba el proxy del entorno. Un commit local no es una publicación, y no había una acción que publicara un ref con destino y digest exactos. G6 (bucle, cancelación y retry) no está hecho. Abrir red para cualquier proceso, o el bucle, aquí sería autonomía falsa.

## Decisión

`review_destination` corre antes de abrir un socket con credencial. Un proxy ambiente que el destino no tiene en `NO_PROXY` es otro destino: la llamada no sale. Un nombre DNS que resuelve a una dirección privada, de loopback, link-local, multicast, reservada o no especificada se niega. Una IP escrita en la URL configurada sigue siendo ese destino, incluido `127.0.0.1` para un modelo local. El stream de chat conecta a la dirección revisada y mantiene el nombre original en el encabezado `Host` y en TLS. No se sigue un redirect.

El sandbox de un comando de proyecto no comparte el namespace de red. No hay un grant que vuelva a encender esa ruta. Seccomp sigue negando sockets. LSP no cambia en este hito: su arranque sigue con `--share-net` y con seccomp.

`git.push` es una acción distinta de `git.commit`. No está en el preset de Classic, no está en el perfil quieto, no es una tool del modelo y no tiene transporte por defecto. Hace falta el remoto https, el ref y el digest de 64 hex, un grant de ese remoto y una aprobación de esa petición. Cambiar el destino o el digest invalida la aprobación. Sin transporte registrado no hay efecto.

El proceso de un servidor MCP local recibe la base fija (`PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`, `USER`, `SHELL`) y las variables escritas en `mcp.json`. No hereda las claves de proveedor del host. `provider.request` sigue fuera del perfil quieto. Desactivarlo, o un host que no está en el grant, no llama a otro provider. `ISYMOTRON_API_KEY` solo describe al provider activo.

Descargar no es `provider.request` ni `workspace.command.run`. No se añade una acción de descarga ni un grant de red universal.

## Qué no hace

No abre el bucle del agente. No marca G5 como APROBADO. No hace un `git push` real: el transporte de prueba es un callback en el proceso. No mete MCP dentro del sandbox de comandos. No cierra el namespace de red de LSP. `urllib` síncrono y el SDK de Anthropic pueden resolver el nombre otra vez después de la revisión; el stream de chat sí clava la dirección que revisó. Un `mcp.json` escrito por la persona puede contener una clave que esa persona puso ahí.

## Alternativas rechazadas

- Seguir el proxy del entorno. El proxy es otro destino y vería metadatos, o el bearer si el tramo es HTTP.
- Dejar `--share-net` y fiarse solo de seccomp. El namespace cerrado es la frontera de red del proceso.
- Meter `git.push` en Classic o en el perfil quieto. Publicar no es trabajo local ordinario.
- Tratar la descarga como red ya concedida al provider o al comando.
