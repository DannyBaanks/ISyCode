# ADR 0003: Staging por copia, no por overlay

- **Estado:** propuesto en M2. No está revisado por otra persona y no autoriza autonomía.
- **Fecha:** 2026-10-02
- **SHA de partida:** `be8f26974652f6510dbc529b41ff4b5278c37439`
- **Plan:** [roadmap Classic/Security](../roadmap-classic-security-ux.md)

## Contexto

Un comando aprobado escribía directo en el checkout. Bubblewrap aislaba red, entorno y rutas sensibles, pero el bind del workspace era escribible. M2 pide que shell, Python y las escrituras tipadas muten un staging y que el árbol del usuario cambie solo al promover un diff medido.

## Decisión

El backend es una copia. `prepare_staging` duplica el workspace fuera del checkout. El comando recibe esa copia en `/workspace`. Al salir, `measure_changes` compara el índice de la copia con el del momento de la copia. `run()` promueve ese diff. `run_staged()` no lo promueve: es la costura de observación, no un camino para que el modelo se salte la promoción.

La escritura tipada guarda los bytes aprobados en un temporal fuera del workspace y solo entonces llama al replace que ya existía. Hasta ese replace, el archivo del usuario no aparece.

No hay fallback al host. Si la copia no cabe, si no hay espacio, o si el sandbox no arranca, el comando no se ejecuta.

Tope de copia: 512 MiB. Además hace falta espacio libre de al menos `tamaño * 2 + 64 MiB`. Por encima de eso el resultado es error y el árbol no se toca. Un checkout más grande no se ejecuta «a medias».

## Qué se midió en esta máquina

Linux 7.0.0-34-generic, Bubblewrap 0.9.0, libseccomp.so.2, ext4. `bwrap --help` tiene `--bind`, `--ro-bind`, `--unshare-user`, `--uid` y `--cap-add`. No tiene overlay.

`unshare --user --map-root-user --mount` falló con `uid_map: Operación no permitida` (exit 1). Dentro de Bubblewrap con `--uid 0 --cap-add CAP_SYS_ADMIN`, `mount -t overlay` falló con «no se puede montar overlay para solo lectura» (exit 32). fuse-overlayfs, firejail y nsjail no se usaron.

Un `bwrap --unshare-all` con el mismo patrón de montajes del producto deja un root que solo contiene `workspace`, `tmp`, `dev`, `proc` y las libs. `/home` no está. `uid` dentro es el del usuario y `CapEff` es 0. `mount` responde que hace falta ser superusuario. Un symlink absoluto hacia `/tmp/...` no modifica el archivo del host: `/tmp` del sandbox es un tmpfs vacío. `/workspace/../neighbor.txt` crea `/neighbor.txt` dentro del root del sandbox, no el vecino del host.

## Alternativas rechazadas

| Opción | Por qué no |
| --- | --- |
| Overlay en user namespace | No monta en este host. No se finge que sí. |
| Worktree de Git | No aísla ignorados, red, home ni procesos. |
| Hardlinks al original | Una escritura en el staging sería una escritura en el original. `copy2` crea inodos nuevos. |
| Ejecutar igual si la copia no cabe | Sería el fallback al host que el roadmap prohíbe. |

## Promoción

Se aplica archivo a archivo, deletes primero. No es atómica entre archivos: un corte a mitad deja un estado parcial. Eso es trabajo de M3, no una promesa de esta nota.

No se promueve:

- `.git`, `.isyroot`, `.isycode` ni un nombre sensible (`.env`, `*.pem`, claves)
- un symlink, ni antes ni después
- una ruta con `..` o absoluta
- un padre que sea symlink, aunque el destino resuelto caiga dentro
- un archivo cuyo bytes en el original ya no coinciden con la copia (edición humana)

Un directorio nuevo vacío no se promueve: solo entran archivos regulares, y los directorios que hagan falta para esos archivos se crean al promoverlos. Borrar un directorio vacío que el índice marcó como directorio sí se intenta, de dentro hacia fuera.

## Qué no cambia

Classic sigue pidiendo aprobación por cada edición y por cada comando. Esta nota no abre autonomía ni marca G2 como APROBADO. `safety.Budget` sigue sin ser el ledger de M3.

## Residuales

- La promoción de muchos archivos puede quedar a medias. M3 tiene que hacerla recuperable.
- 512 MiB deja fuera un checkout grande. El comando falla cerrado; no se sube el tope en silencio.
- El doble de pruebas (`FAKE_BWRAP`) no es un namespace: no aplica máscaras ni tmpfs. La contención de symlink, `.env`, journal, vault y `mount` se afirma con Bubblewrap real.
- `RLIMIT_NPROC` cuenta los hilos del uid. En el doble, un `mkdir` externo puede fallar con `Cannot fork` si el usuario ya supera el tope. Dentro del namespace real el `mkdir` del ataque sí corrió.
- Windows y macOS no tienen este backend. Un skip de Bubblewrap no aprueba comandos allí.
