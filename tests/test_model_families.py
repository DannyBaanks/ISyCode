"""M-UX3.3: model catalog grouped by brand family.

Provider -> family (child) -> variant (grandchild): the picker shows
family folders instead of a flat ~100-model list. Variant ids reach
_select_provider untouched.
"""
import pytest

from isycode.model_presentation import OTHER_FAMILY, model_family


def test_model_family_groups_real_ids():
    assert model_family("glm-5.3") == "GLM"
    assert model_family("glm-5.3-flash") == "GLM"
    assert model_family("glm-5.2-flash") == "GLM"
    assert model_family("gpt-6-luna") == "GPT"
    assert model_family("zhipu/glm-5.3") == "GLM"
    assert model_family("deepseek-r1-0528") == "DeepSeek"
    assert model_family("qwen3-coder") == "Qwen"
    assert model_family("llama-4-maverick") == "Llama"
    assert model_family("kimi-k2") == "Kimi"


def test_model_family_falls_back_to_otros():
    assert model_family("auto") == OTHER_FAMILY
    assert model_family("mistral-large-3") == OTHER_FAMILY
    assert model_family("") == OTHER_FAMILY


@pytest.mark.asyncio
async def test_family_rows_and_variant_navigation(tmp_path, monkeypatch):
    from test_daily_tui import configure
    configure(tmp_path, monkeypatch)
    from isycode.tui import TUIApp

    catalog = ["glm-5.3", "glm-5.3-flash", "glm-5.2-flash", "gpt-6-luna", "auto"]

    monkeypatch.setattr("isycode.providers.Provider.models", lambda self: list(catalog))
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._load_account_models("openai")
        rows = app._account_model_catalogs["openai"]
        kinds = [row["kind"] for row in rows]
        assert kinds.count("model_family") == 1
        family_row = next(row for row in rows if row["kind"] == "model_family")
        assert "GLM" in family_row["label"] and "3 models" in family_row["label"]
        direct = [row for row in rows if row["kind"] == "model" and not row["label"].startswith("★")]
        assert {row["value"] for row in direct} == {"openai|gpt-6-luna", "openai|auto"}
        app._menu_model_family(family_row)
        assert app._menu_title == "Models · GLM"
        variant_ids = [row["value"] for row in app._menu_entries if row["kind"] == "model"]
        assert variant_ids == ["openai|glm-5.3", "openai|glm-5.3-flash", "openai|glm-5.2-flash"]
        assert app._menu_entries[-1]["kind"] == "settings_back"
        app._menu_settings_back({})
        assert app._menu_title != "Models · GLM"


@pytest.mark.asyncio
async def test_variant_selection_reaches_select_provider_with_intact_id(tmp_path, monkeypatch):
    from test_daily_tui import configure
    configure(tmp_path, monkeypatch)
    from isycode.tui import TUIApp

    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._account_family_variants = {
            ("openai", "GLM"): [
                {"label": "glm-5.3-flash", "kind": "model", "value": "openai|glm-5.3-flash"},
            ],
        }
        chosen = []
        monkeypatch.setattr(TUIApp, "_select_provider",
                            lambda self, name, model=None: chosen.append((name, model)))
        app._menu_model_family({"kind": "model_family", "value": "openai|GLM"})
        row = next(row for row in app._menu_entries if row["kind"] == "model")
        app._menu_model(row)
        assert chosen == [("openai", "glm-5.3-flash")]


@pytest.mark.asyncio
async def test_presets_are_labeled_and_catalog_deny_offers_grant(tmp_path, monkeypatch):
    from test_daily_tui import configure
    configure(tmp_path, monkeypatch)
    from isycode.tui import TUIApp

    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        entries = app._branch_entries("models")
        presets = [row for row in entries if row["kind"] == "model" and "preset" in row["label"]]
        assert presets, "preset models must be visibly labeled"
        assert all("preset" in (row.get("detail") or "") for row in presets)


@pytest.mark.asyncio
async def test_catalog_denial_adds_actionable_grant_entry(tmp_path, monkeypatch):
    from test_daily_tui import configure
    configure(tmp_path, monkeypatch)
    from isycode.action_runtime import ActionOutcome
    from isycode.tui import TUIApp

    async def denied_execute(self, provider, payload, transport):
        return None, ActionOutcome("Denied.", "DENY", None, "host not granted")

    monkeypatch.setattr("isycode.action_runtime.ProviderNetworkOwner.execute", denied_execute)
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._menu_mode = "model_account"
        await app._load_account_models("openai")
        grant = [row for row in app._menu_entries if row["kind"] == "provider_catalog_grant"]
        assert grant and grant[0]["value"] == "openai"
        assert any("deny" in row["label"] for row in app._menu_entries if row["kind"] == "info")


def test_vendored_modelsdev_catalog_validates_and_maps():
    from isycode.model_catalog import catalog_models, load_catalog, source_provenance
    load_catalog.cache_clear()
    nvidia = catalog_models("nvidia")
    assert nvidia and all(isinstance(entry["id"], str) for entry in nvidia)
    assert any(entry["tool_call"] for entry in nvidia)
    assert any(entry["id"] == "glm-5.3" for entry in catalog_models("zai"))
    assert catalog_models("ollama") == []
    assert source_provenance()["source"] == "https://models.dev/api.json"
    assert len(source_provenance()["source_sha256"]) == 64


@pytest.mark.asyncio
async def test_picker_shows_catalog_models_with_tool_marker(tmp_path, monkeypatch):
    from test_daily_tui import configure
    configure(tmp_path, monkeypatch)
    from isycode.tui import TUIApp

    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        entries = app._branch_entries("models")
        catalog = [row for row in entries if row["kind"] == "model" and "· catalog" in row["label"]]
        assert catalog, "models.dev entries must appear without a live catalog"
        assert any("no tools" in row["label"] or "tool_call=yes" in (row["detail"] or "")
                   for row in catalog)
        assert all("preset" not in row["label"] for row in catalog)


@pytest.mark.asyncio
async def test_models_screen_renders_family_variants(tmp_path, monkeypatch):
    from test_daily_tui import configure
    configure(tmp_path, monkeypatch)
    from isycode.tui import TUIApp, ModelsScreen

    catalog = ["glm-5.3", "glm-5.3-flash", "glm-5.2-flash"]
    monkeypatch.setattr("isycode.providers.Provider.models", lambda self: list(catalog))
    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._load_account_models("openai")
        entries = app._branch_entries("models")
        assert any(row["kind"] == "model_family" for row in entries)
        screen = ModelsScreen(entries)
        await app.push_screen(screen)
        await pilot.pause()
        rendered = str(app.screen.query_one("#models-scroll").content) if hasattr(app.screen.query_one("#models-scroll"), "content") else ""
        labels = [str(button.label) for button in app.screen.query(".model-choice")]
        assert any("glm-5.3-flash" in label for label in labels), labels


@pytest.mark.asyncio
async def test_models_screen_click_after_immediate_open_does_not_crash(tmp_path, monkeypatch):
    from test_daily_tui import configure
    configure(tmp_path, monkeypatch)
    from isycode.tui import TUIApp, ModelsScreen

    app = TUIApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        entries = app._branch_entries("models")
        app._render_menu("model_account", "Models · account catalog", entries)
        await pilot.pause()
        await pilot.click("#models-search")
        await pilot.pause()
        assert isinstance(app.screen, ModelsScreen)
