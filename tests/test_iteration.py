import asyncio
import json
from pathlib import Path

import pytest
from isycode.iteration import IterationOwner, IterationDenied, run_iteration
from isycode.providers import Provider
from isycode.workspace_authority import WorkspaceAuthority
from isycode.action_audit import ActionAuditJournal


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'workspace'; root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / 'authority')
    authority.set_grant('session.create', enabled=True)
    authority.set_grant('session.resume', enabled=True)
    authority.set_grant('provider.request', enabled=True, network_hosts=['integrate.api.nvidia.com', 'api.openai.com'])
    owner = IterationOwner(root, authority, directory=tmp_path / 'iterations')
    sid = owner.create_iteration('A test', [dict(provider='nvidia', model='fixture-a', role='PROPOSER'),
                                dict(provider='openai', model='fixture-b', role='REVIEWER FINAL')])
    owner.human(sid, 'Propose a verifiable token.')
    return owner, authority, sid


def participant(owner, sid, index):
    return owner.inspect(sid)['participants'][index]['participant_id']


def observe(owner, sid, attempt):
    return owner.read(sid, attempt['participant_id'], attempt['attempt_id'], attempt['iteration_ref'], 0, attempt['based_on_seq'])


def finish(owner, sid, a, text='TOKEN_A=nonce-314159'):
    return owner.finish(sid, a['participant_id'], a['turn_id'], a['attempt_id'], a['based_on_seq'], text)


def test_order_read_immutability_replay_handoff_and_identity(setup):
    owner, _, sid = setup
    a = owner.begin(sid, participant(owner, sid, 0))
    assert [r['seq'] for r in observe(owner, sid, a)] == [1]
    first = finish(owner, sid, a)
    prefix = (owner.directory / (sid + '.jsonl')).read_bytes()
    assert finish(owner, sid, a)['replay'] is True
    b = owner.begin(sid, participant(owner, sid, 1))
    assert observe(owner, sid, b)[-1]['content'] == first['content']
    finish(owner, sid, b, 'HUMAN_HANDOFF: token nonce-314159 verified. Human decides next.')
    state = owner.inspect(sid)
    assert state['status'] == 'WAITING_FOR_HUMAN'
    assert [r['kind'] for r in state['turns']] == ['human', 'agent', 'human_handoff']
    assert [r['seq'] for r in state['turns']] == [1, 2, 3]
    assert [r.get('based_on_seq') for r in state['turns']] == [None, 1, 2]
    assert (owner.directory / (sid + '.jsonl')).read_bytes().startswith(prefix)
    owner.rename(sid, 'Renamed')
    restarted = IterationOwner(owner.root, owner.authority, directory=owner.directory)
    assert restarted.inspect(sid)['iteration_session_id'] == sid
    assert restarted.inspect(sid)['title'] == 'Renamed'
    assert len(state['receipts']) == 2
    assert ActionAuditJournal(owner.root).verify().status == 'PASS'


@pytest.mark.parametrize('case', ['fake', 'participant', 'future', 'negative', 'session'])
def test_reference_denials(setup, case):
    owner, _, sid = setup
    a = owner.begin(sid, participant(owner, sid, 0))
    ref, pid, after, through = a['iteration_ref'], a['participant_id'], 0, 1
    if case == 'fake': ref = 'fake'
    if case == 'participant': pid = participant(owner, sid, 1)
    if case == 'future': through = 2
    if case == 'negative': after = -1
    if case == 'session':
        sid = owner.create_iteration('Other', [dict(provider='nvidia', model='x', role='A'), dict(provider='openai', model='y', role='B')])
        owner.human(sid, 'Other human')
        owner.begin(sid, participant(owner, sid, 0))
    with pytest.raises(IterationDenied):
        owner.read(sid, pid, a['attempt_id'], ref, after, through)


@pytest.mark.parametrize('case', ['writer', 'stale', 'attempt', 'turn', 'unread'])
def test_append_denials(setup, case):
    owner, _, sid = setup
    a = owner.begin(sid, participant(owner, sid, 0))
    if case != 'unread': observe(owner, sid, a)
    args = [sid, a['participant_id'], a['turn_id'], a['attempt_id'], 1, 'Contribution']
    if case == 'writer': args[1] = participant(owner, sid, 1)
    if case == 'stale': args[4] = 0
    if case == 'attempt': args[3] = '0' * 32
    if case == 'turn': args[2] = '0' * 32
    before = (owner.directory / (sid + '.jsonl')).read_bytes()
    with pytest.raises(IterationDenied): owner.finish(*args)
    assert (owner.directory / (sid + '.jsonl')).read_bytes() == before


def test_error_retry_new_attempt_same_turn_and_head(setup):
    owner, _, sid = setup
    a = owner.begin(sid, participant(owner, sid, 0)); observe(owner, sid, a); finish(owner, sid, a)
    b = owner.begin(sid, participant(owner, sid, 1)); observe(owner, sid, b)
    owner.stop(sid, b['attempt_id'], error_kind='SALDO')
    assert owner.inspect(sid)['head_seq'] == 2
    restarted = IterationOwner(owner.root, owner.authority, directory=owner.directory)
    retry = restarted.begin(sid, b['participant_id'])
    assert retry['attempt_id'] != b['attempt_id']
    assert retry['turn_id'] == b['turn_id'] and retry['based_on_seq'] == 2
    with pytest.raises(IterationDenied): finish(owner, sid, b)
    observe(restarted, sid, retry); finish(restarted, sid, retry, 'HUMAN_HANDOFF: retry verified')
    assert [r['outcome'] for r in owner.inspect(sid)['receipts']] == ['SUCCESS', 'PARTICIPANT_ERROR', 'SUCCESS']


