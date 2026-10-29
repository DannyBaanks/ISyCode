# Bounded storage independent review — 2026-10-14

Reviewer: `/root/bounded_storage_final_review`, fresh context, read-only. Scope:
the new provider/configuration and uncommitted backend/resources/recovery
integration after `04ef1bb`; no native profiles or disk preparation by reviewer.

- P1: ordinary backing-file and VirtDisk opens could identify different images
  during an ancestor substitution. Resolved: pin each ancestor with handles
  that do not share DELETE, and correlate the dependency PhysicalDrive device
  with the device returned by VirtDisk. The deterministic mixed-device refresh
  control rejects the combination even when ordinary file IDs match.
- P2: an early Close failure could skip later handle/fd releases. Resolved with
  common best-effort release of every resource; error paths retain their
  original exception and append cleanup diagnostics. A failing first handle
  control verifies that the remaining handle and ordinary fd are closed.
- P1 acceptance harness: an unexpected allowed write must not truncate the
  mounted backing image. Resolved by testing GENERIC_WRITE/OPEN_EXISTING handle
  acquisition and immediately closing any unexpectedly allowed handle, without
  write/truncate/create operations. Mounted backing contents are mutable NTFS
  data, so its stable witness is fixed image length plus lease identity rather
  than a whole-image content hash.

The follow-up reviewer confirmed P1 resolved and found no further important
backend/ownership findings; P2 was corrected after that follow-up. The final
targeted API regression covers both fixes. API fakes are not VHD evidence.
Real capacity, NTFS sparse/compression behavior and product activation remain
NOT_DEMONSTRATED; NATIVE_ACCEPTED remains False.

Final read-only follow-up confirmed the non-destructive acceptance controls
resolve the last finding. No important findings remain in this review. This
review neither executed the real-VHD tests nor certifies their future result.

API correlation follows Microsoft's documented PhysicalDrive device strings:
[dependency entry](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/ns-virtdisk-storage_dependency_info_type_2),
[VirtDisk physical path](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/nf-virtdisk-getvirtualdiskphysicalpath).
