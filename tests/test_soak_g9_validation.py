import asyncio
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def module(monkeypatch):
    monkeypatch.setattr('sys.argv', ['soak_g9.py'])
    spec = importlib.util.spec_from_file_location('soak_g9', Path(__file__).parents[1] / 'scripts/soak_g9.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def valid():
    sample = dict(orphans=0, write_verified=True, undo_verified=True, journal_verified=True)
    return dict(active_seconds=7201, started=0, finished=7201, cycles=102, restarts=3, failures=[],
                rss_samples=[sample], warm_baselines={'3': 100}, final_rss_mib=120)


def test_gate_requires_real_checks(monkeypatch):
    mod = module(monkeypatch)
    assert all(mod.evaluate(valid()).values())
    for field, value in [('active_seconds', 100), ('finished', 100), ('cycles', 99), ('restarts', 2),
                         ('failures', ['failure']), ('final_rss_mib', 126),
                         ('warm_baselines', {})]:
        state = valid()
        state[field] = value
        assert not all(mod.evaluate(state).values()), field
    for field in ['write_verified', 'undo_verified', 'journal_verified', 'orphans']:
        state = copy.deepcopy(valid())
        state['rss_samples'][0][field] = 1 if field == 'orphans' else False
        assert not all(mod.evaluate(state).values()), field


def test_real_cycle_verifies_effects_and_restores_cwd(monkeypatch):
    mod = module(monkeypatch)
    cwd = Path.cwd()
    result = asyncio.run(mod.one_cycle(0))
    assert all(result[k] for k in ['write_verified', 'undo_verified', 'journal_verified'])
    assert Path.cwd() == cwd


def test_a_host_that_reports_nothing_about_memory_or_children_claims_nothing(monkeypatch):
    """macOS has no /proc: an absent measurement is not a green gate and not a leak."""
    mod = module(monkeypatch)
    monkeypatch.setattr(mod, "rss_mib", lambda: None)
    monkeypatch.setattr(mod, "orphans", lambda: None)
    assert mod.sample_rss() is None and mod.sample_orphans() is None
    cycle = asyncio.run(mod.one_cycle(0))
    assert cycle["rss_mib"] is None and cycle["orphans"] is None
    assert all(cycle[k] for k in ['write_verified', 'undo_verified', 'journal_verified'])
    state = valid()
    state['final_rss_mib'] = None
    state['rss_samples'][0]['orphans'] = None
    verdict = mod.evaluate(state)
    assert verdict['rss'] is False and verdict['no_orphans'] is False


def test_denied_undo_is_a_failure_not_a_successful_cycle(monkeypatch):
    mod = module(monkeypatch)
    from isycode.workspace_write import WorkspaceWriteOwner
    original = WorkspaceWriteOwner.apply
    def deny_undo(self, preview, approval):
        if preview.is_undo:
            return SimpleNamespace(decision='DENY', receipt=None)
        return original(self, preview, approval)
    monkeypatch.setattr(WorkspaceWriteOwner, 'apply', deny_undo)
    cwd = Path.cwd()
    with pytest.raises(RuntimeError, match='undo not allowed'):
        asyncio.run(mod.one_cycle(0))
    assert Path.cwd() == cwd


def test_legacy_and_corrupt_state_cannot_silently_restart(monkeypatch, tmp_path):
    mod = module(monkeypatch)
    mod.STATE_PATH = tmp_path / 'state.json'
    mod.STATE_PATH.write_text('{"cycles": 102}')
    with pytest.raises(RuntimeError, match='legacy'):
        mod.load_state()
    mod.STATE_PATH.write_text('not json')
    with pytest.raises(ValueError):
        mod.load_state()
