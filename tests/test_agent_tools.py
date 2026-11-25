import asyncio
import json

import pytest

from isycode.agent_tools import LocalAgentTools
from isycode.approvals import ActionApprovalStore
from isycode.workspace_authority import WorkspaceAuthority


class Review:
    def __init__(self, accept=True, mutate=None):
        self.accept, self.mutate, self.seen = accept, mutate, []
    async def review(self, request, material):
        self.seen.append(material)
        if self.mutate:
            self.mutate()
        return self.accept
    async def ask(self, question):
        return {'status': 'answered', 'text': 'yes'}


def call(name, args):
    return {'id': 'one', 'function': {'name': name, 'arguments': json.dumps(args)}}


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'file.txt').write_text('before\n')
    authority = WorkspaceAuthority(root)
    authority.set_mode('classic')
    return root, authority


@pytest.mark.parametrize('accepted', [False, True])
def test_exact_edit_reviews_diff_and_preserves_owner_receipt(tools, accepted):
    root, authority = tools
    review = Review(accepted)
    runner = LocalAgentTools(root, authority, ActionApprovalStore(), review)
    _, text = asyncio.run(runner.dispatch(call('workspace_edit', {
        'path': 'file.txt', 'old_text': 'before', 'new_text': 'after'})))
    assert (root / 'file.txt').read_text() == ('after\n' if accepted else 'before\n')
    assert '-before' in review.seen[0].text and '+after' in review.seen[0].text
    assert ('rejected' in text) if not accepted else json.loads(text).get('receipt')


def test_policy_change_during_review_does_not_apply(tools):
    root, authority = tools
    review = Review(mutate=lambda: authority.set_grant('workspace.files.write', enabled=False))
    runner = LocalAgentTools(root, authority, ActionApprovalStore(), review)
    _, text = asyncio.run(runner.dispatch(call('workspace_write', {'path': 'file.txt', 'content': 'bad'})))
    assert (root / 'file.txt').read_text() == 'before\n'
    assert 'error' in json.loads(text)


def test_preview_drift_after_acceptance_does_not_overwrite_human_change(tools):
    root, authority = tools
    review = Review(mutate=lambda: (root / 'file.txt').write_text('human change'))
    runner = LocalAgentTools(root, authority, ActionApprovalStore(), review)
    _, text = asyncio.run(runner.dispatch(call('workspace_write', {'path': 'file.txt', 'content': 'bad'})))
    assert (root / 'file.txt').read_text() == 'human change'
    assert 'error' in json.loads(text)


def test_question_and_unknown_tool_are_not_effects(tools):
    root, authority = tools
    runner = LocalAgentTools(root, authority, ActionApprovalStore(), Review())
    _, reply = asyncio.run(runner.dispatch(call('ask_user', {'question': 'continue?'})))
    assert json.loads(reply)['text'] == 'yes'
    _, reply = asyncio.run(runner.dispatch(call('shell', {'text': 'do something'})))
    assert 'error' in json.loads(reply)
