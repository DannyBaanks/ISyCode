# Preserved negative test result

Transcript excerpt from the first icon-only test run (not an original raw log):

```text
FAILED tests/test_file_icons.py::test_tui_proposal_uses_literal_ascii - textual._context.NoActiveAppError
1 failed, 29 passed in 5.34s
```

The test attempted to compose a Textual modal outside an active App. The test
was corrected to use App.run_test; production modal composition did not change
for this harness repair. Later full-suite raw logs are preserved separately.
The excerpt's artifact hash proves preservation of this note, not identity
with an original raw log, which is NOT_DEMONSTRATED.
