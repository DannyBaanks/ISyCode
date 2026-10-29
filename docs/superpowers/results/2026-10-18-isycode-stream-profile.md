# ISyCode streaming render profile — 2026-10-18

Offline measurement for stability Task 7 (content and thinking render cost). No network traffic and no provider credentials are involved: the harness replaces `isycode.tui.provider_complete` with a synthetic provider inside `TUIApp.run_test()`.

## Environment and commands

- Host: Linux `DannyISyCo 7.0.0-38-generic`, Ubuntu 24.04 x86_64
- Python 3.12.3, pytest 9.1.1, Textual 8.2.8
- Harness: `scripts/profile_tui_streaming.py` (sha256 `95bc3edc6d675d36f65566f01aff5d4d7c65715c2e6ede575e53c08b8e6883c6`), defaults `--runs 5 --payload-chars 16384 --chunk-chars 16 128`
- Exact command: `python3 scripts/profile_tui_streaming.py`
- Local raw logs (gitignored evidence directory `.superpowers/sdd/2026-10-18-isycode-tui-stability/`):
  - pre-change baseline `task-7-profile-raw.json`, sha256 `15bb9ae26cbb53b70d55986599e9ac84e2f6e3852ffbddc835013737dcca8bc4`
  - post-change `task-7-profile-after.json`, sha256 `933f9c6d443b6f239a672e0427b7bcfac7991e202af060949152e1521b37c5b6`
  - independent re-run of the post-change tree `task-7-profile-verify.json`, sha256 `4baa0913502e337099b44a731f17aae53e603668552ef26ac24bc03cf7b985a7`

## Baseline and threshold decision

Medians over 5 samples per case, 16,384 payload characters:

| mode | chunk | wall median | CPU median | Markdown CPU | Markdown calls | thinking CPU / calls |
|---|---|---|---|---|---|---|
| content | 16 | 1.196 s | 1.155 s | 0.997 s (86.3% of CPU) | 1025 | 0 / 0 |
| content | 128 | 0.225 s | 0.179 s | 0.126 s (70.6% of CPU) | 129 | 0 / 0 |
| reasoning | 16 | 0.090 s | 0.059 s | 0 | 0 | 0.00075 s / 5 (1.3% of CPU) |
| reasoning | 128 | 0.099 s | 0.057 s | 0 | 0 | 0.00077 s / 5 (1.4% of CPU) |

The plan's materiality threshold (≥20% of measured CPU in repeated renderer work) is met by content Markdown construction; the thinking preview remains around 1.3% of CPU, so `ThoughtBlock` was left unchanged.

## Change (measured bottleneck only)

`src/isycode/tui_app_chat.py` (sha256 `e5514120868df3edf21cc5b793af9c48fbd6692144c73ccab782895fc7083367`; commit `fbdb849`): coalesce content repaints at `CONTENT_PAINT_INTERVAL_S = 1/30`, skip unchanged content, and force a final flush on successful finish, transport failure, cancellation, and lane switch. Full streamed source text, selectable content, `_history` records, transport, provider chunking, and the Idea Box are untouched. The lane-switch guard also stops writing into the detached widget and continues painting into the new lane widget.

Boundary tests (`tests/test_chat_sequence.py`, sha256 `0e5e34ed6da2d631cb6dd9641fd366a3ef8a15f2ae685d2b2f72aaeaf2402a7c`):

- burst of 96 chunks: Markdown constructions stay under half the chunk count (observed 3), and the full answer is byte-exact, selectable, and recorded exactly in `_history`;
- failure after automatic retries are exhausted, and cancellation: the latest partial text stays visible and selectable, history stays empty, and `_interrupted_turn.partial_text` preserves the final attempt without mixing discarded retries;
- lane switch: content keeps painting in the new lane widget and the reasoning block keeps its exact full text.

Exact command: `python3 -m pytest -q tests/test_chat_sequence.py tests/test_ux_polish_and_resume.py::test_area_f_interrupted_turn_capture_and_resume` → **15 passed in 16.72 s**.

## Result (same harness, same host)

| mode | chunk | wall median | CPU median | Markdown CPU | Markdown calls |
|---|---|---|---|---|---|
| content | 16 | 0.104 s | 0.056 s | 0.0026 s | 3 |
| content | 128 | 0.235 s | 0.059 s | 0.0030 s | 3 |
| reasoning | 16 | 0.109 s | 0.060 s | 0 | 0 |
| reasoning | 128 | 0.323 s | 0.077 s | 0 | 0 |

Delta on the targeted renderer: Markdown CPU −99.7% (16-char chunks) and −97.7% (128-char); total content CPU −95.1% and −67.2%. The independent re-run reproduces 3 Markdown constructions per sample in both chunk sizes (0.0026 s Markdown CPU). The ≥20% target is met.

## Limitations

- Synthetic payloads of 16,384 characters; live provider phrasing was not measured.
- `wall` includes Textual event-loop pacing and host load, so wall medians vary between runs; CPU medians are the criterion.
- Windows/macOS hosts were not measured; platform CI evidence remains outstanding (`NOT_DEMONSTRATED`) because this branch is not pushed to `origin`.
