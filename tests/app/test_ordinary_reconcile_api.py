"""Real MySQL 5.7 outcome reconciliation; all service commands are synthetic."""
import json

import pytest

from dnfgm.ordinary_reconcile import summary, validate_summary
from dnfgm.release_files import Refused
from test_maintenance_admission_api import broker, prepare, RID
from test_write_gate import gate
from test_reward_jobs import job_preview, start
from test_combined_rewards import enable, read, write
from test_native_control_api import control, preview as native_preview
from test_application import preview, confirm


def freeze(broker):
    plan = broker.admission.prepare()
    token = broker.admission.freeze(RID, broker.host.identity(), plan)
    return plan, token


def settle(broker, plan, token):
    return broker.admission.drain(plan, token)


def interrupted(env):
    c, s, db, app = env
    enable(s)
    job = job_preview(c)
    assert start(c, job).status_code == 200
    write(db, "UPDATE dnf_gm.reward_targets SET status='executing',attempts=1 WHERE job_id=%s", (job['id'],))
    return job, read(db, 'SELECT * FROM dnf_gm.reward_targets WHERE job_id=%s', (job['id'],))[0]


def test_frozen_preflight_resolves_uncommitted_batch_without_award(env, gate, broker):
    job, target = interrupted(env)
    plan, token = freeze(broker)
    proof = settle(broker, plan, token)
    assert proof['outcomes']['rewards_failed'] == 1
    assert proof['outcomes']['game_writes'] is False
    assert read(env[2], 'SELECT cera FROM taiwan_billing.cash_cera WHERE account=900001')[0]['cera'] == 1000
    assert read(env[2], 'SELECT status FROM dnf_gm.reward_jobs')[0]['status'] == 'paused'
    assert read(env[2], 'SELECT status FROM dnf_gm.reward_targets')[0]['status'] == 'failed'
    assert not env[3].state.reward_jobs.step()  # No implicit retry.
    assert not broker.host.calls
    assert gate.read() == token
    old = read(env[2], 'SELECT * FROM dnf_gm.audit')
    assert settle(broker, plan, token)['outcomes'] == proof['outcomes']
    assert read(env[2], 'SELECT * FROM dnf_gm.audit') == old


def test_committed_batch_response_loss_keeps_actual_credit(env, gate, broker):
    c, s, db, app = env
    enable(s)
    job = job_preview(c)
    assert start(c, job).status_code == 200
    assert app.state.reward_jobs.step()
    write(db, "UPDATE dnf_gm.reward_targets SET status='uncertain' WHERE job_id=%s", (job['id'],))
    original = read(db, "SELECT * FROM dnf_gm.audit WHERE action='reward'")
    plan, token = freeze(broker)
    assert settle(broker, plan, token)['outcomes']['rewards_committed'] == 1
    assert read(db, 'SELECT cera FROM taiwan_billing.cash_cera WHERE account=900001')[0]['cera'] == 1100
    assert read(db, "SELECT * FROM dnf_gm.audit WHERE action='reward'") == original
    assert read(db, 'SELECT status FROM dnf_gm.reward_targets')[0]['status'] == 'committed'


@pytest.mark.parametrize('damage', ['missing_audit', 'wrong_uid', 'wrong_result', 'wrong_action'])
def test_conflict_rolls_back_and_prevents_all_service_commands(env, gate, broker, damage):
    c, s, db, app = env
    enable(s)
    job = job_preview(c)
    assert start(c, job).status_code == 200
    app.state.reward_jobs.step()
    write(db, "UPDATE dnf_gm.reward_targets SET status='uncertain' WHERE job_id=%s", (job['id'],))
    write(db, {'missing_audit': "DELETE FROM dnf_gm.audit WHERE action='reward'",
        'wrong_uid': "UPDATE dnf_gm.audit SET target_uid=999 WHERE action='reward'",
        'wrong_result': "UPDATE dnf_gm.audit SET result_json='{}' WHERE action='reward'",
        'wrong_action': "UPDATE dnf_gm.operations SET action='mail' WHERE action='reward'"}[damage])
    prepared = prepare(broker)
    result = broker.confirm(RID, prepared['fingerprint'])
    assert result['state'] == 'needs_review'
    assert result['error'] == 'maintenance_outcome_conflict'
    assert not broker.host.calls and gate.read()['state'] == 'frozen'
    assert read(db, 'SELECT status FROM dnf_gm.reward_targets')[0]['status'] == 'uncertain'
    assert not read(db, "SELECT * FROM dnf_gm.audit WHERE action='maintenance-reconcile'")


