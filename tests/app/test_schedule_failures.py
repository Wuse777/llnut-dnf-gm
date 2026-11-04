"""Scheduling recovery under real MySQL transaction failures and minimal grants."""
import importlib.util
import json
import os
from contextlib import contextmanager
from pathlib import Path

import pymysql
import pytest
from fastapi.testclient import TestClient

from dnfgm.app import create_app
from dnfgm.db import Database
from dnfgm.security import PASSWORDS
from dnfgm.schedules import Schedules
from test_combined_rewards import read, write
from test_schedules import scheduled, preview, activate, trigger, CommitLoss, P


@pytest.mark.parametrize('persisted', [False, True])
def test_reward_occurrence_unknown_commit_atomic_and_restart(scheduled, monkeypatch, persisted):
    client, s, db, app, engine, now = scheduled
    plan = preview(scheduled)
    assert activate(client, plan).status_code == 200
    now[0] = plan['request']['first_due']
    real = db.connect
    @contextmanager
    def lost():
        with real() as c: yield CommitLoss(c, persisted)
    with monkeypatch.context() as m:
        m.setattr(db, 'connect', lost)
        engine.step()
    runs = engine.runs(plan['id'])['items']
    jobs = read(db, 'SELECT * FROM dnf_gm.reward_jobs')
    assert len(runs) == len(jobs) == int(persisted)
    restarted = Schedules(db, s, app.state.reward_jobs, app.state.native_operations, lambda: now[0])
    restarted.step()
    assert len(restarted.runs(plan['id'])['items']) == 1
    assert len(read(db, 'SELECT * FROM dnf_gm.reward_jobs')) == 1
    for _ in range(2): app.state.reward_jobs.step()
    now[0] += 5; restarted.step()
    assert read(db, 'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera'] == 1100
    assert restarted.detail(plan['id'])['status'] == 'completed'


def test_activation_response_lost_does_not_require_another_plan(scheduled, monkeypatch):
    client, s, db, app, engine, now = scheduled
    plan = preview(scheduled)
    real = db.connect
    @contextmanager
    def lost():
        with real() as c: yield CommitLoss(c, True)
    # Exercise service directly so auth/session maintenance is not the fault target.
    owner = read(db, 'SELECT session_hash FROM dnf_gm.schedules WHERE id=%s', (plan['id'],))[0]['session_hash']
    with monkeypatch.context() as m:
        m.setattr(db, 'connect', lost)
        with pytest.raises(Exception) as e:
            engine.activate(owner, plan['id'], {'fingerprint': plan['fingerprint'], 'idempotency_key': 'loss-key-00000001', 'acknowledge_recurring': False, 'acknowledge_repeat': False, 'all_server_confirmation': ''})
        assert e.value.status_code == 503
    assert engine.detail(plan['id'])['status'] == 'active'
    assert activate(client, plan, idempotency_key='loss-key-00000001').status_code == 200
    trigger(scheduled, plan)
    assert len(engine.runs(plan['id'])['items']) == 1


def test_trigger_audit_failure_leaves_no_orphan_reward(scheduled, monkeypatch):
    client, s, db, app, engine, now = scheduled
    plan = preview(scheduled)
    assert activate(client, plan).status_code == 200
    now[0] = plan['request']['first_due']
    with monkeypatch.context() as m:
        def broken(*args, **kw): raise RuntimeError('synthetic audit unavailable')
        m.setattr(engine, 'audit', broken)
        with pytest.raises(RuntimeError): engine.step()
    assert engine.detail(plan['id'])['next_due'] == now[0]
    for table in ('schedule_runs', 'reward_jobs', 'reward_targets'):
        assert not read(db, 'SELECT * FROM dnf_gm.' + table)
    engine.step()
    assert len(engine.runs(plan['id'])['items']) == 1


def test_recurring_failed_child_cannot_overlap_after_resume(scheduled):
    client, s, db, app, engine, now = scheduled
    plan = preview(scheduled, recurrence='daily')
    assert activate(client, plan, acknowledge_recurring=True).status_code == 200
    trigger(scheduled, plan)
    child = engine.runs(plan['id'])['items'][0]['reference_id']
    app.state.reward_jobs.control(child, 'pause')
    now[0] += 5; engine.step()
    assert engine.detail(plan['id'])['status'] == 'needs_attention'
    assert client.post(P + '/' + plan['id'] + '/control', json={'action': 'resume'}).status_code == 422
    assert client.post(P + '/' + plan['id'] + '/control', json={'action': 'resume', 'acknowledge_attention': True}).status_code == 200
    now[0] = plan['request']['first_due'] + 86400
    engine.step()
    assert len(read(db, 'SELECT * FROM dnf_gm.reward_jobs')) == 1
    assert engine.detail(plan['id'])['status'] == 'needs_attention'


def test_template_and_item_policy_changes_stop_scheduled_issue(scheduled):
    client, s, db, app, engine, now = scheduled
    reward = {'targets': {'mode': 'selected', 'charac_nos': [900001]}, 'reward': {'items': [{'id': 990002, 'quantity': 2147483647}]}, 'reason': 'quantity preserved'}
    plan = preview(scheduled, reward_job=reward)
    assert plan['preview']['binding']['reward']['rewards']['items'][0]['quantity'] == 2147483647
    assert activate(client, plan).status_code == 200
    # Replacing the immutable index is detected against the frozen snapshot.
    import sqlite3
    with sqlite3.connect(s.catalog_file) as c:
        c.execute("UPDATE items SET name='Changed version' WHERE id=990002")
    trigger(scheduled, plan)
    assert engine.detail(plan['id'])['status'] == 'needs_attention'
    assert not read(db, 'SELECT * FROM dnf_gm.reward_jobs')


