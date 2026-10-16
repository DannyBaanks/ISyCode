# Platform parity verification — 2026-10-15

## Scope

Incremental native storage, recovery effects and trusted Git adaptation from commit `b80975517f8496b70b8f7c2d37f408cd839d6b27`. One source tree; no cross-repository runtime dependency. Authority/Sentinel/owners and per-action approvals remain in place. No release milestone is advanced.

Windows host: Windows 11 Home x64, build 10.0.26200, Xeon E5-2678 v3, Python 3.12.10, Textual 8.2.8, pywin32 312. Linux evidence uses the Docker `python:3.11` runtime and a non-root `parity` user. Container evidence is not a physical Linux terminal witness.

## Demonstrated results

| Run | Result | Evidence |
| --- | --- | --- |
| Original Linux subset | 46 passed | linux-baseline-script.log |
| Linux migration regression subset | 132 passed, 1 integration case deselected | linux-final.log |
| Windows migration regression subset | 124 passed, 1 skipped, 1 integration case deselected | windows-final.log |
| Windows final native storage/Git negative controls | 15 passed | windows-native-last.log |
| Windows final Git owners and read/edit/diff TUI flow | 28 passed | windows-git-last.log |
| Windows session continuity standalone | 13 passed | windows-continuity-final.log |
| Windows installer | Installed same package; version/entry point verification succeeds | windows-install-r2.log |
| Authority snapshot consistency | Pass after generated line references were refreshed | test_action_coverage.py targeted run; prior snapshot preserved as m15-before.json |
| Baseline controls for two broader UI failures | Both fail on the original commit as well | linux-existing-ui-controls.log |
| Broader Linux run before final corrections | 1246 passed, 5 failed, 11 skipped, 11 deselected; stopped at five failures | linux-suite-r2.log |
| Windows integrity-pinned resource catalog and activation | 2 passed after exact-byte restoration | windows-bundle-final.log |
| Windows legacy session and final adapter controls | 17 passed | windows-legacy-final.log |
| Isolated Windows wheel import/skill catalog | Native adapters load; 6 bundled skills validate | windows-wheel-skills.log and wheel build/install logs |
| Linux current-source corrections and storage acceptance | 107 passed, including bundle and legacy-session controls | linux-corrections-final.log |
| Windows multiprocess session continuity | 18 passed | windows-session-processes.log |
| Windows latest storage/Git contracts | 16 passed | windows-native-complete.log |

These runs overlap; do not sum the counts as unique tests. Some final safeguards were added after the larger subsets and have their own later targeted runs. Exact source and artifact hashes are recorded in hashes.json.

The Windows skipped test requires file-symlink privilege (WinError 1314). A separate native junction control passed; a skip is not a file-symlink security witness. Live provider transport in the coding-flow test is simulated, while reads, approved writes, Git and audit owners execute for real.

## Negative results and corrections

- Baseline Windows collection failed on unconditional `fcntl` imports. Native adapter selection removes that dependency from the shared owners.
- Baseline Windows effect/operation locks were unavailable. Native process/thread exclusion and release after writer death are now tested.
- Initial Windows TUI coding flow lacked Git tools because discovery only knew POSIX bin folders. Registry-based trusted Git discovery now targets the native binary and checks its dependency trees and every intermediate directory component.
- Review reproduced a temporary-file leak on flush failure, a stale-preimage overwrite during flush, omitted Git dependency/parent ACL checks and a `None == None` GitBoundary acceptance. Each received a failing regression test before correction.
- A thread on the same EffectLedger instance could be mistaken for lock reentry. The regression failed before adding an RLock around instance reentry.
- Privacy protection initially changed an ACL before rejecting a foreign owner. A negative test now proves rejection before any ACL change.
- Root-run Linux permission controls are not valid ordinary-user evidence. The later container regression runs use a non-root account.
- The first Windows installer run installed successfully but PowerShell treated pip's stderr notice as terminating. The installer disables the version-check notice and verifies native exit codes.
- A Linux wrapper run reported 103 passing tests but exited with a shell parse error after the live-mounted script was edited during execution. It is preserved as a harness failure, not accepted as a successful command.
- Full Windows suite execution was interrupted after a stalled question-screen test; its incomplete output is preserved. The baseline Linux question-screen test independently passes. This is not a full Windows suite certification.
- Windows checkout CRLF conversion invalidated the pinned bundled skill manifest and content. Twenty files were restored to their exact Git blob bytes; `.gitattributes` disables text conversion for the pinned bundle. Hash acceptance constants were not changed. Restoration hashes are retained in bundle-restoration.json.
- The broad Linux run also exposed a regression reading legacy mode-0644 transcripts inside private directories. `private_child` now preserves POSIX parent-directory privacy semantics and data bytes, while Windows still requires a private file DACL. The broad run's other three non-baseline failures were the two bundle checks and this legacy case; targeted corrections are recorded separately. It was not rerun to completion and is not reported as a passing full suite.

The broader Linux suite and its controls are recorded separately in linux-suite-r2.log and related evidence. The two known unrelated UI failures concern authority-menu geometry and file-preview clipboard behavior; their baseline failures are preserved, not relabelled as new platform regressions.

## Review and verification

An independent read-only reviewer examined the storage/Git changes and corrections. Final review found the unavailable-Git boundary case, which was reproduced and fixed. Review is not native execution evidence; test logs provide that evidence.

The M15 coverage snapshot changed only generated source-line associations (14 old/new line references). The previous bytes are retained in evidence. Updating that live snapshot is not release acceptance.

