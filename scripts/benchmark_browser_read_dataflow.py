"""Run M2 worker comparisons; only metric dictionaries are printed or saved.

Run from the repository root with `python3 scripts/benchmark_browser_read_dataflow.py`.
Requires the optional `playwright` Python package and an installed Chromium.
Page snapshots stay in memory; this script emits URL/status, hashes, timings,
canaries, and memory metrics, never page or filtered text.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from playwright.sync_api import sync_playwright

from isycode.browser_read_benchmark import benchmark_filter_modes


PAGES = (
    ("python-docs", "https://docs.python.org/3/library/asyncio.html", ("asyncio", "create_task")),
    ("github-readme", "https://raw.githubusercontent.com/python/cpython/main/README.rst", ("python", "cpython")),
    ("news", "https://www.bbc.com/news", ("news", "world")),
    ("wikipedia", "https://en.wikipedia.org/wiki/Artificial_intelligence", ("artificial intelligence", "machine learning")),
    ("product", "https://www.nvidia.com/en-us/geforce/graphics-cards/", ("geforce", "graphics")),
)
FIXTURES = (
    ("small", "- main:\n  - paragraph: small-page text\n", ("small-page text",)),
    (
        "large",
        "- main:\n" + "".join(f"  - paragraph: item {i:05d} needle\n" for i in range(6000)),
        ("item 00000", "item 05999"),
    ),
    (
        "malformed",
        'garbage\n- heading "Valid heading" [level=1]\n??\n- paragraph: Valid body\n',
        ("Valid heading", "Valid body"),
    ),
    (
        "adversarial",
        '- generic:\n  - complementary:\n    - heading "API reference" [level=2]\n'
        '    - paragraph: Retry-After accepts seconds.\n  - main:\n'
        '    - heading "Release notes" [level=1]\n    - button "Subscribe to updates":\n'
        '    - paragraph: Useful main text.\n',
        ("API reference", "Retry-After", "Useful main text"),
    ),
)


def compare(name: str, snapshot: str, canaries: tuple[str, ...]) -> dict:
    return {
        "name": name,
        "cold": benchmark_filter_modes(
            snapshot, workers=(1, 2, 4), repetitions=5, pool_lifecycle="cold", canaries=canaries
        ),
        "reused": benchmark_filter_modes(
            snapshot, workers=(1, 2, 4), repetitions=5, pool_lifecycle="reused", canaries=canaries
        ),
    }


def main() -> None:
    report = {"fixtures": [compare(*fixture) for fixture in FIXTURES], "pages": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for name, url, canaries in PAGES:
            page = browser.new_page()
            status = None
            try:
                response = page.goto(url, wait_until="commit", timeout=30_000)
                status = response.status if response else None
                page.wait_for_timeout(2_000)
                snapshot = page.locator("body").aria_snapshot()
                report["pages"].append({"http": status, **compare(name, snapshot, canaries)})
            except Exception as exc:
                report["pages"].append({"name": name, "http": status, "error": type(exc).__name__})
            finally:
                page.close()
        browser.close()
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
