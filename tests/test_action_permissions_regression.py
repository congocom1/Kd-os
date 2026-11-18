"""Security boundary regressions; no desktop/network handlers are executed."""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from core.action_permissions import ActionPermissionManager
from core.action_loader import ActionRecord, ActionRegistry, _validate, discover_actions


def manager():
    pm = ActionPermissionManager(lambda principal, action, permissions: principal == 'session:user')
    pm.register_action('send', required_permissions=['send'])
    return pm


def test_fail_closed_and_voice_is_never_authority():
    pm = ActionPermissionManager()
    pm.register_action('send', needs_approval=False, side_effects=['external_send'])
    assert pm.check_and_authorize('missing', {}) == (False, 'unknown_action')
    assert pm.check_and_authorize('send', {}, 'session:user')[0] is False
    with pytest.raises(PermissionError):
        pm.approve('send', {}, approved_by='system')
    pm = manager()
    with pytest.raises(PermissionError):
        pm.approve('send', {}, approved_by='session:user')
    pm.approve('send', {}, principal_id='session:user')
    assert not pm.check_and_authorize('send', {}, 'session:user')[0]
    assert not pm.check_and_authorize('send', {}, principal_id='other')[0]
    assert pm.check_and_authorize('send', {}, principal_id='session:user') == (True, 'approved')
    assert not pm.check_and_authorize('send', {}, principal_id='session:user')[0]


@pytest.mark.parametrize('checker', [lambda *a: 1, lambda *a: (_ for _ in ()).throw(RuntimeError('secret'))])
def test_checker_errors_and_nonboolean_allow_fail_closed(checker):
    pm = ActionPermissionManager(checker)
    pm.register_action('send')
    assert not pm.check_and_authorize('send', {}, principal_id='user')[0]
    with pytest.raises(PermissionError):
        pm.approve('send', {}, principal_id='user')


def test_grant_immutable_exact_and_bound_to_principal():
    pm = manager()
    args = {'nested': [{'value': 1}]}
    grant = pm.approve('send', args, principal_id='session:user')
    args['nested'][0]['value'] = 2
    grant.args['nested'][0]['value'] = 3
    with pytest.raises(FrozenInstanceError):
        grant.approved_by = 'other'
    for value in (2, True, 1.0):
        assert not pm.check_and_authorize('send', {'nested': [{'value': value}]}, principal_id='session:user')[0]
    assert pm.check_and_authorize('send', {'nested': [{'value': 1}]}, principal_id='session:user')[0]


@pytest.mark.parametrize('args', [{1: 'secret'}, {'a': float('nan')}, {'a': (1, 2)}, [], {'a': object()}])
def test_non_json_arguments_refused_and_audited(args):
    pm = manager()
    with pytest.raises(ValueError):
        pm.approve('send', args, principal_id='session:user')
    assert pm.check_and_authorize('send', args, principal_id='session:user') == (False, 'invalid_arguments')
    assert len(pm.list_audit()) == 2


def test_expiry_status_and_concurrent_single_use(monkeypatch):
    pm = manager()
    now = [100.0]
    monkeypatch.setattr('core.action_permissions.time.monotonic', lambda: now[0])
    pm.approve('send', {}, principal_id='session:user', expires_in_seconds=1)
    assert pm.status()['active_approvals'] == 1
    now[0] = 101.0
    assert not pm.is_approved('send', {}, principal_id='session:user')
    assert pm.status()['active_approvals'] == 0
    pm.approve('send', {}, principal_id='session:user')
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: pm.check_and_authorize('send', {}, principal_id='session:user')[0], range(32)))
    assert sum(outcomes) == 1


@pytest.mark.parametrize('ttl', [0, -1, float('inf'), float('nan'), True, 301])
def test_invalid_lifetime(ttl):
    with pytest.raises(ValueError):
        manager().approve('send', {}, principal_id='session:user', expires_in_seconds=ttl)


def test_declarations_are_immutable_and_changes_revoke():
    pm = manager()
    pm.approve('send', {}, principal_id='session:user')
    with pytest.raises(FrozenInstanceError):
        pm.get_decl('send').needs_approval = False
    pm.register_action('send', required_permissions=['new'])
    assert not pm.is_approved('send', {}, principal_id='session:user')


def test_audit_redacts_all_payloads_and_is_defensive():
    pm = manager()
    pm.check_and_authorize('unknown', {'password': 'SECRET'})
    pm.record_execution('send', {'nested': ['SECRET']}, None, True, 'approved', 'failed', result='SECRET', error='SECRET')
    records = pm.list_audit()
    assert len(records) == 2
    assert 'SECRET' not in json.dumps(records)
    records[0]['args']['leak'] = 'SECRET'
    assert 'SECRET' not in json.dumps(pm.list_audit())


def test_loader_registration_safe_compatibility_and_context_not_authority():
    seen = []
    pm = manager()
    rec = ActionRecord('send', valid=True, handler=lambda parameters: seen.append(parameters) or 'secret-result')
    reg = ActionRegistry({'send': rec}, lambda _: None, pm)
    pm.approve('send', {'a': [1]}, principal_id='session:user')
    assert 'refused' in reg.run('send', {'a': [1]}, {'principal_id': 'session:user', 'speaker_id': 'session:user'})
    assert not seen
    original = {'a': [1]}
    assert reg.run('send', original, principal_id='session:user') == 'secret-result'
    seen[0]['a'].append(2)
    assert original == {'a': [1]}
    assert 'secret-result' not in json.dumps(pm.list_audit())
    assert 'refused' in reg.run('send', original, principal_id='session:user')
    safe = ActionRecord('read', valid=True, needs_approval=False, handler=lambda parameters, speak=None: 'ok')
    assert ActionRegistry({'read': safe}, lambda _: None).run('read', {}) == 'ok'


def test_discovery_registers_conservative_declaration(tmp_path):
    (tmp_path / 'regression_unique_action.py').write_text("TOOL = {'name': 'regression_unique_action', 'description': 'test', 'handler': lambda parameters: 'ok'}")
    pm = ActionPermissionManager()
    reg = discover_actions(tmp_path, logger=lambda _: None, permission_manager=pm)
    assert reg.has('regression_unique_action')
    assert pm.get_decl('regression_unique_action').needs_approval is True
    assert 'refused' in reg.run('regression_unique_action', {})
    assert 'not available' in reg.run('unknown', {})
    assert pm.list_audit()[0]['approval_reason'] == 'unknown_action'
    assert 'needs_approval' not in reg.get_tool_declarations()[0]


@pytest.mark.parametrize('metadata', [{'needs_approval': 'false'}, {'required_permissions': 'send'}, {'side_effects': None}, {'timeout_seconds': -1}])
def test_invalid_security_metadata_rejected(metadata):
    rec = _validate(SimpleNamespace(TOOL=dict(name='send', description='test', handler=lambda parameters: None, **metadata)), 'test.py')
    assert not rec.valid


def test_handler_exception_is_redacted_from_audit_logs_and_response():
    def fail(parameters):
        raise RuntimeError('secret-token')
    logs = []
    reg = ActionRegistry({'read': ActionRecord('read', valid=True, needs_approval=False, handler=fail)}, logs.append)
    assert 'secret-token' not in reg.run('read', {})
    assert 'secret-token' not in repr(logs)
    assert 'secret-token' not in repr(reg._permission_manager.list_audit())