The native-contract CI workflow was added but has not been run on GitHub in this task. No product push, release or deployment is part of this local implementation.

## Exact reproduction

The Windows commands are in GUIA.md and the workflow's native-contract test command. Linux setup/commands are preserved in `evidence/linux-final.sh`; the mount is read-only and the source is copied into a disposable container checkout. Tests that need bubblewrap receive container-local namespace capabilities, not host configuration changes.

## NOT_DEMONSTRATED

Complete Windows product parity; native Windows command sandbox activation; all optional state-store/integration migrations; all-provider live inference; a separately logged-on Windows identity ACL witness; physical clipboard/font/mouse behavior; packaged EXE install/update flow; hardware power-loss recovery; and the GitHub-hosted full Windows suite run. The five-user acceptance matrix is explicitly waived for this request. Remaining work is enumerated in INVENTORY.md.

Windows recovery retains the documented same-user directory rename race in the final replacement interval. Neither platform claims universal filesystem compare-and-swap. File fsync plus write-through rename on Windows is documented separately from POSIX directory fsync.

Native API design references: [Microsoft file security and access rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights), [security descriptor operations](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-descriptor-operations), [MoveFileEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexa). Windows private-child handling accounts for [traverse bypass](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/security-policy-settings/bypass-traverse-checking); the file DACL still determines access.

## Native command sandbox continuation — 2026-10-14

The shared command owner now consumes a platform sandbox adapter. Linux
discovery, resource setup and Bubblewrap argv live in `platform_posix_sandbox.py`;
the public compatibility builder remains available. Windows has a native LPAC
launcher, atomic Job-list assignment, explicit E/S handles, private CPython
runtime/staging copies, runtime SHA bound to the approved request, and cleanup
with a protected ownership record. There is no native product activation:
`NATIVE_ACCEPTED=False` because execution storage limits are not met.

Windows real controls: **46 passed, 1 expected failure**, exit 0, 463.71 seconds,
in `evidence/windows-lpac-final-20261014.txt`. Controls include an approved
command promoting through the ledger with a receipt, refusal without approval,
timeout, cancellation without promotion, external-file and private-registry
denial, TCP/UDP loopback denial with working host witnesses, inherited argument
fidelity, marker protection, child termination, breakaway refusal, owner death,
recovery during copy/profile creation, invalid masks, junction refusal and
runtime-digest refusal. This suite tests the experimental backend directly;
owner fixtures enable availability temporarily and restore it.

The expected failure is separately executed with `--runxfail` in
`evidence/windows-lpac-budget-negative-20261014.txt`: native CPython wrote
**537919488 bytes (513 MiB)** and exited 0 where the proposed per-file limit
is 536870912 bytes (512 MiB). That control exits 1 and blocks activation.
Its bounded allocation was cleaned up. An earlier run skipped this control
for its conservative free-space threshold; the recorded negative run preserved
1 GiB of free-space margin. No quotas or virtual volumes were configured.

The first broad native attempt had 44 passes and one recovery failure: an
exited process object remained openable and was incorrectly reported ACTIVE.
The corrected recovery checks the process handle's termination signal as well
as PID/birth. That earlier raw output is preserved in
`evidence/windows-lpac-pre-recovery-signal-fix-20261014.txt`.

Review also reproduced an original-workspace junction disclosing seeded
external data before isolation. Shared staging and sensitive scanning now use
`winfs.is_link`; the owner junction negative control passes. Marker-directory
rename and exit code 259 also have reproduced regression controls. Job-list
assignment removes the creation/assignment interval. Ownership metadata is
written before copying or creating the profile, durably and privately; recovery
accepts only an explicitly requested owned scratch directory.

Authority/approval regression: 30 passed, exit 0 in
`evidence/windows-sandbox-authority-20261014.txt`. The generated M15 source-line
snapshot was refreshed again after moving POSIX helpers, with its earlier bytes
preserved as `evidence/m15-before-native-sandbox-20261014.json`. No milestone is
advanced by this refresh. These runs overlap with other selections and are not
a unique total of product acceptance cases.

Linux evidence is container execution as a non-root user, not a physical Linux
terminal. Initial attempts had a nonexistent test filename (exit 4), then 56
passes/2 skips and a diagnostic wording failure (exit 1). The original POSIX
diagnostic was restored. A subsequent pre-move run passed 57 tests with 3
Windows-only skips. Its bytes are preserved separately; the final current-source
run is `evidence/linux-sandbox-final-20261014.txt`, using the exact script
`evidence/linux-sandbox-current.sh`.

`registryRead` was the minimal fixed capability that restored unmodified
CPython activation contexts, Winsock initialization and child creation. There
are no networking capability SIDs. A temporary private-copy manifest-removal
experiment was discarded; installed and copied runtime binaries now keep their
original bytes. Source-volume-root scratch avoids private Temp ancestry without
changing host parent ACLs. The current token lacks SeManageVolumePrivilege;
virtual-volume attachment remains NOT_DEMONSTRATED.

Operation and pending storage choices are documented in
[the Windows sandbox guide](WINDOWS-SANDBOX-GUIA.md). Product activation, bounded
execution storage, non-CPython runtimes/project dependencies, wider IPC/device
and IPv6/Internet controls remain NOT_DEMONSTRATED. Earlier whole-product parity
limitations still apply.

