"""RTK opt-in and rewrite advice cannot confer workspace execution authority."""
import asyncio

from test_command_runner import sandbox
from test_rtk_integration import adapter


def test_rtk_allow_cannot_replace_workspace_grant(sandbox, adapter, monkeypatch):
    owner, authority, approvals, executable, log = sandbox
    rtk, _ = adapter
    rtk.Settings().enable()
    monkeypatch.setattr(rtk, '_cli', lambda *args: (0, b'rtk grep needle file'))
    preview = owner.prepare(['grep', 'needle', 'file'])
    assert preview.request.parameters['rtk']['decision'] == 'allow'
    outcome = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert outcome.decision == 'DENY'
    assert not log.exists()


def test_rtk_ask_requires_explicit_approval_in_classic(sandbox, adapter):
    owner, authority, approvals, executable, log = sandbox
    rtk, _ = adapter
    authority.set_mode('classic')
    rtk.Settings().enable()
    preview = owner.prepare(['grep', 'needle', 'file'])
    assert preview.request.parameters['rtk']['decision'] == 'ask'
    assert asyncio.run(owner.run(preview, None)).decision == 'DENY'
    assert not log.exists()


def test_rtk_replacement_after_approval_denies_before_execution(sandbox, adapter):
    owner, authority, approvals, executable, log = sandbox
    rtk, binary = adapter
    authority.set_mode('classic')
    rtk.Settings().enable()
    preview = owner.prepare(['grep', 'needle', 'file'])
    approval = approvals.issue(preview.request)
    binary.write_bytes(b'replaced executable after approval')
    assert asyncio.run(owner.run(preview, approval)).decision == 'DENY'
    assert not log.exists()