def test_cancel_corruption_secrets_and_denied_grants(setup):
    owner, authority, sid = setup
    a = owner.begin(sid, participant(owner, sid, 0))
    owner.stop(sid, a['attempt_id'], outcome='ABORTED')
    with pytest.raises(IterationDenied): owner.begin(sid, a['participant_id'])
    assert owner.inspect(sid)['head_seq'] == 1
    authority.set_grant('session.create', enabled=False)
    with pytest.raises(IterationDenied): owner.rename(sid, 'No')
    authority.set_grant('session.resume', enabled=False)
    with pytest.raises(IterationDenied): owner.inspect(sid)
    authority.set_grant('session.resume', enabled=True)
    with (owner.directory / (sid + '.jsonl')).open('ab') as f: f.write(b'{')
    with pytest.raises(IterationDenied): owner.inspect(sid)


def factory(p):
    return Provider(name=p['provider'], model=p['model'], api_key='fixture-only')


def fixture_transport(observed, fail_b=False):
    async def transport(provider, messages, tools):
        assert [t['function']['name'] for t in tools] == ['read_iteration']
        if messages[-1]['role'] == 'user':
            task = json.loads(messages[-1]['content'])
            return {'text': '', 'tool_calls': [{'id': 'read-1', 'type': 'function', 'function': {'name': 'read_iteration',
                'arguments': json.dumps({'ref': task['iteration_ref'], 'after_seq': 0, 'through_seq': task['head_seq']})}}]}
        rows = json.loads(messages[-1]['content'])
        observed.append((provider.name, rows))
        if provider.name == 'nvidia':
            assert len(rows) == 1
            return {'text': 'TOKEN_A=nonce-314159', 'tool_calls': []}
        assert rows[-1]['content'] == 'TOKEN_A=nonce-314159'
        if fail_b: raise TimeoutError('controlled fixture failure')
        return {'text': 'HUMAN_HANDOFF: TOKEN_A=nonce-314159 verified; human chooses next.', 'tool_calls': []}
    return transport


def test_existing_run_child_owned_loop_and_failure_retry(setup):
    owner, _, sid = setup
    observed = []
    state = asyncio.run(run_iteration(owner, sid, factory, transport=fixture_transport(observed, True)))
    assert state['head_seq'] == 2 and state['status'] == 'PARTICIPANT_ERROR'
    failed = state['receipts'][-1]
    state = asyncio.run(run_iteration(owner, sid, factory, transport=fixture_transport(observed)))
    assert state['status'] == 'WAITING_FOR_HUMAN'
    assert state['receipts'][-1]['attempt_id'] != failed['attempt_id']
    assert state['receipts'][-1]['based_on_seq'] == 2
    assert [name for name, _ in observed] == ['nvidia', 'openai', 'openai']


def test_network_denial_never_calls_transport(setup):
    owner, authority, sid = setup
    authority.set_grant('provider.request', enabled=False)
    async def forbidden(*args): raise AssertionError('transport bypass')
    state = asyncio.run(run_iteration(owner, sid, factory, transport=forbidden))
    assert state['head_seq'] == 1 and state['status'] == 'PARTICIPANT_ERROR'


def test_creation_denied_no_new_artifact_and_secret_redaction(setup):
    owner, authority, sid = setup
    before = set(owner.directory.iterdir())
    authority.set_grant('session.create', enabled=False)
    with pytest.raises(IterationDenied):
        owner.create_iteration('Denied', [dict(provider='nvidia',model='a',role='A'),dict(provider='openai',model='b',role='B')])
    assert set(owner.directory.iterdir()) == before
    authority.set_grant('session.create', enabled=True)
    a = owner.begin(sid, participant(owner,sid,0)); observe(owner,sid,a)
    finish(owner,sid,a,'api_key=hunter2 and sk-'+'A'*40)
    raw = (owner.directory/(sid+'.jsonl')).read_text()
    assert 'hunter2' not in raw and 'sk-'+'A'*40 not in raw
    assert a['iteration_ref'] not in raw


def test_corrupt_hash_fails_closed(setup):
    owner, _, sid = setup
    path = owner.directory/(sid+'.jsonl')
    path.write_bytes(path.read_bytes().replace(b'A test',b'B test'))
    with pytest.raises(IterationDenied): owner.inspect(sid)


def test_two_contenders_one_writer(setup):
    from concurrent.futures import ThreadPoolExecutor
    owner, _, sid = setup
    pid=participant(owner,sid,0)
    def claim():
        peer=IterationOwner(owner.root,owner.authority,directory=owner.directory)
        try: return peer.begin(sid,pid)['attempt_id']
        except IterationDenied: return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(lambda _:claim(),range(2)))
    assert sum(value is not None for value in outcomes)==1


def test_coordinator_cancel_leaves_valid_aborted_artifact(setup):
    owner, _, sid = setup
    async def scenario():
        entered=asyncio.Event()
        async def wait(*args):
            entered.set()
            await asyncio.Future()
        task=asyncio.create_task(run_iteration(owner,sid,factory,transport=wait))
        await asyncio.wait_for(entered.wait(),5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        state=owner.inspect(sid)
        assert state['status']=='ABORTED' and state['head_seq']==1
        assert state['receipts'][-1]['error_kind']=='CANCELLED'
    asyncio.run(scenario())