Final delta controls after disk preflight and compatibility-export fixes:
**18 passed**, exit 0, 239.35 seconds, in
`evidence/windows-sandbox-final-delta-20261014.txt`. The low-space control now
refuses before allocation; the preparation stage is capped at 512 MiB. This
does not fix the execution-writing limit. The scratch left by the earlier red
low-space test was recovered through its exact protected ownership record.
A selection typo (exit 4) is preserved separately.

The final independent review caught an omitted POSIX timeout constant import;
its failing run and the earlier compatibility-export collection failure are
preserved as `linux-sandbox-posix-timeout-regression-20261014.txt` and
`linux-sandbox-posix-export-regression-20261014.txt`. Neither is discarded or
treated as a passing run. CI now selects real native Windows prototype controls
with the activation guard; GitHub execution of that new step is NOT_DEMONSTRATED.

Final Linux current-source result: **77 passed, 3 Windows-only skips**, exit 0,
182.67 seconds, `evidence/linux-sandbox-final-20261014.txt`. Public compatibility
helpers and the moved bootstrap execute successfully. Final Windows integrity
selection: **4 passed**, exit 0, 9.67 seconds,
`evidence/windows-sandbox-integrity-final-20261014.txt`. Exact selection commands
and scope are recorded in `evidence/windows-sandbox-final-runs-20261014.json`;
the updated `hashes.json` covers evidence, source and docs while retaining the
previous manifest as historical evidence.

## Profile-storage continuation — 2026-10-14

Two additional real controls reproduced writes outside reviewed scratch: the
AppContainer local-data directory and its own registry storage. Environment
variables alone did not confine either. The red outputs are retained in
`windows-profile-storage-red-20261014.txt` and
`windows-profile-registry-control-20261014.txt`. The freshly-created profile
folder is now read-only to LPAC across its entire tree. Before ResumeThread,
the launcher verifies the actual child's AppContainer SID, discovers its own
registry through temporary impersonation, restores the caller and applies a
protected read-only DACL. The installed runtime and unrelated host parent
permissions are not broadened.

Intermediate registry attempts failed before any user-code resume: pywin32
PyHANDLE context-manager mismatch, lazy UTF-16 codec import under impersonation,
native registry namespace casing and storage names using monikers rather than
SIDs. Each raw failure is retained. The final implementation uses documented
token/profile APIs and measured key names, not a guessed registry layout.

Full post-registry-hardening selection: **54 passed, 1 explicitly deselected**,
exit 0, 557.79 seconds in `windows-profile-hardening-final-20261014.txt`.
The unchanged failing 513 MiB budget control was intentionally excluded from
this selection; its earlier negative evidence still blocks product activation.
This result precedes the final namespace restriction below, which has its own
targeted regression selection.

Independent review reported no product-code regression and requested stronger
identity/failure/non-target witnesses. Six initial final controls passed in
91.90 seconds. An earlier test-harness failure used an unsupported pywin32
descriptor method; that output remains historical. Follow-up review found the
sibling-folder snapshot was too late to witness target preparation. The
corrected control passed once in 22.05 seconds after snapshotting before
preparing and launching the target. Review is recorded in
`windows-profile-storage-review-20261014.md`; results are overlapping selections,
not a summed acceptance total.

IPv4 and IPv6 TCP/UDP loopback probes used functioning host witnesses. Internet
and wider IPC/device acceptance remain NOT_DEMONSTRATED. Linux product source
and owner behavior were not changed by this continuation; its earlier recorded
77-pass/3-skip selection remains earlier evidence, not a newly rerun claim.

The proposed [bounded storage design](WINDOWS-STORAGE-DESIGN.md) recommends a
fixed-size VHD-backed NTFS volume provisioned explicitly by an operator and
consumed by ISyCode without administrator elevation. Raw current privilege and
named driver/service observations are preserved; no volume, quota, driver or
administrator service was created. The design is proposed, not implemented.
Native product activation and the execution-storage ceiling remain blocked.

Final namespace restriction shares one prefix predicate with creation and
recovery and refuses other profile names before registry discovery or resume.
The real seeded non-target-name control was first red and its output is retained.
Final targeted current-source selection: **15 passed**, exit 0, 174.36 seconds
in `windows-profile-scope-final-20261014.txt`, including all seven registry
witnesses, recovery, approved owner promotion, profile-folder refusal and
native extension loading. Authority snapshot: **1 passed**, exit 0, 5.93 seconds
in `windows-profile-authority-snapshot-final-20261014.txt`. Raw evidence is hashed
with sources/docs; the preceding manifest is preserved separately. CI includes
the new registry controls; GitHub execution remains NOT_DEMONSTRATED.

## Bounded Windows provider continuation — 2026-10-14

The user approved the implementation plan with “SI AHORA SI SGAMOS :)”. The
earlier statement that bounded storage was only proposed is historical. The
provider/configuration, retained identity lease, volume-root allocator, schema2
recovery and backend `windows-lpac-job/2` are now implemented. Registration
binds measured identity; preview/start bind it again; finish checks identity
before the shared owner measures/promotes. Cleanup tries every resource and
retains ownership if the volume cannot be verified. No shared Authority,
Sentinel, approvals, ledger or POSIX owner semantics were changed.

Implementation runs on Windows 11 10.0.26200, Python 3.12.10 with pywin32 312;
ctypes layouts were checked against SDK 10.0.26100.0. No administrator attach,
format, resize, quota, driver or service operation was executed. The CLI has
only inspect-image, inspect-volume and register. Explicit private host config
is selected via ISYCODE_WINDOWS_SANDBOX_STORAGE_CONFIG, never discovered from
a workspace. No C:/D: scratch fallback exists in the product backend. Direct
historical resource experiments retain their separate optional-lease API.