def test_projection_without_atomic_success_is_not_called_failed(env, gate, broker):
    job, target = interrupted(env)
    write(env[2], 'INSERT INTO dnf_gm.economy_values(operation_id,metric,amount) VALUES(%s,%s,%s)', (target['operation_id'], 'cera', 100))
    plan, token = freeze(broker)
    with pytest.raises(Refused, match='outcome_conflict'): settle(broker, plan, token)
    assert read(env[2], 'SELECT status FROM dnf_gm.reward_targets')[0]['status'] == 'executing'


@pytest.mark.parametrize('kind', ['dispatching', 'uncertain'])
def test_native_uncertainty_preserved_without_sending_again(env, control, gate, broker, kind):
    ops = control[4]
    op = native_preview(control)
    session = read(env[2], 'SELECT session_hash FROM dnf_gm.operations WHERE operation_id=%s', (op,))[0]['session_hash']
    calls = []
    def send(data, operation_id=None):
        assert operation_id == op
        calls.append(data)
        if kind == 'dispatching': raise SystemExit('synthetic process exit')
        return {'transport_status': 'uncertain', 'effect_status': 'unknown', 'reason_code': 'test', 'automatic_retry_allowed': False}
    ops.send_once = send
    if kind == 'dispatching':
        with pytest.raises(SystemExit): ops.confirm(session, op, 'fixture-native-preflight-0001')
    else: ops.confirm(session, op, 'fixture-native-preflight-0001')
    before = read(env[2], 'SELECT * FROM dnf_gm.operations WHERE operation_id=%s', (op,))
    plan, token = freeze(broker)
    proof = settle(broker, plan, token)
    assert proof['outcomes']['native_uncertain'] == 1
    assert read(env[2], 'SELECT * FROM dnf_gm.operations WHERE operation_id=%s', (op,)) == before
    assert len(calls) == 1
    assert not broker.host.calls


def test_plain_currency_success_and_unused_preview_remain_unchanged(env, gate, broker):
    c, _, db, _ = env
    op = preview(c).json()['operation_id']
    assert confirm(c, op).status_code == 200
    preview(c)
    before = read(db, 'SELECT * FROM dnf_gm.operations ORDER BY operation_id')
    plan, token = freeze(broker)
    assert settle(broker, plan, token)['outcomes']['rewards_failed'] == 0
    assert read(db, 'SELECT * FROM dnf_gm.operations ORDER BY operation_id') == before


def test_index_migration_is_repeatable_and_wrong_index_refused(env, gate, broker):
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[2] / 'migrations/014-operation-outcomes.sql').read_text()
    for _ in range(2):
        with env[2].connect() as c, c.cursor() as q:
            for statement in sql.split(';'):
                if statement.strip(): q.execute(statement)
            c.commit()
    write(env[2], 'ALTER TABLE dnf_gm.operations DROP INDEX outcome_status, ADD INDEX outcome_status(created_at)')
    prepared = prepare(broker)
    result = broker.confirm(RID, prepared['fingerprint'])
    assert result['error'] == 'maintenance_outcome_index_unproven'
    assert not broker.host.calls


