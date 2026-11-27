"""Automated acceptance driver for the ISyCode desktop app.

Runs the REAL MainWindow + AgentWorker pipeline (the exact code shipped
in isycode.exe) offscreen, with a REAL provider from opencode's
auth.json, and executes the acceptance flow:

    open window -> select provider/model -> run multi-step task
    -> see tool calls -> see edits -> see diff -> run tests
    -> see evidence -> continue conversation

Evidence is dumped as JSON. Run:

    python -m ui.acceptance <workspace_dir> <out.json>

The workspace must contain a tests/ directory for the Tests panel.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.app import AppController  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

TASK_1 = (
    "Crea el archivo utils.py en la raiz con una funcion sum_range(a, b) "
    "que devuelva la suma de enteros de a a b inclusive (sum_range(1,3)==6, "
    "sum_range(0,0)==0). Luego crea tests/test_sum.py con dos funciones de "
    "prueba pytest que verifiquen esos dos casos importando utils. Escribe "
    "ambos archivos con la herramienta write. Cuando termines, responde "
    "brevemente que hiciste."
)

TASK_2 = (
    "Edita utils.py: agrega una funcion product_range(a, b) que devuelva el "
    "producto de enteros de a a b inclusive. Usa la herramienta edit. "
    "Luego responde brevemente que hiciste."
)

PROVIDER_CANDIDATES = [
    ("ollama", "isyco-coder:latest"),
    ("nvidia", "meta/llama-3.3-70b-instruct"),
    ("google", "gemini-2.0-flash"),
    ("google", "gemini-1.5-pro"),
    ("openai", "gpt-4o"),
]


def log(message: str) -> None:
    print(f"[acceptance] {message}", flush=True)


def pump_until(app: QApplication, condition, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.05)
    return False


async def probe(controller: AppController, name: str,
                provider_type: str, model: str) -> str | None:
    """Returns None on success, or the error string."""
    try:
        controller.add_provider(name, provider_type, model, timeout=120.0)
        provider = controller.provider_registry.get(name)
        response = await asyncio.wait_for(
            provider.complete([{"role": "user", "content": "ping"}]), 90)
        if response and response.content:
            return None
        return "empty response"
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def run_task(app: QApplication, window: MainWindow, prompt: str,
             timeout_s: int = 300) -> dict:
    before = {i: window.tools_panel.tree.topLevelItemCount() for i in range(2)}
    window._start_agent(prompt)
    ok = pump_until(app, lambda: not window._worker.isRunning(), timeout_s)
    tools = []
    tree = window.tools_panel.tree
    for i in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(i)
        tools.append({
            "tool": item.text(0),
            "status": item.text(1),
            "detail": item.text(2),
            "actor": item.text(3),
        })
    return {
        "completed": ok,
        "tool_calls": tools,
        "new_tool_rows": tree.topLevelItemCount() - before[0],
    }


def main() -> int:
    workspace = Path(sys.argv[1] if len(sys.argv) > 1 else Path.cwd()).resolve()
    out_path = Path(sys.argv[2] if len(sys.argv) > 2 else "acceptance_evidence.json")
    app = QApplication(sys.argv)

    evidence: dict = {"workspace": str(workspace), "provider": None, "steps": {}}

    # --- select provider/model (real backend) --------------------------
    # Isolate home so the user's real keyring/config are not touched:
    # keys are imported into a temporary home via the real SecretBroker.
    import pathlib
    temp_home = Path(os.environ.get("TEMP", Path.home())) / "isyco_acceptance_home"
    temp_home.mkdir(parents=True, exist_ok=True)
    real_home = Path.home()
    pathlib.Path.home = lambda: temp_home
    try:
        controller = AppController(workspace)
    finally:
        pathlib.Path.home = lambda: real_home
    evidence["isolated_home"] = str(temp_home)

    auth = real_home / ".local" / "share" / "opencode" / "auth.json"
    if auth.is_file():
        try:
            from ui.keys import import_opencode_keys_ui
            imported = import_opencode_keys_ui(controller, auth)
            evidence["imported_keys"] = sorted(imported)
        except Exception as exc:
            evidence["import_error"] = str(exc)

    # Host environment keys (the app reads secrets only from SecretBroker;
    # this mirrors the user pasting a key in the Config panel).
    for env_name, provider_name in [
        ("NVIDIA_NIM_API_KEY", "nvidia"),
        ("OPENAI_API_KEY", "openai"),
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("GOOGLE_API_KEY", "google"),
    ]:
        value = os.environ.get(env_name)
        if value:
            controller.set_key(provider_name, value)
            evidence.setdefault("env_keys", []).append(provider_name)

    selected = None
    probe_failures = []

    async def probe_all():
        nonlocal selected
        for provider_type, model in PROVIDER_CANDIDATES:
            name = provider_type
            if provider_type != "ollama" and not controller.has_key(name):
                continue
            error = await probe(controller, name, provider_type, model)
            if error is None:
                selected = (name, model)
                return
            probe_failures.append(f"{provider_type}/{model}: {error}")
            log(f"probe {provider_type}/{model} failed: {error}")

    asyncio.run(probe_all())
    evidence["probe_failures"] = probe_failures
    if selected is None:
        evidence["steps"]["provider"] = {
            "status": "FAIL", "detail": "no working provider with key"}
        _write_evidence(out_path, evidence)
        log("FAIL: no working provider")
        return 1
    evidence["provider"] = {"name": selected[0], "model": selected[1]}
    log(f"provider selected: {selected}")

    # --- open window (same code as isycode.exe) ------------------------
    window = MainWindow(controller=controller)
    window.show()
    app.processEvents()
    window.provider_combo.setCurrentText(selected[0])
    window.model_combo.setCurrentText(selected[1])
    app.processEvents()
    evidence["steps"]["window"] = {
        "status": "PASS",
        "provider_combo": window.provider_combo.currentText(),
        "model_combo": window.model_combo.currentText(),
        "tabs": [window.bottom_tabs.tabText(i)
                 for i in range(window.bottom_tabs.count())],
    }
    log("window open, provider/model selected")

    # --- multi-step task ------------------------------------------------
    result_1 = run_task(app, window, TASK_1, timeout_s=300)
    evidence["steps"]["task1"] = result_1
    log(f"task1 completed={result_1['completed']} tools={result_1['new_tool_rows']}")

    # --- see edits on disk ----------------------------------------------
    utils = workspace / "utils.py"
    test_sum = workspace / "tests" / "test_sum.py"
    evidence["steps"]["files"] = {
        "utils.py": utils.read_text(encoding="utf-8") if utils.is_file() else None,
        "tests/test_sum.py": test_sum.read_text(encoding="utf-8")
        if test_sum.is_file() else None,
    }

    # --- see diff --------------------------------------------------------
    if utils.is_file():
        window._open_file(str(utils))
        app.processEvents()
        window.editor_panel.editor.setPlainText(
            window.editor_panel.current_text() + "\n# diff preview\n")
        app.processEvents()
        diff_html = window.diff_browser.toHtml()
        evidence["steps"]["diff"] = {
            "status": "PASS" if ("diff-add" in diff_html or "diff-del" in diff_html)
            else "FAIL",
            "changed": window.editor_panel.dirty(),
        }
        window.editor_panel.editor.undo()
    else:
        evidence["steps"]["diff"] = {"status": "SKIP", "detail": "utils.py missing"}

    # --- run tests (Tests panel, real QProcess) --------------------------
    window.tests_panel.run()
    tests_ok = pump_until(app, lambda: not window.tests_panel.run_button.isEnabled(),
                          300)
    output = window.tests_panel.output.toPlainText()
    evidence["steps"]["tests"] = {
        "completed": tests_ok,
        "exit_summary": output.splitlines()[-3:] if output else [],
        "passed_marker": ("passed" in output.lower() or "ok" in output.lower()),
    }
    log(f"tests completed={tests_ok}")

    # --- evidence (contract verifier through the panel) ------------------
    import verifier.contract_verifier as cv
    original_report = cv.write_report
    cv.write_report = lambda results: None  # keep the repo untouched
    window.evidence_panel.run_verify()
    verify_ok = pump_until(app, lambda: window.evidence_panel.verify_button.isEnabled(),
                           60)
    cv.write_report = original_report
    tree = window.evidence_panel.tree
    targets = [tree.topLevelItem(i).text(0)
               for i in range(tree.topLevelItemCount())]
    evidence["steps"]["evidence"] = {
        "completed": verify_ok,
        "targets": targets,
        "view_preview": window.evidence_panel.view.toPlainText()[:400],
    }
    log(f"verify completed={verify_ok} targets={targets}")

    # --- continue conversation ------------------------------------------
    result_2 = run_task(app, window, TASK_2, timeout_s=300)
    evidence["steps"]["task2"] = result_2
    log(f"task2 completed={result_2['completed']} tools={result_2['new_tool_rows']}")

    # --- resident sessions recorded -------------------------------------
    evidence["steps"]["sessions"] = [
        s["id"] for s in controller.sessions()]

    # --- verdict ---------------------------------------------------------
    checks = [
        ("task1 completed", evidence["steps"]["task1"]["completed"]),
        ("files written", utils.is_file() and test_sum.is_file()),
        ("tool calls visible", evidence["steps"]["task1"]["new_tool_rows"] > 0),
        ("diff rendered", evidence["steps"]["diff"].get("status") == "PASS"),
        ("tests ran", evidence["steps"]["tests"]["completed"]),
        ("evidence verified", evidence["steps"]["evidence"]["completed"]),
        ("conversation continued", evidence["steps"]["task2"]["completed"]),
        ("sessions recorded", len(evidence["steps"]["sessions"]) >= 1),
    ]
    evidence["verdict"] = {
        "passed": sum(1 for _name, ok in checks if ok),
        "total": len(checks),
        "checks": {name: ok for name, ok in checks},
    }
    _write_evidence(out_path, evidence)
    log(f"VERDICT: {evidence['verdict']['passed']}/{evidence['verdict']['total']} "
        f"-> {'PASS' if evidence['verdict']['passed'] == evidence['verdict']['total'] else 'FAIL'}")
    window.close()
    app.processEvents()
    return 0 if evidence["verdict"]["passed"] == evidence["verdict"]["total"] else 1


def _write_evidence(out_path: Path, evidence: dict) -> None:
    out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    log(f"evidence written: {out_path}")


if __name__ == "__main__":
    raise SystemExit(main())