Recorded selections, not an additive acceptance total:

- Initial model/API: 26 passed; configuration continuation: 34 passed. Raw red
  interface failures and green results are retained in their unique logs.
- Lease/resource/schema1 recovery selection: 59 passed, exit 0, 267.02 seconds.
  Native backend/owner selection before final extra controls: 15 passed, exit 0,
  114.05 seconds. These were observed directly in the tool transcript.
- Full native continuation: **108 passed, 8 skipped, 1 deselected**, exit 0,
  657.49 seconds, `windows-bounded-storage-final-20261014.txt`. The historical
  ordinary-scratch execution-budget negative was excluded explicitly. This
  collection preceded the final extra API/config/recovery and VHD controls;
  their separate selections below must not be added to this total.
- Provider/API/configuration and real-VHD selection before the final compile
  control: 45 passed, **13 skipped**, exit 0, 1.84 seconds; raw
  `windows-bounded-provider-current-r2-20261014.txt`. Each real-VHD skip explicitly
  says NOT_DEMONSTRATED. These fakes/negative ordinary-disk probes certify no
  real quota or successful positive VHD inspection.
- Final acceptance-only selection: **13 skipped**, exit 0, 0.35 seconds,
  `windows-bounded-real-acceptance-current-20261014.txt`. This is absence of
  real-VHD evidence, not acceptance. Generated sparse/compression/device
  programs also compile in a separate synthetic control without execution.
- Final current provider regression, including generated-program compilation:
  **46 passed, 13 skipped**, exit 0, 1.23 seconds,
  `windows-bounded-provider-current-r3-20261014.txt`.
- Schema2 refusal and parent-ACL preservation: 3 passed, 6 deselected, exit 0,
  13.04 seconds, `windows-bounded-recovery-final-20261014.txt`.
- Authority snapshot: 1 passed, exit 0, 6.14 seconds,
  `windows-bounded-authority-snapshot-20261014.txt`.

Independent review found and resolved mixed backing/VirtDisk handles and
incomplete cleanup after Close failure; see the review record. Ancestor handles
exclude delete-sharing, dependency/physical device paths must correspond, and
truncated SDK responses fail closed. CI includes the provider controls and
explicit real-VHD skips; no administrative provisioning is added to CI.

**NOT_DEMONSTRATED:** a real private fixed VHD, quota exhaustion, logical size
under sparse/compression, volume devices, real reboot/remount/forced detach,
and approved promotion on that volume. Fixed physical capacity alone is not
evidence for the logical-file ceiling. Operator commands and prerequisites are
in WINDOWS-STORAGE-GUIA.md; a provisioned but invalid config fails the tests,
rather than being skipped. Broader Internet/IPC/device/runtime acceptance also
remains open. `NATIVE_ACCEPTED=False` remains; the historical 513 MiB ordinary
scratch failure is preserved, not rewritten as a pass. Prior Linux evidence
was not rerun because no shared owner/POSIX contract was changed.

Integrity closure: the provider manifest verified 195 exact local files, and
30 changed committed files matched those bytes. An extra whole-index comparison
reported `AssertionError: README.md` because that unchanged baseline text file
has checkout CRLF/LF conversion. It was not edited. The manifest intentionally
attests local bytes, not a universal clone-byte hash; changed provider sources,
parity documentation and raw evidence are checked separately against Git.
This observation is retained in `windows-bounded-committed-bytes-20261014.json`.

## Operator-authorized real VHD preparation — 2026-10-14

The user explicitly requested “K ENTONCES PREPARALA”, authorizing the operator
step. A fresh GUID-named directory was created on D: with user/SYSTEM/admin
access, then an administrative helper was launched through Windows RunAs.
No existing host disk was selected or formatted. DiskPart created a new fixed
classic 512 MiB image; the helper correlated its SDK physical device with
Get-DiskImage/Get-Disk before initialization, partition creation and NTFS format.
An independent read-only review found no blocking association/scope defect.

The first helper's Set-Acl call did not persist a protected root DACL on this
host; the normal-user inspector correctly refused it. The root was corrected
with the existing named Win32 security adapter, only after verifying the new
image association, NTFS/capacity and private backing. The operator helper now
uses the same named security API. Its original executed bytes, SHA and output
remain archived separately. The provider also had a real API path defect:
HostVolumeName lacked the root separator required by GetDriveType. A watched
red regression and one-line normalization fixed it; all 12 API controls pass.

Normal-user inspection and private registration now pass. Measured filesystem
capacity is **535752704 bytes**, virtual image capacity is 536870912 and fixed
backing-file length is 536871424 including its footer. GUID/serial/image ID/file
ID and NATIVE_ACCEPTED=False appear in the registered-inspection raw log. The
private storage.json remains outside Git; its selection is recorded locally
in config-path.txt beside the new image, not installed globally.

Real acceptance is now a demonstrated negative result: **13 failed**, exit 1,
183.72 seconds, `windows-vhd-real-acceptance-first-20261014.txt`. All failures
occurred at LPAC process creation (WinError 87); no budget-write result can be
inferred. Preparation resources were cleaned, leaving only filesystem system
metadata. The image remains attached and is preserved for diagnosis.

