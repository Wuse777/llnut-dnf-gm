"""Admission plan integrity, race and recovery with synthetic DB evidence."""
import copy

import pytest

from maintenance_admission import validate_plan, validate_proof, validate_token
from maintenance_drain import digest
from dnfgm.release_files import Refused, atomic_json
from test_maintenance_drain import rig, prepare, restart, RID


@pytest.mark.parametrize('field', ['server_uuid', 'version', 'gate', 'extra'])
def test_admission_plan_rejects_invalid_types_or_unbound_fields(rig, field):
    c, h, _ = rig
    plan = c.admission.prepare()
    plan[field] = {'server_uuid': 'not-a-uuid', 'version': True, 'gate': {'state': 'open'}, 'extra': 'ignored?'}[field]
    with pytest.raises((Refused, KeyError)):
        validate_plan(plan)
    assert not h.calls


@pytest.mark.parametrize('field,value', [('generation', 9), ('operation_id', 'b'*32), ('binding_sha256', 'a'*64),
                                         ('state', 'open'), ('version', True)])
def test_frozen_token_cannot_be_rebound_to_another_request(rig, field, value):
    c, h, _ = rig
    plan = c.admission.prepare()
    token = c.admission.freeze(RID, h.identity(), plan)
    token[field] = value
    with pytest.raises(Refused):
        validate_token(token, plan, RID, h.identity())


@pytest.mark.parametrize('field,value', [('protocol_version', True), ('generation', False),
                                         ('server_uuid', '12345678-1234-1234-1234-aaaaaaaaaaaa'),
                                         ('ordinary_transactions_drained', False), ('maintenance_permit', True),
                                         ('checked_at', float('nan')), ('checked_at', -1)])
def test_database_proof_checks_types_identity_and_scope(rig, field, value):
    c, h, _ = rig
    plan = c.admission.prepare()
    token = c.admission.freeze(RID, h.identity(), plan)
    proof = c.admission.drain(plan, token)
    proof[field] = value
    with pytest.raises(Refused):
        validate_proof(proof, plan, token)


def test_compare_generation_and_freeze_are_atomic_under_gate_lock(rig, monkeypatch):
    c, h, _ = rig
    prepared = prepare(c)
    original = c.admission.verify_plan
    def racing(plan):
        original(plan)
        token = c.admission.gate.freeze('b'*32, h.identity())
        c.admission.gate.release(token, lambda: True)  # test-only unrelated lifecycle
    monkeypatch.setattr(c.admission, 'verify_plan', racing)
    result = c.confirm(RID, prepared['fingerprint'])
    assert result['state'] == 'needs_review' and not h.calls
    assert c.admission.gate.read()['operation_id'] == 'b'*32
    assert c.admission.gate.read()['state'] == 'open'


def test_database_identity_change_after_freeze_keeps_gate_closed_and_sends_nothing(rig, monkeypatch):
    c, h, _ = rig
    prepared = prepare(c)
    original = c.admission.freeze
    def replaced(*args):
        token = original(*args)
        c.admission.server_uuid = '12345678-1234-1234-1234-aaaaaaaaaaaa'
        return token
    monkeypatch.setattr(c.admission, 'freeze', replaced)
    result = c.confirm(RID, prepared['fingerprint'])
    assert result['error'] == 'maintenance_database_identity_changed'
    assert result['phase'] == 'write-gate-frozen'
    assert not h.calls and c.admission.gate.read()['state'] == 'frozen'


def test_malformed_proof_from_adapter_is_not_recorded_or_accepted(rig, monkeypatch):
    c, h, _ = rig
    prepared = prepare(c)
    original = c.admission.drain
    def wrong(*args):
        proof = original(*args)
        proof['maintenance_permit'] = True
        return proof
    monkeypatch.setattr(c.admission, 'drain', wrong)
    result = c.confirm(RID, prepared['fingerprint'])
    assert result['error'] == 'maintenance_journal_transition_invalid'
    assert result['phase'] == 'write-gate-frozen' and not h.calls
    assert c.admission.gate.read()['state'] == 'frozen'


def test_lost_gate_invalidates_command_precondition(rig, monkeypatch):
    c, h, _ = rig
    prepared = prepare(c)
    original = c.admission.drain
    def changed(*args):
        result = original(*args)
        c.admission.gate.release(args[1], lambda: True)  # unexpected root state change
        return result
    monkeypatch.setattr(c.admission, 'drain', changed)
    result = c.confirm(RID, prepared['fingerprint'])
    assert result['state'] == 'needs_review' and result['phase'] == 'database-drained'
    assert not h.calls


@pytest.mark.parametrize('change', ['server_uuid','generation','operation_id'])
def test_rehashed_journal_cannot_change_proof_binding(rig, change):
    c, h, _ = rig
    prepared = prepare(c)
    assert c.confirm(RID, prepared['fingerprint'])['state'] == 'game_drained'
    doc = c._load(RID)
    proof = doc['events'][2]['data']
    proof[change] = {'server_uuid': '12345678-1234-1234-1234-aaaaaaaaaaaa', 'generation': 4, 'operation_id': 'b'*32}[change]
    # Even a structurally valid hash chain must match the original plan.
    for i, e in enumerate(doc['events']):
        e['previous'] = doc['binding'] if i == 0 else doc['events'][i-1]['digest']
        e['digest'] = digest({k:v for k,v in e.items() if k != 'digest'})
    atomic_json(c.root/(RID+'.json'), doc, mode=0o600)
    calls = copy.deepcopy(h.calls)
    with pytest.raises(Refused, match='journal_invalid'):
        restart(c).confirm(RID, prepared['fingerprint'])
    assert h.calls == calls