@pytest.mark.parametrize('damage', ['binding', 'summary'])
def test_lost_reply_reuses_only_matching_valid_audit(env, gate, broker, damage):
    plan, token = freeze(broker)
    settle(broker, plan, token)
    column = 'request_json' if damage == 'binding' else 'result_json'
    write(env[2], 'UPDATE dnf_gm.audit SET ' + column + "='{}' WHERE action='maintenance-reconcile'")
    with pytest.raises(Refused): settle(broker, plan, token)
    assert not broker.host.calls


def test_late_error_rolls_back_all_earlier_target_updates(env, gate, broker):
    job, target = interrupted(env)
    write(env[2], "INSERT INTO dnf_gm.reward_targets(job_id,ordinal,target_uid,charac_no,target_json,operation_id,status) VALUES(%s,999,900001,999,'{}',%s,'executing')", (job['id'], 'f'*32))
    write(env[2], "INSERT INTO dnf_gm.economy_values(operation_id,metric,amount) VALUES(%s,'cera',10)", ('f'*32,))
    plan, token = freeze(broker)
    with pytest.raises(Refused): settle(broker, plan, token)
    assert {r['status'] for r in read(env[2], 'SELECT status FROM dnf_gm.reward_targets')} == {'executing'}
    assert read(env[2], 'SELECT status FROM dnf_gm.reward_jobs')[0]['status'] == 'running'


def test_pending_budget_is_bounded_before_mutations(env, gate, broker):
    job, target = interrupted(env)
    with env[2].connect() as c, c.cursor() as q:
        for i in range(100):
            q.execute("INSERT INTO dnf_gm.reward_targets(job_id,ordinal,target_uid,charac_no,target_json,operation_id,status) VALUES(%s,%s,900001,%s,'{}',%s,'executing')", (job['id'], 1000+i, 1000+i, f'{i:032x}'))
        c.commit()
    plan, token = freeze(broker)
    with pytest.raises(Refused, match='pending_budget'): settle(broker, plan, token)
    assert {r['status'] for r in read(env[2], 'SELECT status FROM dnf_gm.reward_targets')} == {'executing'}


def test_actual_minimum_management_grants_can_reconcile_without_game_write_rights(env, gate, broker, lab):
    import pymysql
    from dnfgm.db import Database
    from maintenance_admission import MaintenanceAdmission
    from dnfgm.ordinary_reconcile import TABLES
    from grants import gameplay_fence_sql
    job, target = interrupted(env)
    user = "'gm_outcome_fixture'@'localhost'"
    write(env[2], 'DROP USER IF EXISTS ' + user)
    write(env[2], 'CREATE USER ' + user + " IDENTIFIED BY 'isolated-fixture-only'")
    try:
        with env[2].connect() as c, c.cursor() as q:
            for table in TABLES:
                rights = 'SELECT,INSERT,UPDATE' if table in ('reward_jobs','reward_targets','operations') else 'SELECT,INSERT'
                q.execute(f'GRANT {rights} ON dnf_gm.{table} TO ' + user)
            q.execute(gameplay_fence_sql(user)); c.commit()
        def factory():
            return pymysql.connect(unix_socket=str(lab.socket),user='gm_outcome_fixture',password='isolated-fixture-only',
                charset='utf8mb4',autocommit=False,cursorclass=pymysql.cursors.DictCursor,read_timeout=5,write_timeout=5)
        limited = Database(env[1], factory)
        admission = MaintenanceAdmission(gate, limited)
        plan = admission.prepare()
        token = admission.freeze(RID, broker.host.identity(), plan)
        assert admission.drain(plan, token)['outcomes']['rewards_failed'] == 1
        with limited.connect() as c, c.cursor() as q:
            with pytest.raises(pymysql.MySQLError): q.execute('UPDATE taiwan_billing.cash_cera SET cera=0')
    finally:
        write(env[2], 'DROP USER IF EXISTS ' + user)


