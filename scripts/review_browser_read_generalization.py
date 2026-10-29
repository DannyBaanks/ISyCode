"""M3 category matrix and exact browser-preview interaction probe.

Requires optional Playwright + Chromium. Live accessibility snapshots stay in
memory and the emitted JSON contains no source or filtered page text.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from playwright.sync_api import sync_playwright
from textual.app import App

from isycode.browser_read import filter_accessibility_snapshot
from isycode.browser_read_benchmark import benchmark_filter_modes
from isycode.tui_screens_approval import BrowserReadPreviewScreen


PAGES = (
    ("python-api-docs", "https://docs.python.org/3/library/asyncio.html", ("asyncio", "create_task")),
    ("github-readme", "https://raw.githubusercontent.com/python/cpython/main/README.rst", ("python", "cpython")),
    ("news", "https://www.bbc.com/news", ("news", "world")),
    ("wikipedia", "https://en.wikipedia.org/wiki/Artificial_intelligence", ("artificial intelligence", "machine learning")),
    ("product", "https://www.nvidia.com/en-us/geforce/graphics-cards/", ("geforce", "graphics")),
)

FIXTURES = (
    (
        "python-api-docs",
        '''- navigation:\n  - link "Library index":\n- main:\n  - heading "asyncio TaskGroup" [level=1]\n  - paragraph: Task groups provide structured concurrency.\n  - code: async with asyncio.TaskGroup() as group:\n  - paragraph: Use create_task to schedule a coroutine.\n  - button "Copy code":\n    - text: Copy code\n''',
        ("asyncio TaskGroup", "structured concurrency", "create_task"),
    ),
    (
        "github-readme",
        '''- banner:\n  - link "Sign in":\n- navigation:\n  - link "Repository navigation":\n- main:\n  - heading "CPython" [level=1]\n  - paragraph: The Python programming language implementation.\n  - code: ./configure && make\n  - button "Fork repository":\n    - text: Fork\n''',
        ("CPython", "Python programming language", "./configure && make"),
    ),
    (
        "news",
        '''- banner:\n  - link "Watch live":\n- main:\n  - heading "Cities prepare for heavy rain" [level=1]\n  - generic: By A. Reporter · 09 October 2026\n  - paragraph: Emergency teams opened shelters before the storm.\n  - paragraph: Officials expect the strongest rainfall overnight.\n  - button "Subscribe to updates":\n''',
        ("Cities prepare for heavy rain", "A. Reporter", "opened shelters", "rainfall overnight"),
    ),
    (
        "wikipedia",
        '''- navigation:\n  - link "Contents":\n- main:\n  - heading "Artificial intelligence" [level=1]\n  - paragraph: Artificial intelligence studies systems that perform tasks associated with intelligence.\n  - heading "History" [level=2]\n  - paragraph: Early work explored symbolic reasoning and learning.\n  - listitem: [1] Reference entry\n''',
        ("Artificial intelligence", "systems that perform tasks", "History", "symbolic reasoning"),
    ),
    (
        "product-page",
        '''- banner:\n  - navigation:\n    - link "Products":\n- main:\n  - heading "GeForce RTX 5090" [level=1]\n  - paragraph: Price: $1,999. Availability: In stock.\n  - paragraph: 32 GB GDDR7 memory and 21,760 CUDA cores.\n  - button "Add to cart":\n    - text: Add to cart\n''',
        ("GeForce RTX 5090", "$1,999", "In stock", "32 GB GDDR7", "CUDA cores"),
    ),
    (
        "adversarial-sidebar",
        '''- generic:\n  - complementary:\n    - heading "API reference" [level=2]\n    - paragraph: Retry-After accepts seconds or an HTTP date.\n    - code: 429 responses include a Retry-After header.\n  - main:\n    - button "Subscribe to alerts":\n    - generic "Jump to content":\n      - paragraph: Promotional content must not replace the sidebar API details.\n    - paragraph: Version 2.4 adds streaming responses.\n''',
        ("API reference", "Retry-After", "429 responses", "Version 2.4"),
    ),
)


class _PreviewHost(App):
    def __init__(self, title: str, content: str, input_chars: int, processing_ms: float):
        super().__init__()
        self.title = title
        self.content = content
        self.input_chars = input_chars
        self.processing_ms = processing_ms
        self.decision: bool | None = None

    def on_mount(self) -> None:
        screen = BrowserReadPreviewScreen(
            self.title,
            self.content,
            self.input_chars,
            len(self.content),
            False,
            self.processing_ms,
        )
        self.push_screen(screen, self._record)

    def _record(self, decision: bool) -> None:
        self.decision = decision


async def _exercise_preview(title: str, content: str, input_chars: int, processing_ms: float) -> dict:
    interactions = {}
    for action, button_id, expected in (
        ("discard", "#browser-read-discard", False),
        ("share", "#browser-read-share", True),
    ):
        host = _PreviewHost(title, content, input_chars, processing_ms)
        async with host.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            visible = pilot.app.screen.query_one("#browser-read-content Static").render()
            visible_text = visible.plain if hasattr(visible, "plain") else str(visible)
            if visible_text != content:
                raise AssertionError("browser preview differs from the reviewed text")
            await pilot.click(button_id)
            await pilot.pause()
        if host.decision is not expected:
            raise AssertionError("browser preview action returned an unexpected decision")
        interactions[action] = host.decision
    return {
        "displayed_exactly": True,
        "discard_returns_false": interactions["discard"] is False,
        "share_returns_true": interactions["share"] is True,
    }


def _measure(name: str, snapshot: str, canaries: tuple[str, ...]) -> dict:
    return {
        "name": name,
        "input_sha256": hashlib.sha256(snapshot.encode()).hexdigest(),
        "strategies": benchmark_filter_modes(
            snapshot,
            workers=(2, 4),
            repetitions=3,
            pool_lifecycle="reused",
            canaries=canaries,
        ),
    }


def main() -> None:
    report: dict = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "fixtures": [_measure(name, snapshot, canaries) for name, snapshot, canaries in FIXTURES],
        "pages": [],
    }
    preview_inputs: dict[str, tuple[str, str, int, float]] = {}
    captures: list[tuple[str, str, tuple[str, ...], int | None, str | None]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for name, url, canaries in PAGES:
                page = browser.new_page()
                try:
                    response = page.goto(url, wait_until="commit", timeout=60_000)
                    status = response.status if response else None
                    page.wait_for_timeout(2_000)
                    snapshot = page.locator("body").aria_snapshot()
                    captures.append((name, url, canaries, status, snapshot))
                except Exception as exc:
                    captures.append((name, url, canaries, None, None))
                    report["pages"].append({"name": name, "url": url, "error": type(exc).__name__})
                finally:
                    page.close()
        finally:
            browser.close()
    # Capture all pages before CPU-heavy worker comparisons, so pool startup
    # cannot starve the browser or turn later live captures into timeouts.
    for name, url, canaries, status, snapshot in captures:
        if snapshot is None:
            continue
        filtered = filter_accessibility_snapshot(snapshot)
        preview_inputs[name] = (
            name,
            filtered["content"],
            filtered["input_chars"],
            filtered["processing_ms"],
        )
        report["pages"].append(
            {
                "name": name,
                "url": url,
                "http": status,
                "snapshot_sha256": hashlib.sha256(snapshot.encode()).hexdigest(),
                "input_chars": len(snapshot),
                "source_canaries": {
                    canary: canary.casefold() in snapshot.casefold()
                    for canary in canaries
                },
                "serial_canaries": {
                    canary: canary.casefold() in filtered["content"].casefold()
                    for canary in canaries
                },
                "quality_status": filtered["quality_status"],
                "truncated": filtered["truncated"],
                "untrusted": filtered["untrusted"],
                "fidelity_assessed": filtered["fidelity_assessed"],
                **_measure(name, snapshot, canaries),
            }
        )
    # Textual's async test loop runs after leaving Playwright's sync greenlet.
    for page_result in report["pages"]:
        values = preview_inputs.get(page_result["name"])
        if values is not None:
            page_result["preview"] = asyncio.run(_exercise_preview(*values))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
