"""Isolated MySQL schedules: due-time recipients, atomic children, no UDP replay."""
import copy
import json
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from dnfgm.schedules import Schedules, OperationsWorker, missed, next_due
from test_combined_rewards import enable, read, write
from test_native_control_api import control  # explicitly reuse private synthetic transport fixture
from test_reward_jobs import extra_role

P = '/dnf-gm/api/v1/schedules'


@pytest.fixture
def scheduled(env):
    client, s, db, app = env
    enable(s)
    s.schedule_worker_enabled = True
    engine = app.state.schedules
    now = [int(time.time())]
    engine.clock = lambda: now[0]
    return client, s, db, app, engine, now


def definition(now, **kw):
    data = {'title': '北京时间奖励测试', 'kind': 'reward', 'first_due': now + 120,
            'reward_job': {'targets': {'mode': 'selected', 'charac_nos': [900001]},
                           'reward': {'currency_rewards': {'cera': 100}, 'gold': 123}, 'reason': '隔离环境'}}
    data.update(kw)
    return data


def preview(fixture, **kw):
    c, _, _, _, _, now = fixture
    r = c.post(P + '/preview', json=definition(now[0], **kw))
    assert r.status_code == 200, r.text
    return r.json()


def activate(c, item, **kw):
    data = {'fingerprint': item['fingerprint'], 'idempotency_key': 'schedule-test-' + item['id']}
    data.update(kw)
    return c.post(P + '/' + item['id'] + '/activate', json=data)


def trigger(fixture, item):
    *_, engine, now = fixture
    now[0] = item['request']['first_due']
    assert engine.step()


def test_rewards_freeze_at_actual_due_and_account_dedup(scheduled):
    c, s, db, app, engine, now = scheduled
    item = preview(scheduled, reward_job={'targets': {'mode': 'online'}, 'reward': {'currency_rewards': {'cera': 100}, 'gold': 123}, 'reason': 'due snapshot'})
    assert item['preview']['estimate'] == {'target_count': 1, 'account_count': 1}
    assert not read(db, 'SELECT * FROM dnf_gm.reward_jobs')
    assert activate(c, item).status_code == 200
    extra_role(db)  # created AFTER plan activation, but BEFORE actual trigger
    trigger(scheduled, item)
    runs = engine.runs(item['id'])['items']
    assert len(runs) == 1 and runs[0]['status'] == 'running'
    job = app.state.reward_jobs.detail(runs[0]['reference_id'])
    assert job['target_count'] == 2 and job['account_count'] == 1
    assert not read(db, 'SELECT * FROM taiwan_cain_2nd.postal')
    for _ in range(3):
        app.state.reward_jobs.step()
    now[0] += 5
    engine.step()
    assert engine.detail(item['id'])['status'] == 'completed'
    assert engine.runs(item['id'])['items'][0]['status'] == 'finished'
    assert read(db, 'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera'] == 1100
    assert len(read(db, 'SELECT * FROM taiwan_cain_2nd.postal')) == 2
    assert not engine.step()
    assert activate(c, item).status_code == 200
    assert len(read(db, 'SELECT * FROM dnf_gm.reward_jobs')) == 1


def test_pause_cancel_do_not_cancel_authorized_child(scheduled):
    c, s, db, app, engine, now = scheduled
    item = preview(scheduled, recurrence='daily')
    assert activate(c, item).status_code == 422
    assert activate(c, item, acknowledge_recurring=True).status_code == 200
    assert c.post(P + '/' + item['id'] + '/control', json={'action': 'pause'}).json()['status'] == 'paused'
    now[0] = item['request']['first_due']
    assert not engine.step()
    assert c.post(P + '/' + item['id'] + '/control', json={'action': 'resume'}).status_code == 200
    engine.step()
    assert c.post(P + '/' + item['id'] + '/control', json={'action': 'cancel'}).status_code == 200
    for _ in range(2): app.state.reward_jobs.step()
    now[0] += 5; engine.step()
    assert engine.detail(item['id'])['status'] == 'cancelled'
    assert engine.runs(item['id'])['items'][0]['status'] == 'finished'
    assert c.post(P + '/' + item['id'] + '/control', json={'action': 'resume'}).status_code == 409


def test_long_downtime_aggregated_no_catchup_and_end_boundary(scheduled):
    c, s, db, app, engine, now = scheduled
    item = preview(scheduled, recurrence='daily', end_at=now[0] + 120 + 86400 * 9)
    assert activate(c, item, acknowledge_recurring=True).status_code == 200
    now[0] += 86400 * 1000
    assert engine.step()
    runs = engine.runs(item['id'])['items']
    assert len(runs) == 1 and runs[0]['skipped_count'] == 10
    assert runs[0]['last_due_at'] == item['request']['end_at']
    assert engine.detail(item['id'])['status'] == 'completed'
    assert not read(db, 'SELECT * FROM dnf_gm.reward_jobs')