def test_actual_minimum_grants_for_schedules(scheduled):
    client, s, root, app, engine, now = scheduled
    spec = importlib.util.spec_from_file_location('schedule_grants', Path(__file__).resolve().parents[2] / 'deploy/grants.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    text = module.bootstrap_sql({'db_user': 'schedule_minimal', 'db_password': 'isolated-fixture-password', 'db_account_host': 'localhost'}, PASSWORDS.hash('fixture-admin-password'))
    with root.connect() as c, c.cursor() as q:
        q.execute('DROP DATABASE dnf_gm'); q.execute("DROP USER IF EXISTS 'schedule_minimal'@'localhost'")
        for statement in text.split(';'):
            if statement.strip(): q.execute(statement)
        c.commit()
    def factory():
        return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'], user='schedule_minimal', password='isolated-fixture-password', charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor, autocommit=False)
    limited = Database(s, factory); application = create_app(s, limited)
    schedules = application.state.schedules; schedules.clock = lambda: now[0]
    # No context-manager lifespan: manually drive exactly one worker step.
    c = TestClient(application, raise_server_exceptions=False)
    try:
        c.headers['Origin'] = 'http://testserver'
        r = c.post('/dnf-gm/api/v1/auth/login', json={'username': 'admin', 'password': 'fixture-admin-password'})
        assert r.status_code == 200, r.text
        c.headers['X-CSRF-Token'] = r.json()['csrf']
        isolated = c, s, limited, application, schedules, now
        plan = preview(isolated)
        assert activate(c, plan).status_code == 200
        trigger(isolated, plan)
        for _ in range(2): application.state.reward_jobs.step()
        now[0] += 5; schedules.step()
        assert schedules.detail(plan['id'])['status'] == 'completed'
        assert c.get('/dnf-gm/api/v1/health').status_code == 200
        for statement in ('DELETE FROM dnf_gm.schedules', 'DELETE FROM dnf_gm.schedule_runs', 'DELETE FROM dnf_gm.audit', 'DROP TABLE dnf_gm.schedule_runs', 'UPDATE taiwan_cain.charac_info SET lev=1'):
            with limited.connect() as conn, conn.cursor() as q:
                with pytest.raises(pymysql.OperationalError): q.execute(statement)
    finally:
        c.close()


def test_catalog_changes_during_freeze_rollback_child(scheduled, monkeypatch):
    client, s, db, app, engine, now = scheduled
    plan = preview(scheduled, reward_job={'targets': {'mode': 'selected', 'charac_nos': [900001]}, 'reward': {'items': [{'id': 990002, 'quantity': 2}]}, 'reason': 'TOCTOU fixture'})
    assert activate(client, plan).status_code == 200
    original = app.state.reward_jobs.create_in_transaction
    def changed(*args, **kw):
        import sqlite3
        with sqlite3.connect(s.catalog_file) as c:
            c.execute("UPDATE items SET name='Changed during target freeze' WHERE id=990002")
        return original(*args, **kw)
    monkeypatch.setattr(app.state.reward_jobs, 'create_in_transaction', changed)
    trigger(scheduled, plan)
    assert engine.detail(plan['id'])['status'] == 'needs_attention'
    assert not read(db, 'SELECT * FROM dnf_gm.reward_jobs')
    assert not read(db, 'SELECT * FROM dnf_gm.reward_targets')


def test_pause_does_not_bypass_attention_ack(scheduled):
    client, s, db, app, engine, now = scheduled
    plan = preview(scheduled, recurrence='daily')
    assert activate(client, plan, acknowledge_recurring=True).status_code == 200
    s.batch_worker_enabled = False
    trigger(scheduled, plan)
    s.batch_worker_enabled = True
    assert engine.control(plan['id'], 'pause')['status'] == 'paused'
    r = client.post(P + '/' + plan['id'] + '/control', json={'action': 'resume'})
    assert r.status_code == 422


def test_empty_dynamic_audience_skips_without_pausing_future_periods(scheduled):
    client, s, db, app, engine, now = scheduled
    plan = preview(scheduled, recurrence='daily', reward_job={'targets': {'mode': 'online'}, 'reward': {'currency_rewards': {'cera': 1}}, 'reason': 'no online players'})
    assert activate(client, plan, acknowledge_recurring=True).status_code == 200
    write(db, 'UPDATE taiwan_login.login_account_3 SET login_status=0')
    trigger(scheduled, plan)
    assert engine.detail(plan['id'])['status'] == 'active'
    run = engine.runs(plan['id'])['items'][0]
    assert run['status'] == 'skipped' and run['skipped_count'] == 1
    assert not read(db, 'SELECT * FROM dnf_gm.reward_jobs')
    write(db, 'UPDATE taiwan_login.login_account_3 SET login_status=1')
    now[0] += 86400; engine.step()
    assert len(read(db, 'SELECT * FROM dnf_gm.reward_jobs')) == 1


def test_last_missed_period_does_not_hide_running_child(scheduled):
    client, s, db, app, engine, now = scheduled
    plan = preview(scheduled, recurrence='daily', end_at=now[0] + 120 + 86400)
    assert activate(client, plan, acknowledge_recurring=True).status_code == 200
    trigger(scheduled, plan)
    now[0] += 86400 + 301
    engine.step()
    assert engine.detail(plan['id'])['status'] == 'active'
    for _ in range(2): app.state.reward_jobs.step()
    now[0] += 5; engine.step()
    assert engine.detail(plan['id'])['status'] == 'completed'
    audit = read(db, "SELECT actor,request_json FROM dnf_gm.audit WHERE action='reward'")[0]
    assert audit['actor'] == 'scheduler'
    assert json.loads(audit['request_json'])['schedule_id'] == plan['id']