Read-only path controls found normal CreateProcess accepts both GUID and DOS
cwd. LPAC rejected GUID executable paths with WinError 87; using the measured
DOS executable alias created the process but exited with STATUS_DLL_NOT_FOUND
(-1073741515). This isolates a further launch/loader boundary; the exact loader
cause and safe alias/traversal policy remain NOT_DEMONSTRATED. No ordinary-volume
fallback or ACL relaxation was added to make tests pass. Native activation,
quota exhaustion, sparse/compression and successful approved promotion remain
blocked. The previous absent-VHD statements and skips are historical, not the
current preparation state.

## Cierre de fallos reales LPAC/VHD — 2026-10-14

**CURRENT, alcance de esta batería:** 13/13 controles VHD reales PASS,
225.68 s, exit 0 (`windows-vhd-real-acceptance-final-20261014.txt`).
Incluyen escritura 513 MiB, muchos archivos, temp/truncate, sparse/compresión,
protección de imagen/raíz/perfil/metadata, aislamiento entre SIDs, denegación
del dispositivo y aprobación exacta con promoción Unicode. Sparse y compresión
se rechazaron al pedir su control NTFS (`control-denied`); esto demuestra esos
intentos concretos, no toda forma imaginable de asignación lógica.

Dos fronteras causaban los fallos de arranque. El ejecutable GUID LPAC necesita
un alias DOS obtenido de un handle fijado y la imagen del hijo se verifica
suspendida antes de ResumeThread. El montaje previo imponía secure-open por
imagen (características 0x20120). DiskPart ordinario tampoco lo eliminó en este
host. AttachVirtualDisk con PERMANENT_LIFETIME|NO_SECURITY_DESCRIPTOR dejó
0x20020, manteniendo identidad y ACL privada usuario/SYSTEM. No se concedió
acceso de datos al dispositivo. Las pruebas temporales de ACL restauraron sus
DACL originales; el readback final consta en windows-vhd-attachment-verified.

La promoción fallaba después de ejecutar correctamente porque VerifiedFS
mezclaba namespace GUID, DOS y prefijo extendido. Se mantiene el recorrido
lexical, se compara con la clave canónica del handle y se rechaza raíz
redirigida o ascendencia reparse. Regresiones observadas rojas antes de corregir:
namespace lexical y retarget de raíz. El control exacto aprobado terminó con
exit 0, promoted_count=1 y promotion.state=committed; sin aprobación fue DENY.

Verificación adicional: 65 PASS / 10 SKIP en 123.85 s para proceso, aliases,
operador, proveedor/API/CLI y ledger; 12/12 owner Windows PASS en 100.96 s.
Los skips pertenecen a controles no disponibles o POSIX; no se cuentan como
aceptación. Tras agregar controles de parser y equivalencia de prefijos,
11/11 controles de operador/aliases PASS. Los logs se preservan con SHA-256.
La revisión independiente rechazó una primera variante que omitía la raíz del
recorrido; se corrigió y añadió el negativo de retarget antes de cerrar.
También se comprobó UUID en cada paso de preparación antes de mutar un disco.

**NOT_DEMONSTRATED en esta continuación:** nuevo ciclo de creación/formato con
el preparador revisado, reboot real, recuperación schema2 tras muerte abrupta
sobre VHD, aceptación completa de Internet/IPv6/IPC y runtimes adicionales,
y regresión Linux actual. No se repitió la matriz nativa completa histórica.
NATIVE_ACCEPTED=False permanece; estos resultados cierran los 13 fallos de esta
batería, no certifican toda la paridad de producto ni una puerta de release.
No push, publicación o PR. La imagen y configuración privada se preservan.

Fuentes primarias para el diagnóstico:
[AttachVirtualDisk flags](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/ne-virtdisk-attach_virtual_disk_flag),
[seguridad de dispositivos](https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/applying-security-descriptors-on-the-device-object).

## Cross-platform regression closure — 2026-10-15

The current Windows UI and workspace interaction selection passes **39/39**
in 89.18 seconds (`evidence/windows-ui-parity-closure-final-20261015.txt`). It
covers cross-conversation messaging, model filtering/reasoning, sibling-folder
read and approved edit, automatic-edit confirmation, exact text copying,
keyboard-scrollable onboarding at 80x24, Settings reachability and startup.
The separate native-parity failure selection passes **37 tests with 3 explicit
platform skips** in 33.87 seconds (`evidence/windows-full-suite-failure-regressions-r2-20261015.txt`).

The corresponding Linux current-source adapter selection passes **139 tests
with 9 skips** in 142.48 seconds in a disposable Python 3.11 container, running
as an unprivileged `parity` user (`evidence/linux-native-adapters-closure-final-20261015.txt`).
The M15 authority snapshot was regenerated with current source-line locations;
its direct consistency test passes (`evidence/windows-m15-snapshot-current-20261015.txt`).
The previous snapshot bytes are preserved in
`evidence/m15-before-ui-closure-20261015.json`.

