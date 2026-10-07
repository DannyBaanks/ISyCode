import asyncio
from textual.widgets import Collapsible
from isycode.tui import TUIApp, ModelsScreen, plain_text
from isycode.providers import Provider
from isycode import reasoning_options as reasoning
from test_daily_tui import configure


def test_model_accordions_filter_and_open_provider_reasoning(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "test-not-real")
    monkeypatch.setattr(reasoning, "_SELECTIONS", {})
    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._render_menu("branch", "Models", app._branch_entries("models"))
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ModelsScreen)
            for _ in range(200):  # composed (and not mid-rebuild) before it is used
                if app.screen.query('#models-search'):
                    break
                await pilot.pause(0.05)
            screen = app.screen
            assert all(group.collapsed for group in screen.query(Collapsible))
            screen.query_one('#models-search').value = 'nemotron-3-ultra'
            # Searching expands the NVIDIA group, which loads the account catalog in a
            # worker and may rebuild this screen when it finishes. Use the button only
            # once the same widget has stayed on the current screen for a while.
            button, stable = None, 0
            for _ in range(200):
                await pilot.pause(0.05)
                current = app.screen
                found = None
                if isinstance(current, ModelsScreen) and not getattr(app, '_account_models_loading', False):
                    search = current.query('#models-search')
                    if search and search.first().value != 'nemotron-3-ultra':
                        search.first().value = 'nemotron-3-ultra'  # a rebuilt screen starts unfiltered
                        stable, button = 0, None
                        continue
                    found = next((item for item in current.query('.model-choice')
                                  if 'nvidia/nemotron-3-ultra' in str(item.label)), None)
                stable = stable + 1 if found is not None and found is button else 0
                button = found
                if stable >= 10:
                    break
            assert button is not None, 'filtered model button never appeared'

            assert 'Nemotron 3 Ultra' in str(button.label)
            button.press()
            for _ in range(100):
                await pilot.pause(0.05)
                if app._menu_mode == 'reasoning':
                    break
            assert app._menu_mode == 'reasoning'
            assert [entry['value'].rsplit('|', 1)[1] for entry in app._menu_entries] == ['default', 'off', 'on']
            app._select_menu_entry(app._menu_entries[-1])
            await pilot.pause()
            assert Provider(name='nvidia', api_key='test-not-real').reasoning_effort == 'on'
            assert '/ On · NVIDIA NIM' in plain_text(app.query_one('#idea-box'))
            assert 'nvidia/nemotron' not in plain_text(app.query_one('#idea-box'))
            app._open_settings_menu()
            assert all(entry.get('detail') for entry in app._menu_entries)
            assert {entry['category'] for entry in app._menu_entries} == {
                'Conversation', 'Preferences', 'Permissions', 'Connections'}
    asyncio.run(scenario())


def test_catalog_levels_are_model_specific_and_unknown_models_have_no_invented_levels(monkeypatch):
    monkeypatch.setattr(reasoning, '_CATALOG', {})
    reasoning.record_catalog('chatgpt', 'fixture', {'supportedReasoningEfforts': [
        {'reasoningEffort': 'low'}, {'reasoningEffort': 'xhigh'}, {'reasoningEffort': 'bogus'}]})
    assert reasoning.reasoning_levels('chatgpt', 'fixture') == ('low', 'xhigh')
    assert reasoning.reasoning_levels('nvidia', 'z-ai/glm-5.3') == ()
    assert reasoning.reasoning_levels('anthropic', 'claude-opus-4-6') == ('low', 'medium', 'high', 'max')


def test_nvidia_thinking_uses_chat_template_and_does_not_send_generic_effort(monkeypatch):
    from isycode import chat_transport
    monkeypatch.setattr(reasoning, '_SELECTIONS', {})
    calls = []
    async def fake(*args, **kwargs):
        calls.append(kwargs)
        return {'text': 'ok'}
    monkeypatch.setattr(chat_transport, 'async_stream_complete', fake)
    for level, enabled in (('off', False), ('on', True)):
        reasoning.select_reasoning('nvidia', 'nvidia/nemotron-3-ultra-550b-a55b', level)
        provider = Provider(name='nvidia', model='nvidia/nemotron-3-ultra-550b-a55b', api_key='test-not-real')
        asyncio.run(chat_transport.provider_complete(provider, [{'role': 'user', 'content': 'hi'}]))
        assert calls[-1]['chat_template_kwargs'] == {'enable_thinking': enabled}
        assert calls[-1]['reasoning_effort'] is None