def test_late_boundary_and_weekly_arithmetic():
    data = {'recurrence': 'weekly', 'end_at': None}
    assert next_due(data, 100) == 604900
    count, last, nxt = missed(data, 100, 100 + 604800 * 100 + 301)
    assert count == 101 and last == 60480100 and nxt == 61084900
    assert next_due({'recurrence': 'once'}, 100) is None
    assert next_due({'recurrence': 'daily', 'end_at': 86500}, 100) == 86500
    assert next_due({'recurrence': 'daily', 'end_at': 86499}, 100) is None


@pytest.mark.parametrize('delay,expected', [(300, 'running'), (301, 'skipped')])
def test_late_window(scheduled, delay, expected):
    c, s, db, app, engine, now = scheduled
    item = preview(scheduled)
    assert activate(c, item).status_code == 200
    now[0] = item['request']['first_due'] + delay
    engine.step()
    assert engine.runs(item['id'])['items'][0]['status'] == expected


@pytest.mark.parametrize('change', ['no_targets', 'test_scope', 'pvf', 'resource', 'worker', 'deleted'])
def test_due_rechecks_roll_back_entire_child(scheduled, change):
    c, s, db, app, engine, now = scheduled
    item = preview(scheduled)
    assert activate(c, item).status_code == 200
    if change == 'no_targets': write(db, 'UPDATE taiwan_cain.charac_info SET delete_flag=1')
    if change == 'deleted': write(db, 'DELETE FROM d_taiwan.accounts WHERE UID=900001')
    if change == 'test_scope': s.test_uids = (900002,)
    if change == 'pvf': s.pvf_sha256 = 'b' * 64
    if change == 'worker': s.batch_worker_enabled = False
    if change == 'resource':
        from pathlib import Path
        p = Path(s.status_file); status = json.loads(p.read_text()); status['mem_available_mib'] = 1; p.write_text(json.dumps(status))
    trigger(scheduled, item)
    assert engine.detail(item['id'])['status'] == 'needs_attention'
    assert engine.runs(item['id'])['items'][0]['status'] == 'needs_attention'
    assert not read(db, 'SELECT * FROM dnf_gm.reward_jobs')
    assert not read(db, 'SELECT * FROM dnf_gm.reward_targets')
    assert not read(db, 'SELECT * FROM taiwan_cain_2nd.postal')
    assert not engine.step()


def test_concurrent_due_only_one_child(scheduled):
    c, s, db, app, engine, now = scheduled
    item = preview(scheduled)
    assert activate(c, item).status_code == 200
    now[0] = item['request']['first_due']
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: engine.step(), range(2)))
    assert len(engine.runs(item['id'])['items']) == 1
    assert len(read(db, 'SELECT * FROM dnf_gm.reward_jobs')) == 1


def test_previous_child_blocks_next_occurrence(scheduled):
    c, s, db, app, engine, now = scheduled
    item = preview(scheduled, recurrence='daily')
    assert activate(c, item, acknowledge_recurring=True).status_code == 200
    trigger(scheduled, item)
    now[0] += 86400
    engine.step()
    assert engine.detail(item['id'])['status'] == 'needs_attention'
    assert len(read(db, 'SELECT * FROM dnf_gm.reward_jobs')) == 1
    assert len(engine.runs(item['id'])['items']) == 2


def test_activation_auth_origin_csrf_and_key_conflicts(scheduled):
    c, s, db, app, engine, now = scheduled
    item = preview(scheduled)
    assert activate(c, item, fingerprint='0' * 64).status_code == 409
    original = c.headers['X-CSRF-Token']; del c.headers['X-CSRF-Token']
    assert activate(c, item).status_code == 403
    c.headers['X-CSRF-Token'] = original
    assert c.post(P + '/' + item['id'] + '/activate', headers={'Origin': 'https://evil.invalid'}, json={'fingerprint': item['fingerprint'], 'idempotency_key': 'test-origin-00001'}).status_code == 403
    assert activate(c, item).status_code == 200
    assert activate(c, item, idempotency_key='changed-key-00001').status_code == 409
    second = preview(scheduled)
    assert activate(c, second, idempotency_key='schedule-test-' + item['id']).status_code == 409
    c.cookies.clear()
    assert c.get(P).status_code == 401


def test_full_server_and_repeat_ack(scheduled):
    c, s, db, app, engine, now = scheduled
    item = preview(scheduled, reward_job={'targets': {'mode': 'all'}, 'reward': {'currency_rewards': {'cera': 1}}, 'account_reward_mode': 'per_character', 'reason': 'all roles'})
    assert activate(c, item).status_code == 422
    assert activate(c, item, all_server_confirmation='全服发放').status_code == 422
    assert activate(c, item, all_server_confirmation='全服发放', acknowledge_repeat=True).status_code == 200
    trigger(scheduled, item)  # full list contains non-test account; cannot bypass test scope
    assert engine.detail(item['id'])['status'] == 'needs_attention'
    assert not read(db, 'SELECT * FROM dnf_gm.reward_jobs')


