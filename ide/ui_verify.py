"""Headless UX verification: exercise TUI interactions at several sizes,
capture SVG screenshots, and verify layout content."""
import asyncio
import html
import re
import sys
import tempfile
from pathlib import Path

from textual.widgets import Input

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent.chat import IsycoAgentApp


def text_of(svg: str) -> str:
    texts = re.findall(r"<text[^>]*>(.*?)</text>", svg, flags=re.S)
    joined = "\n".join(texts)
    return html.unescape(joined).replace("\xa0", " ").replace("\n", "")


async def verify_size(size: tuple[int, int], out: Path, work: Path):
    app = IsycoAgentApp(working_dir=str(work))
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        app.todo_store.add("implement resident scan")
        app.todo_store.add("add provider")
        app.refresh_todo_summary()
        await pilot.pause()

        checks = []

        svg = app.export_screenshot()
        (out / f"ui_{size[0]}x{size[1]}_start.svg").write_text(svg, encoding="utf-8")
        content = text_of(svg)

        checks.append(("welcome present", "ISYCODE" in content))
        checks.append(("mode badge", "[PLAN]" in content))
        checks.append(("status provider", "openai" in content))
        checks.append(("status model", "gpt-4o" in content))
        checks.append(("runtime layer", "layer_a" in content))

        wide = size[0] >= 100
        checks.append(("sidebar visible", "RESIDENT" in content and "last scan" in content and "workspace:" in content) if wide else
                      ("sidebar hidden at narrow width", "last scan" not in content))
        if wide:
            checks.append(("todo item 1", "implement resident scan" in content))
            checks.append(("todo item 2", "add provider" in content))

        bar_visible = size[0] >= 64
        if bar_visible:
            checks.append(("options button", "OPTIONS" in content))
            checks.append(("todo button", "TODO" in content))
        else:
            checks.append(("action bar hidden at narrow width", "OPTIONS" not in content))

        # toggle mode
        await pilot.press("shift+tab")
        checks.append(("shift+tab -> coder", app.mode == "coder"))
        await pilot.press("shift+tab")
        checks.append(("shift+tab -> plan", app.mode == "plan"))

        # options modal via ctrl+o
        await pilot.press("ctrl+o")
        await pilot.pause()
        checks.append(("ctrl+o opens options", app.screen.__class__.__name__ == "OptionsModal"))
        await pilot.click("#option-close")
        await pilot.pause()

        # todo modal via ctrl+t
        await pilot.press("ctrl+t")
        await pilot.pause()
        checks.append(("ctrl+t opens todo", app.screen.__class__.__name__ == "TodoModal"))
        app.screen.query_one("#todo-input", Input).value = "review resident UI"
        await pilot.click("#todo-add")
        await pilot.pause()
        await pilot.click("#todo-close")
        await pilot.pause()
        checks.append(("todo added", "review resident UI" in app.todo_store.summary()))

        # toggle sidebar via ctrl+s
        await pilot.press("ctrl+s")
        await pilot.pause()
        svg2 = app.export_screenshot()
        (out / f"ui_{size[0]}x{size[1]}_sidebar_off.svg").write_text(svg2, encoding="utf-8")
        content2 = text_of(svg2)
        checks.append(("ctrl+s hides sidebar", "last scan" not in content2))
        await pilot.press("ctrl+s")
        await pilot.pause()

        # typing + submit in multiline input
        app.input_area.focus()
        await pilot.pause()
        for char in "hello agent":
            await pilot.press("space" if char == " " else char)
        await pilot.press("enter")
        await pilot.pause()
        content3 = text_of(app.export_screenshot())
        checks.append(("user message rendered", "hello agent" in content3))
        checks.append(("input cleared after send", app.input_area.text == ""))

        failed = [name for name, ok in checks if not ok]
        print(f"[{size[0]}x{size[1]}] {'OK' if not failed else 'FAIL'}: {len(checks) - len(failed)}/{len(checks)} checks")
        for name, ok in checks:
            if not ok:
                print(f"    MISSING: {name}")
        return failed


async def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "ui_verify_out")
    out.mkdir(parents=True, exist_ok=True)
    all_failed = []
    for size in ((140, 32), (108, 30), (80, 24), (60, 22)):
        with tempfile.TemporaryDirectory(prefix="isycode_ui_") as tmp:
            all_failed += await verify_size(size, out, Path(tmp))
    if all_failed:
        print("FAILED:", all_failed)
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    asyncio.run(main())