These are overlapping regression selections, not a release gate. The fresh
Windows non-integration suite ran from the D: checkout and passed **1827 tests**
with **323 skips, 11 deselected integration tests, and 1 expected failure** in
1838.80 seconds. Its command used `py -m pytest -p no:cacheprovider
--basetemp D:\Development\ISyCo\windows-parity\runs\20261015\full-suite-d-nonintegration-r2\basetemp
-m "not integration" -q`. Raw output is preserved in
`evidence/windows-full-suite-d-nonintegration-r2-20261015.txt` (SHA-256
`bb16b49a948fe63f64c8de07028e490b79268a91756149699149fa92eeab8f5b`). A broader
all-marker diagnostic is preserved in
`evidence/windows-full-suite-d-all-markers-r1-20261015.txt` (SHA-256
`15ff2dd2f9844c271040b2c1b03ede2142ae1b7391e1dd3cd9d57c7859da8fe6`); its five
failures were confined to integration tests whose host checkout/state
assumptions were not configured for the D: copy. Two follow-up root-discovery
probes then ran `test_bridge.py`
against the shared Bridge and appended test records **2991–3010** (temporary
HELLO/HEARTBEAT identities and two lease/PROGRESS/RELEASE cycles). I verified
that no `isycode-m3-*` lease remains active; the append-only history was not
rewritten, and the event was disclosed on the Bridge at seq 3117. The raw probe
logs are preserved in `evidence/windows-d-root-discovery-r1-20261015.txt`
(SHA-256 `fa6ff7c842785dd1a003592b3a3bc5366a8e6b4b016968273b08d272ae11329c`)
and `evidence/windows-d-root-discovery-r2-20261015.txt` (SHA-256
`11e495ffc760c40a0e0bf43c8cf3ea3b4c3051bc8026b187104cb611191a29d8`). Native
The broker integration tests no longer assume `Path.home()/Development/ISyCo`;
they use the explicitly configured `ISYCO_ROOT`, and isolate both POSIX and
Windows state roots. Their initial targeted run had 2 passes and one fixture
failure because it set only `XDG_STATE_HOME`; the corrected run passes 3/3.
The Bridge integration selection used a temporary D: root containing only a
copy of the handshake script, so its records never touched the shared Bridge.
The full integration-marked selection then passed **5 tests**, skipped **6**,
and deselected 2151 in 9.41 seconds. The six skips are five opt-in live Gateway
tests and the Bubblewrap command test, whose Linux prerequisite is unavailable
on Windows. Raw logs:

- `evidence/windows-broker-configured-checkout-r1-20261015.txt` (2 passed, 1
  failed; SHA-256 `e5eda3b347afc92af5635d6a05860c7486ce2c88eb250a5a368b883d9834c582`)
- `evidence/windows-broker-configured-checkout-r2-20261015.txt` (3 passed;
  SHA-256 `b6b2424099af79623904c89aa9d04fbb97e604b0a1f8ad4dd1409bc6c4fa8754`)
- `evidence/windows-bridge-isolated-integration-r1-20261015.txt` (2 passed;
  SHA-256 `3a08fa11cd0ecfd94ac9d8bb1486735ca10b8dcf510a899ffab2f6f11860e44f`)
- `evidence/windows-integration-d-isolated-root-r1-20261015.txt` (5 passed, 6
  skipped; SHA-256 `fbd2af8d64caff887218f373146c6e27c5e01f893f384b8b0879bb1beb0ddcd5`)
- The broker module's non-integration tests were rerun after giving the
  outside-`.isyroot` denial test a valid temporary recipe: **5 passed, 3
  deselected** in 0.57 seconds (`evidence/windows-broker-unit-r1-20261015.txt`,
  SHA-256 `31dad2206a0717b54da09469b3b4907e696007bb69ee31f6e1bfe84e8b2127a2`).

Together with the complementary non-integration run above, the collected suite
was covered in two safe selections: **1832 passed, 329 skipped, 1 expected
failure**. The five live Gateway tests remained opt-in and were not run.

Native sandbox activation remains disabled while lifecycle and broader host
acceptance remain open. The retained standalone 513 MiB xfail uses
`WindowsSandboxResources.prepare` without a storage lease, so it demonstrates
that ordinary NTFS scratch has no quota; it is not the product launch path.
`WindowsSandbox.start` rejects a missing approved storage identity and opens the
configured bounded-storage provider before preparing or launching a process.
The 13/13 real-VHD controls demonstrate refusal at the fixed volume's aggregate
capacity, not a per-file quota on arbitrary host paths. At this point in the
chronology, reboot/remount, abrupt-owner recovery on the VHD, and broader
Internet/IPv6/IPC/runtime acceptance were still open; the later continuation
below closes only the specific controls it names. `NATIVE_ACCEPTED=False`, so
complete Windows product parity remains **NOT_DEMONSTRATED**.

## Current VHD lifecycle and host-boundary evidence — 2026-10-15

The existing private fixed VHD was exercised again from the current checkout.
The real-volume acceptance selection passes **13/13** in 227.87 seconds, exit
0, in `evidence/windows-vhd-real-acceptance-continuation-r1-20261015.txt`
(SHA-256 `EF4ACEDB0D020F4143FCADE543504697E03CD6E9104824F418D0923C4A748647`).
It re-demonstrates aggregate-capacity refusal at 535752704 usable filesystem
bytes, refusal of the tested NTFS sparse/compression controls, external and
cross-SID isolation, and exact-approval Unicode promotion. The VHD remains
private and is not a product default.

