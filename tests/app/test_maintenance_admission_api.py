"""Full durable drain entry with REAL isolated MySQL; s6 commands are synthetic.

These tests never call Docker or change a production game/service. Transactions,
locks, filesystem state, hashes, receipt recovery and SQL commits are real.
"""
import copy
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deploy'))
from maintenance_admission import MaintenanceAdmission
from maintenance_drain import DrainCoordinator, digest
from dnfgm.release_files import Refused, atomic_json
from test_game_drain import FakeHost
from test_write_gate import gate
from test_combined_rewards import read, write
from test_application import preview, confirm, P

RID = 'd' * 32


@pytest.fixture
def broker(env, gate, tmp_path):
    host = FakeHost()
    coordinator = DrainCoordinator(tmp_path / 'admitted-journal', host, owner=os.geteuid(),
                                   admission=MaintenanceAdmission(gate, env[2]))
    coordinator.initialize()
    return coordinator


def restart(broker, *, admission=True):
    return DrainCoordinator(broker.root, broker.host, owner=os.geteuid(),
                            admission=broker.admission if admission else None)


def prepare(broker):
    return broker.prepare(RID, '测试原数据库绑定维护')


def test_original_db_and_open_generation_bound_before_any_commands(env, gate, broker):
    first = prepare(broker)
    raw = broker._load(RID)
    assert raw['version'] == 2 and raw['plan']['admission'] == broker.admission.prepare()
    assert raw['plan']['admission']['server_uuid'] == read(env[2], 'SELECT @@server_uuid AS u')[0]['u']
    assert raw['plan']['admission']['gate'] == gate.read()
    assert restart(broker).prepare(RID, '测试原数据库绑定维护') == first
    assert not broker.host.calls and gate.read()['state'] == 'open'
    assert 'server_uuid' not in json.dumps(first) and 'password' not in json.dumps(first)


def test_actual_mysql_fence_precedes_every_synthetic_game_command(env, gate, broker):
    first = prepare(broker)
    original = broker.host.command
    def command(args, timeout=10):
        doc = broker._load(RID)
        assert [e['phase'] for e in doc['events'][:3]] == ['freeze-intent', 'write-gate-frozen', 'database-drained']
        assert doc['events'][2]['data']['server_uuid'] == read(env[2], 'SELECT @@server_uuid AS u')[0]['u']
        assert gate.read() == doc['events'][1]['data']
        assert doc['events'][2]['data']['maintenance_permit'] is False
        return original(args, timeout)
    broker.host.command = command
    result = broker.confirm(RID, first['fingerprint'])
    assert result['state'] == 'game_drained' and result['revision'] == 12
    assert result['maintenance_permit'] is False and gate.read()['state'] == 'frozen'
    calls = copy.deepcopy(broker.host.calls)
    assert restart(broker).confirm(RID, first['fingerprint']) == result
    assert broker.host.calls == calls
    assert cera(env) == 1000


def cera(env):
    return read(env[2], 'SELECT cera FROM taiwan_billing.cash_cera WHERE account=900001')[0]['cera']


@pytest.mark.parametrize('finish', ['commit', 'rollback'])
def test_remote_transaction_after_file_lease_loss_prevents_all_game_commands(env, gate, broker, finish):
    first = prepare(broker)
    _, _, db, app = env
    held = db.factory()
    try:
        with held.cursor() as q:
            with app.state.service.write_gate.writer() as lease:
                lease.protect_transaction(q)
                q.execute('UPDATE taiwan_billing.cash_cera SET cera=1234 WHERE account=900001')
        # Deliberately retain remote transaction after its file lease disappears.
        result = broker.confirm(RID, first['fingerprint'])
        assert result['state'] == 'needs_review' and result['phase'] == 'write-gate-frozen'
        assert gate.read()['state'] == 'frozen' and not broker.host.calls
        getattr(held, finish)()
        assert cera(env) == (1234 if finish == 'commit' else 1000)
        assert restart(broker).confirm(RID, first['fingerprint']) == result
        assert not broker.host.calls  # No automatic replay after the timeout.
    finally:
        held.close()


def test_changed_database_before_freeze_does_not_use_a_new_plan(env, gate, broker, monkeypatch):
    first = prepare(broker)
    original = broker.admission.prepare
    def changed():
        result = original()
        result['server_uuid'] = '12345678-1234-1234-1234-123456789abc'
        return result
    monkeypatch.setattr(broker.admission, 'prepare', changed)
    result = broker.confirm(RID, first['fingerprint'])
    assert result['state'] == 'needs_review' and result['error'] == 'maintenance_admission_changed'
    assert gate.read()['state'] == 'open' and not broker.host.calls