def test_database_success_then_lost_commit_response_resolves_original_receipt(env, gate, broker, monkeypatch):
    from contextlib import contextmanager
    job, target = interrupted(env)
    plan, token = freeze(broker)
    original = env[2].connect
    @contextmanager
    def lost_reply():
        with original() as c:
            commit = c.commit
            def ambiguous():
                commit()
                raise OSError('synthetic reply loss after commit')
            c.commit = ambiguous
            yield c
    monkeypatch.setattr(env[2], 'connect', lost_reply)
    with pytest.raises(OSError): settle(broker, plan, token)
    monkeypatch.setattr(env[2], 'connect', original)
    assert gate.read() == token and not broker.host.calls
    proof = settle(broker, plan, token)
    assert proof['outcomes']['rewards_failed'] == 1
    assert len(read(env[2], "SELECT * FROM dnf_gm.audit WHERE action='maintenance-reconcile'")) == 1
    assert read(env[2], 'SELECT cera FROM taiwan_billing.cash_cera WHERE account=900001')[0]['cera'] == 1000


def test_public_drain_reports_only_counts_not_private_binding(env, gate, broker):
    interrupted(env)
    prepared = prepare(broker)
    result = broker.confirm(RID, prepared['fingerprint'])
    assert result['ordinary_outcomes'] == {'rewards_committed':0,'rewards_failed':1,'native_uncertain':0,
        'game_writes':False,'automatic_replay':False}
    serialized = json.dumps(result)
    for private in ('server_uuid','binding_sha256','maintenance-outcomes:','target_json'):
        assert private not in serialized


def test_unrecognized_persistent_intent_prevents_service_exit(env, gate, broker):
    op = preview(env[0]).json()['operation_id']
    write(env[2], "UPDATE dnf_gm.operations SET status='executing' WHERE operation_id=%s", (op,))
    prepared = prepare(broker)
    result = broker.confirm(RID, prepared['fingerprint'])
    assert result['error'] == 'maintenance_outcome_action_unproven'
    assert not broker.host.calls and gate.read()['state'] == 'frozen'


@pytest.mark.parametrize('damage', ['audit', 'index', 'target', 'claim_json'])
def test_unproven_native_claim_does_not_become_valid_unknown(env, control, gate, broker, damage):
    ops = control[4]; op = native_preview(control)
    session = read(env[2], 'SELECT session_hash FROM dnf_gm.operations WHERE operation_id=%s', (op,))[0]['session_hash']
    def crash(data, operation_id=None):
        assert operation_id == op
        raise SystemExit('fixture crash')
    ops.send_once = crash
    with pytest.raises(SystemExit): ops.confirm(session, op, 'fixture-native-preflight-0002')
    sql = {'audit':'DELETE FROM dnf_gm.audit WHERE operation_id=%s',
        'index':'DELETE FROM dnf_gm.native_controls WHERE operation_id=%s',
        'target':'UPDATE dnf_gm.audit SET target_uid=999 WHERE operation_id=%s',
        'claim_json':"UPDATE dnf_gm.audit SET result_json='{}' WHERE operation_id=%s"}[damage]
    write(env[2], sql, (op,))
    prepared = prepare(broker)
    result = broker.confirm(RID, prepared['fingerprint'])
    assert result['error'] == 'maintenance_outcome_native_conflict'
    assert not broker.host.calls


def test_root_binding_is_redacted_in_audit_page_and_export(env, gate, broker):
    interrupted(env)
    plan, token = freeze(broker)
    settle(broker, plan, token)
    private = read(env[2], "SELECT request_json FROM dnf_gm.audit WHERE action='maintenance-reconcile'")[0]['request_json']
    assert plan['server_uuid'] in private and token['binding_sha256'] in private
    for route in ('/dnf-gm/api/v1/audit', '/dnf-gm/api/v1/audit/export'):
        response = env[0].get(route)
        assert response.status_code == 200
        assert 'binding_redacted' in response.text and 'maintenance-reconcile' in response.text
        assert plan['server_uuid'] not in response.text and token['binding_sha256'] not in response.text
        assert 'server_uuid' not in response.text and 'binding_sha256' not in response.text