@pytest.mark.parametrize('payload', [
    {'first_due': 1}, {'title': '   '}, {'kind': 'notice'},
    {'recurrence': 'hourly'}, {'first_due': True},
    {'reward_job': {'targets': {'mode': 'selected', 'charac_nos': [900001]}, 'reward': {'currency_rewards': {'cera': 1}}, 'reason': '   '}},
    {'end_at': 1}, {'reward_job': {'targets': {'mode': 'selected'}, 'reward': {}, 'reason': ''}},
    {'kind': 'notice', 'reward_job': None, 'notice': {'action': 'native-kick', 'uid': 900001, 'reason': 'no'}}
])
def test_bad_definition(scheduled, payload):
    c, *_, now = scheduled
    assert c.post(P + '/preview', json=definition(now[0], **payload)).status_code == 422


def test_disabled_and_expired_activation(scheduled):
    c, s, db, app, engine, now = scheduled
    item = preview(scheduled)
    s.schedule_worker_enabled = False
    assert activate(c, item).status_code == 409
    now[0] = item['request']['first_due']
    assert not engine.step()
    s.schedule_worker_enabled = True
    assert activate(c, item).status_code == 409


def configure_notice(control):
    c, s, db, app, ops, sent = control
    s.test_uids = ()
    s.schedule_worker_enabled = True
    engine = app.state.schedules
    now = [int(time.time())]
    engine.clock = lambda: now[0]
    r = c.post(P + '/preview', json=definition(now[0], kind='notice', reward_job=None, notice={'action': 'native-notice', 'message': '测试公告', 'reason': '隔离报文'}))
    assert r.status_code == 200, r.text
    item = r.json()
    assert activate(c, item).status_code == 422
    assert activate(c, item, all_server_confirmation='全服公告').status_code == 200
    now[0] = item['request']['first_due']
    return engine, now, item


def test_scheduled_notice_reuses_at_most_once_transport(control):
    c, s, db, app, ops, sent = control
    engine, now, item = configure_notice(control)
    assert engine.step()
    assert sent == ['测试公告']
    runs = engine.runs(item['id'])['items']
    assert runs[0]['status'] == 'sent'
    child = ops.detail(runs[0]['reference_id'])
    assert child['result']['effect_status'] == 'unknown'
    assert engine.detail(item['id'])['status'] == 'completed'
    assert not engine.step()
    assert sent == ['测试公告']


class CommitLoss:
    def __init__(self, inner, persisted): self.inner, self.persisted = inner, persisted
    def __getattr__(self, key): return getattr(self.inner, key)
    def commit(self):
        if self.persisted: self.inner.commit()
        raise OSError('synthetic response loss')


@pytest.mark.parametrize('persisted', [False, True])
def test_notice_unknown_preparation_commit_never_sends(control, monkeypatch, persisted):
    c, s, db, app, ops, sent = control
    engine, now, item = configure_notice(control)
    real = db.connect
    @contextmanager
    def lost():
        with real() as conn: yield CommitLoss(conn, persisted)
    with monkeypatch.context() as m:
        m.setattr(db, 'connect', lost)
        assert engine.step()
    assert not sent
    runs = engine.runs(item['id'])['items']
    if persisted:
        assert len(runs) == 1
        now[0] += 61
        restarted = Schedules(db, s, app.state.reward_jobs, ops, lambda: now[0])
        restarted.step()
        assert restarted.detail(item['id'])['status'] == 'needs_attention'
        assert ops.detail(runs[0]['reference_id'])['status'] == 'cancelled'
        assert not sent
    else:
        assert not runs
        assert not read(db, 'SELECT * FROM dnf_gm.native_controls')


def test_notice_result_loss_recovered_without_resend(control, monkeypatch):
    c, s, db, app, ops, sent = control
    engine, now, item = configure_notice(control)
    real = engine.finish_run
    monkeypatch.setattr(engine, 'finish_run', lambda *a: (_ for _ in ()).throw(OSError('synthetic')))
    with pytest.raises(OSError): engine.step()
    assert len(sent) == 1
    monkeypatch.setattr(engine, 'finish_run', real)
    now[0] += 5
    engine.step()
    assert len(sent) == 1
    assert engine.detail(item['id'])['status'] == 'completed'


def test_cancel_during_native_send_does_not_reactivate(control):
    c, s, db, app, ops, sent = control
    engine, now, item = configure_notice(control)
    original = ops.transport.notice
    def send(value):
        engine.control(item['id'], 'cancel')
        return original(value)
    ops.transport.notice = send
    engine.step()
    assert engine.detail(item['id'])['status'] == 'cancelled'
    assert len(sent) == 1
    assert engine.runs(item['id'])['items'][0]['status'] == 'sent'


def test_single_worker_scheduler_error_does_not_starve_rewards(scheduled):
    _, s, _, app, engine, _ = scheduled
    called = []
    class Bad:
        def step(self): raise RuntimeError('synthetic')
    class Jobs:
        def step(self): called.append(True)
    driver = OperationsWorker(Bad(), Jobs(), s)
    driver.step(); driver.step()
    assert len(called) == 2