The real lifecycle selection passes **11**, skips **2**, exit 0, in 145.61
seconds, in `evidence/windows-vhd-lifecycle-continuation-r2-20261015.txt`
(SHA-256 `ADC5EA6CF8C10BEBD06CA12B8C2AD6D99C03B5E001F3DDC23A92A6FB38894BEA`).
Schema2 recovery passed after abrupt owner death during copying, immediately
after profile creation, and while an LPAC process was running. The process was
confirmed terminated before the owned scratch was removed. Host IPv4/IPv6
TCP/UDP socket creation and a host-seeded named pipe were denied inside LPAC.
A host WinHTTP HTTPS HEAD request completed; the same request inside LPAC was
denied with error 10013. Both preparation cancellation and owner cancellation
cleaned the scratch and did not promote the staged file. The two skips in this
non-operator run were then executed separately with a private coordination
directory and an elevated helper that verifies and restores the exact test
image. Both passed: `evidence/windows-vhd-disappearance-lease-final-20261015.txt`
(1 passed, SHA-256
`3FE251A407B16434F69FB7A3DB614670C22F3C84B322E16B632C7DB37EABA50A`) and
`evidence/windows-vhd-disappearance-running-final-20261015.txt` (1 passed,
SHA-256 `ED02DE06C30051378285AE4A85F87F18A89A66EE65F561AC9A2A407BD5486F19`).
The first detached the image while a lease was held, then proved start refused
without fallback and the exact image identity reopened. The second detached it
while a command was executing, proved no promotion and original-file
preservation, then reattached the image and recovered its scratch. Across the
regular and operator-coordinated selections, all **13 lifecycle controls** are
demonstrated; the two skips above are superseded by those targeted passes.

The first lifecycle run is retained as diagnostic evidence:
`evidence/windows-vhd-lifecycle-continuation-r1-20261015.txt` (SHA-256
`E03A087D87A54D017FF8DA0572130CD62CC8C8351409E95FF420B210958D0958`). All
three abrupt-death subprocesses failed before reaching the product code because
the test harness did not pass the checkout's `src` path to its child Python.
The harness now supplies that path through `PYTHONPATH`; the corrected full
selection above passes. No Windows sandbox product source changed in this
continuation.

## Real Windows reboot and exact VHD remount — 2026-10-15

The host completed an actual Windows reboot. The post-boot probe found the
registered image detached, verified the same fixed VHD by its registered image
and backing-file identities, reattached it with the standard device policy,
and passed volume inspection plus a bounded-storage reopen. The pre-boot and
post-boot identity digests match; no owned scratch remained. The one-shot
startup runner's first attempt could not load the registered private storage
configuration, and that failure is retained in
`evidence/windows-vhd-reboot-acceptance-20261015.txt`. A later elevated
acceptance attempt did remount and inspect the image but its pytest run hit the
private-state ACL check (`1 failed, 12 errors`); that diagnostic is retained in
`evidence/windows-vhd-reboot-acceptance-r2-20261015.txt` and the raw log remains
under the protected D: run directory.

The same real-VHD acceptance selection then passed **13/13** in **242.69 s**,
exit 0, under the ordinary non-elevated user token after the remount. Its
protected raw-log SHA-256 is
`87444d17d92db4b190aabe3a50754bf9436d84b1755bad78baea5a94be3f8b67`. The
consolidated sanitized result is
`evidence/windows-vhd-reboot-acceptance-final-20261015.txt`. The failures above
remain visible as diagnostic history; they do not replace this passing run.
This proves the tested VHD lifecycle across a real reboot, not automatic
product startup mounting or complete Windows/Linux parity.

**Still NOT_DEMONSTRATED:** remaining IPC/device classes; a usable AF_UNIX
endpoint on a Windows host; host access to a pipe created by LPAC; runtimes
besides CPython and project dependency staging; access from a second Windows
identity; standalone EXE install/uninstall and self-update; a live proxied Git
update query; hardware power-loss recovery; and full physical Linux/Windows
interactive parity. Wheel install/uninstall is separately demonstrated below.
These controls do not enable native sandbox execution:
`NATIVE_ACCEPTED=False` remains, and complete Windows product parity remains
NOT_DEMONSTRATED.

## Windows standalone updater environment — 2026-10-15

`SelfUpdater._env()` now retains its fixed, isolated Git environment while
forwarding only case-insensitive standard proxy and trusted-CA overrides:
`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`,
`SSL_CERT_DIR`, `CURL_CA_BUNDLE`, and `GIT_SSL_CAINFO`. It does not inherit
arbitrary application credentials, Python path settings, user Git config
injection, or `GIT_SSL_NO_VERIFY`. The regression uses synthetic
`.example.invalid` values, verifies that those approved keys survive Windows
environment-name normalization, and confirms unrelated/security-disabling
variables remain absent.

`py -m pytest tests/test_updater.py -q` passes **36 tests with 1 skip** in
172.04 seconds. The skip is the POSIX-only pip-launcher assertion. The captured
raw output is `evidence/windows-updater-proxy-tests-r3-20261015.txt` (SHA-256
`EABDADD3D24B775C152AC4682332348B96C2794D44767B4590BF05270AD93ABD`). Two
interrupted capture attempts are preserved as diagnostics, not accepted runs.
A clean PyInstaller 6.22.3 one-file build using the CI packaging arguments
completed with exit 0. The isolated profile was under a path with spaces and
Unicode. `--version`,
`--help`, `doctor --json`, `dirs --json`, and
`models --json` all exited 0. The build and isolated command outputs are
summarized in `evidence/windows-updater-proxy-20261015.txt`; exact hashes are
listed in `hashes.json`.

`update --check` exited 1 with the generic repository-query error. This host
has no standard proxy environment keys, no user/machine proxy environment
keys, no WinINET proxy or auto-config, and WinHTTP reports direct access. The
new regression therefore proves environment filtering, but a live query
through a real proxy/TLS setup remains **NOT_DEMONSTRATED**. The mutating
`update` command was not run from the frozen EXE: the existing source updater
bootstraps a source checkout when no checkout is discoverable; it does not
replace the packaged executable. Standalone EXE install/uninstall and upgrade
still need a supported flow and separate acceptance.

## IPC, runtime allowlist, and wheel install/uninstall — 2026-10-15