def test_changed_generation_before_freeze_never_overwrites_newer_gate(env, gate, broker):
    first = prepare(broker)
    token = gate.freeze('e' * 32, broker.host.identity())
    # Synthetic restoration proof for a separate test-only request.
    gate.release(token, lambda: True)
    original = gate.read()
    result = broker.confirm(RID, first['fingerprint'])
    assert result['error'] == 'maintenance_admission_changed'
    assert gate.read() == original and not broker.host.calls


@pytest.mark.parametrize('damage', ['protocol', 'row', 'engine'])
def test_db_protocol_damage_after_preview_cannot_advance_to_drain(env, gate, broker, damage):
    first = prepare(broker)
    write(env[2], {'protocol': 'UPDATE dnf_gm.gameplay_fence SET protocol_version=5',
                  'row': 'DELETE FROM dnf_gm.gameplay_fence',
                  'engine': 'ALTER TABLE dnf_gm.gameplay_fence ENGINE=MyISAM'}[damage])
    result = broker.confirm(RID, first['fingerprint'])
    assert result['state'] == 'needs_review' and not broker.host.calls
    assert gate.read()['state'] == 'open'


def test_freeze_intent_persists_before_freeze_and_crash_never_replays(env, gate, broker):
    first = prepare(broker)
    original = broker.admission.freeze
    def crash(*args):
        assert broker._load(RID)['events'][-1]['phase'] == 'freeze-intent'
        token = original(*args)
        assert gate.read() == token
        raise SystemExit('synthetic process death after freeze')
    broker.admission.freeze = crash
    with pytest.raises(SystemExit):
        broker.confirm(RID, first['fingerprint'])
    assert gate.read()['state'] == 'frozen' and not broker.host.calls
    restarted = restart(broker)
    assert restarted.confirm(RID, first['fingerprint'])['state'] == 'running'
    assert not broker.host.calls


def test_failed_durable_database_proof_does_not_send_game_commands(env, gate, broker):
    first = prepare(broker)
    writer = broker.writer
    def fail(path, data, mode):
        if data.get('events') and data['events'][-1]['phase'] == 'database-drained':
            raise OSError('synthetic receipt failure')
        writer(path, data, mode=mode)
    broker.writer = fail
    result = broker.confirm(RID, first['fingerprint'])
    assert result['state'] == 'needs_review' and result['phase'] == 'write-gate-frozen'
    assert gate.read()['state'] == 'frozen' and not broker.host.calls


def test_freeze_preserves_prior_success_and_refuses_new_game_write(env, gate, broker):
    c, _, _, _ = env
    old_op = preview(c).json()['operation_id']
    assert confirm(c, old_op).status_code == 200
    first = prepare(broker)
    assert broker.confirm(RID, first['fingerprint'])['state'] == 'game_drained'
    assert c.get(P + '/operations/' + old_op).json()['status'] == 'committed'
    assert confirm(c, old_op).status_code == 200
    assert cera(env) == 1100
    # Preview may itself be refused while frozen; neither path sends a write.
    new = preview(c)
    if new.status_code == 200:
        assert confirm(c, new.json()['operation_id'], 'new-key-after-freeze').status_code == 409
    else:
        assert new.status_code == 409
    assert cera(env) == 1100


def test_no_admission_is_readonly_and_cannot_prepare_or_confirm(env, gate, broker):
    observer = restart(broker, admission=False)
    with pytest.raises(Refused, match='admission_required'):
        observer.prepare(RID, '不允许缺失数据库绑定')
    first = prepare(broker)
    assert observer.status(RID)['state'] == 'prepared'
    with pytest.raises(Refused, match='admission_required'):
        observer.confirm(RID, first['fingerprint'])
    assert not broker.host.calls and gate.read()['state'] == 'open'


def test_original_legacy_preview_is_readable_cancelable_but_not_executable(env, gate, broker):
    first = prepare(broker)
    doc = broker._load(RID)
    doc['version'] = 1
    doc['plan'].pop('admission')
    doc['plan'].pop('fingerprint')
    doc['plan']['fingerprint'] = digest(doc['plan'])
    doc['binding'] = digest({k: doc[k] for k in ('request_id', 'reason', 'plan', 'created_at', 'created_monotonic')})
    atomic_json(broker.root / (RID + '.json'), doc, mode=0o600)
    assert restart(broker).status(RID)['can_confirm'] is False
    with pytest.raises(Refused, match='admission_required'):
        broker.confirm(RID, doc['plan']['fingerprint'])
    assert broker.cancel(RID)['state'] == 'cancelled' and not broker.host.calls