The complete real-VHD lifecycle module was rerun after adding IPC probes:
**12 passed, 3 skipped** in 178.97 seconds, exit 0. The two operator-controlled
volume-disappearance cases remain separately demonstrated by the earlier
coordinated runs. The third skip is the AF_UNIX control: Windows CPython can
create a family-1 socket, but the host bind fails with `bad family` before
listen/connect can be tested; its `socketpair` fallback supports only
AF_INET/AF_INET6. LPAC created the same socket object, but bind produced the
same unavailable-family error. Since
there was no positive endpoint control, AF_UNIX remains **NOT_DEMONSTRATED**;
this is not reported as an access-denied result.

The new named-pipe control passed: `CreateNamedPipeW` returned
`ERROR_ACCESS_DENIED` (5) from LPAC. This demonstrates that LPAC could not create
the server-side pipe under the tested policy. The host-open direction therefore
remains **NOT_DEMONSTRATED**; the earlier host-created pipe control separately
proved that LPAC could not open that pipe. Raw VHD output SHA-256 is
`F25F3139632EDF5D16252DA09FD60C4C3637B336666714C4DBBA5559F9A124C3`; the
sanitized results and limits are in
`evidence/windows-ipc-runtime-extension-20261015.txt`.
A read-only post-run check reopened the same registered volume, confirmed its
identity unchanged, and found zero owned scratch directories; see
`evidence/windows-vhd-post-lifecycle-20261015.txt`.

The runtime allowlist regression passed **6/6**. The host has CPython, Node, and
Bun, but the native command backend resolves only its explicit CPython runtime;
it rejects `cmd.exe`, Node, Bun, and the installed absolute Node/Bun paths. This
confirms fail-closed selection, not support for those runtimes or staging of
project dependencies. Evidence hashes are in `hashes.json` for
`evidence/windows-runtime-allowlist-20261015.txt` and
`evidence/windows-runtime-inventory-20261015.txt`.

A wheel built from a private copy of the current `pyproject.toml` and `src/`
installed and uninstalled successfully in a fresh D: venv whose path includes
spaces and Unicode. The Windows `isycode.exe --version` and `--help` launchers
passed; `pip uninstall` removed both the launcher and distribution. This check
used `--no-deps` with system dependencies visible, so it does not prove a clean
dependency download, the source installer's uninstaller, or a standalone EXE
install/update flow. The result is recorded in
`evidence/windows-wheel-install-uninstall-20261015.txt`.

The sandbox remains disabled: `NATIVE_ACCEPTED=False`. Secondary-user ACL
acceptance, other IPC/device classes, dependency staging, a live proxied update,
hardware power-loss recovery, standalone EXE update/install, and physical
Linux/Windows interactive parity are still **NOT_DEMONSTRATED**.

## Final identity and clipboard controls — 2026-10-15

`py -m pytest -q tests/test_windows_clipboard.py tests/test_windows_private_identity.py`
passes **6 tests** with **1 skip**, exit 0. The UTF-16 clipboard regression
strips a leading BOM before returning UTF-8 text; the anonymous-token test also
confirms that a distinct Windows security principal cannot read the seeded
private metadata files. The raw output is
`evidence/windows-identity-clipboard-final-20261015.txt` (SHA-256
`454A8E50CA96341EE6D21851A7BAF6F0E93A71AFC467AC971F5A9BA7C5521F41`).

The skipped clipboard roundtrip requires an administrator-created private
window station. This host is not elevated, so that native roundtrip was not
rerun after the BOM fix. A prior isolated-station run is retained separately;
the current BOM behavior is demonstrated by the deterministic Win32 memory
control. The five-user acceptance matrix remains waived as requested; a
separately logged-on second-user witness remains NOT_DEMONSTRATED.

The PR adds a Windows 3.12 job that runs the same full non-integration pytest
selection as Linux and gates package builds on it. Local Windows had already
passed the full suite (1,827 passed, 323 skipped, 11 integration tests
deselected, 1 expected failure). The new GitHub-hosted Windows run is pending
until the PR workflow executes; it is not represented as a completed result.
The 7,309,128-byte Linux collection log is retained locally in raw form and committed here as a lossless gzip stream at `evidence/linux-collection.log.gz`. Decompression was verified byte-for-byte; the original SHA-256 is `15e8cf3d313466921af807f358bf1769222c2db2136a4ef4264b715931976440` and the compressed SHA-256 is `39eb2f59dfafb367410e7f77a8885c9926f16f165df7fdff867363ea6f53536e` (also recorded in `hashes.json`).

The 4,200,909-byte raw log `windows-clipboard-regressions-20261014.txt` remains local and is committed losslessly as `windows-clipboard-regressions-20261014.txt.gz`. Decompression matches the original byte-for-byte (original SHA-256 `1281df6bf6cfc783f79ab305f91512e3529a6f9c0590a52fc11f4081570f30fd`, gzip SHA-256 `440432b9fb6d26b8fab0c989816f0d71124edbb6b9d79638f46795020efcbb25`).

The 1,018,307-byte raw log `windows-full-suite-final-closure-20261015.txt` remains local and is committed losslessly as `windows-full-suite-final-closure-20261015.txt.gz`. Decompression matches the original byte-for-byte (original SHA-256 `1e7adba1d61420c80d6a5dd22296c1d48d02936cb9a6213ba7c215fdd7cd20ea`, gzip SHA-256 `f562cba7719b5380033a9c131421750b56dfe1ff3e63f93d3ef954d2c37d7408`).
