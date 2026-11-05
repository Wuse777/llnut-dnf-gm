import json
from pathlib import Path
import time
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from dnfgm.app import create_app
from dnfgm.capability_policy import SWITCHES

P='/dnf-gm/api/v1'


def update(c,**kw):
    data={'request_id':uuid.uuid4().hex,'expected_revision':0,'enabled':list(SWITCHES),'reason':'专用环境管理员权限测试',**kw}
    return c.post(P+'/capabilities/policy',json=data),data


def test_report_is_admin_only_and_does_not_expose_secrets(env):
    c,s,db,app=env
    d=c.get(P+'/capabilities');assert d.status_code==200,d.text
    assert d.json()['policy']['state']=='legacy'
    assert d.json()['application']['version']=='0.3.1'
    for secret in (s.secret,s.db_password,s.status_file,s.catalog_file):assert secret not in d.text
    assert all(i['verification']['state']=='not_recorded' for i in d.json()['items'])
    c.cookies.clear();assert c.get(P+'/capabilities').status_code==401


def test_owner_can_enable_all_and_remove_test_uid_restriction_without_restart(env):
    c,s,db,app=env;r,body=update(c);assert r.status_code==200,r.text
    assert set(r.json()['enabled'])==set(SWITCHES)
    effective=app.state.settings
    assert effective.test_uids==() and effective.batch_worker_enabled and effective.schedule_worker_enabled
    assert effective.native_control_actions==('native-notice','native-kick')
    assert 'item-edit' in effective.writes
    d=c.get(P+'/capabilities').json();assert d['policy']['account_scope']=='all'
    assert not d['scope']['test_only'] and d['policy']['revision']==1
    # The retained low-level base file is intentionally not rewritten.
    assert s.test_uids==(900001,)
    with db.connect() as conn,conn.cursor() as q:
        q.execute("SELECT COUNT(*) n FROM dnf_gm.audit WHERE action='capability-policy'");assert q.fetchone()['n']==1
        q.execute('SELECT COUNT(*) n FROM dnf_gm.operations');assert q.fetchone()['n']==0
    # Real game write preview for an account outside the former test list.
    with db.connect() as conn,conn.cursor() as q:
        q.execute("INSERT INTO taiwan_billing.cash_cera VALUES('900002',10,0,NOW(),NOW())");conn.commit()
    p=c.post(P+'/operations/preview',json={'action':'currency','uid':900002,'currency':'cera','delta':1,'reason':'非原测试名单权限检查'})
    assert p.status_code==200,p.text


def test_idempotency_conflict_and_result_readback(env):
    c,s,db,app=env;r,body=update(c,enabled=['mail']);assert r.status_code==200
    assert c.post(P+'/capabilities/policy',json=body).json()==r.json()
    assert c.post(P+'/capabilities/policy',json={**body,'enabled':['currency']}).status_code==409
    assert update(c,enabled=[])[0].status_code==409
    assert c.get(P+'/capabilities/policy/requests/'+body['request_id']).json()==r.json()
    assert c.get(P+'/capabilities/policy/requests/'+'a'*32).status_code==404


def test_disable_and_reenable_updates_existing_services(env):
    c,s,db,app=env
    assert update(c,enabled=[])[0].status_code==200
    assert not app.state.service.settings.writes
    assert update(c,expected_revision=1,enabled=['currency'])[0].status_code==200
    assert app.state.service.settings.writes==('currency',)
    assert not app.state.settings.native_monitor_enabled


def test_restart_loads_same_policy_not_legacy_file(env):
    c,s,db,app=env;assert update(c,enabled=['mail','native-kick'])[0].status_code==200
    restarted=create_app(s,db)
    assert restarted.state.settings.writes==('mail',)
    assert restarted.state.settings.native_monitor_enabled
    assert restarted.state.capability_policy.view()['revision']==1


def test_no_unknown_switches_or_duplicates_or_empty_reason(env):
    c,s,db,app=env
    for data in ({'enabled':['shell']},{'enabled':['mail','mail']},{'reason':'  '},{'expected_revision':True}):
        assert update(c,**data)[0].status_code==422
    assert app.state.capability_policy.view()['revision']==0


def test_csrf_origin_and_recent_auth_required(env):
    c,s,db,app=env
    body={'request_id':uuid.uuid4().hex,'expected_revision':0,'enabled':list(SWITCHES),'reason':'fixture'}
    assert c.post(P+'/capabilities/policy',headers={'X-CSRF-Token':'wrong'},json=body).status_code==403
    assert c.post(P+'/capabilities/policy',headers={'Origin':'https://evil.invalid'},json=body).status_code==403
    with db.connect() as conn,conn.cursor() as q:
        q.execute('UPDATE dnf_gm.sessions SET authenticated_at=0');conn.commit()
    assert c.post(P+'/capabilities/policy',json=body).status_code==403


def test_missing_snapshot_never_claims_writes_are_usable(env):
    c,s,db,app=env;update(c);Path(s.status_file).unlink()
    d=c.get(P+'/capabilities').json();entry=next(i for i in d['items'] if i['id']=='mail')
    assert entry['enabled'] is True and entry['state']=='attention'
    assert 'snapshot_unknown' in [x['code'] for x in entry['checks']]
    assert entry['verification']['state']=='not_recorded'


def test_policy_query_failure_revokes_writes_not_login_or_receipt_history(env):
    c,s,db,app=env;update(c)
    with patch.object(app.state.capability_policy.db,'connect',side_effect=RuntimeError('private connection string')):
        app.state.capability_policy.refresh(force=True)
    assert app.state.capability_policy.state=='unknown' and not app.state.settings.writes
    assert c.get(P+'/auth/me').status_code==200
    app.state.capability_policy.refresh(force=True);assert 'mail' in app.state.settings.writes


def test_policy_audit_failure_rolls_back_everything(env):
    c,s,db,app=env
    with db.connect() as conn,conn.cursor() as q:
        q.execute("CREATE TRIGGER dnf_gm.reject_capability_audit BEFORE INSERT ON dnf_gm.audit FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic failure'");conn.commit()
    r,body=update(c);assert r.status_code==500
    with db.connect() as conn,conn.cursor() as q:
        q.execute('SELECT revision FROM dnf_gm.capability_policy');assert q.fetchone()['revision']==0
        q.execute('SELECT COUNT(*) n FROM dnf_gm.capability_requests');assert q.fetchone()['n']==0
    assert c.get(P+'/capabilities/policy/requests/'+body['request_id']).status_code==404


def test_read_only_policy_overview_and_write_grants_for_dedicated_user(env):
    import importlib.util, os, pymysql
    from dnfgm.db import Database
    from dnfgm.capability_policy import CapabilityPolicy, RuntimeSettings
    spec=importlib.util.spec_from_file_location('capability_grants',Path(__file__).parents[2]/'deploy/grants.py')
    g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
    c,s,root,app=env
    with root.connect() as conn,conn.cursor() as q:
        q.execute("DROP USER IF EXISTS 'capability_fixture'@'localhost'")
        q.execute("CREATE USER 'capability_fixture'@'localhost' IDENTIFIED BY 'fixture-password'")
        sql=g.capability_policy_sql("'capability_fixture'@'localhost'")+"GRANT SELECT,INSERT ON dnf_gm.audit TO 'capability_fixture'@'localhost';"
        for statement in sql.split(';'):
            if statement.strip():q.execute(statement)
        conn.commit()
    def factory():return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'],user='capability_fixture',password='fixture-password',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    policy=CapabilityPolicy(Database(s,factory),RuntimeSettings(s));policy.refresh(force=True)
    assert policy.view()['revision']==0
    result=policy.update({'request_id':uuid.uuid4().hex,'expected_revision':0,'enabled':list(SWITCHES),'reason':'fixture minimal rights'})
    assert result['revision']==1
    with policy.db.connect() as conn,conn.cursor() as q:
        for sql in ('DELETE FROM dnf_gm.capability_requests','UPDATE dnf_gm.capability_requests SET fingerprint="x"','SELECT password FROM d_taiwan.accounts','DROP TABLE dnf_gm.capability_policy'):
            with pytest.raises(pymysql.OperationalError):q.execute(sql)


def test_installation_initializer_opens_all_once_preserves_later_choices(env):
    import importlib.util
    spec=importlib.util.spec_from_file_location('capability_grants_init',Path(__file__).parents[2]/'deploy/grants.py')
    g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
    c,s,db,app=env
    def install():
        with db.connect() as conn,conn.cursor() as q:
            for sql in g.initialize_owner_capabilities_sql().split(';'):
                if sql.strip():q.execute(sql)
            conn.commit()
    install();app.state.capability_policy.refresh(force=True)
    assert set(app.state.capability_policy.view()['enabled'])==set(SWITCHES)
    assert update(c,expected_revision=1,enabled=['mail'])[0].status_code==200
    install();app.state.capability_policy.refresh(force=True)
    assert app.state.settings.writes==('mail',)
    assert app.state.capability_policy.view()['revision']==2


def test_concurrent_same_request_has_one_revision_and_one_audit(env):
    from concurrent.futures import ThreadPoolExecutor
    from dnfgm.capability_policy import CapabilityPolicy,RuntimeSettings
    c,s,db,app=env
    body={'request_id':uuid.uuid4().hex,'expected_revision':0,'enabled':['mail'],'reason':'concurrent fixture'}
    managers=[CapabilityPolicy(db,RuntimeSettings(s)),CapabilityPolicy(db,RuntimeSettings(s))]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda m:m.update(body),managers))
    assert results[0]==results[1] and results[0]['revision']==1
    assert all(m.settings.writes==('mail',) for m in managers)
    with db.connect() as conn,conn.cursor() as q:
        q.execute("SELECT COUNT(*) n FROM dnf_gm.audit WHERE action='capability-policy'");assert q.fetchone()['n']==1


def test_lost_response_receipt_survives_new_app_and_is_not_reapplied(env):
    c,s,db,app=env;r,body=update(c);assert r.status_code==200
    new=create_app(s,db)
    assert new.state.capability_policy.receipt(body['request_id'])==r.json()
    assert new.state.capability_policy.update(body)==r.json()
    assert new.state.capability_policy.view()['revision']==1


def test_rollback_refuses_live_web_permission_policy(env,tmp_path):
    import importlib.util
    c,s,db,app=env;update(c)
    spec=importlib.util.spec_from_file_location('rollback_capability_guard',Path(__file__).parents[2]/'deploy/check_rollback.py')
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    with db.connect() as conn,conn.cursor() as q:
        with pytest.raises(guard.IncompatibleRollback,match='web-managed'):guard.check(q,tmp_path)
    (tmp_path/'deploy').mkdir();(tmp_path/'deploy/release-features.json').write_text('{"schema_version":1,"reward_target_modes":["accounts"],"web_capability_policy":1,"maintenance_requests":1}')
    with db.connect() as conn,conn.cursor() as q:guard.check(q,tmp_path)


def test_audit_operation_lookup_resolves_policy_receipt_without_game_confirm(env):
    c,s,db,app=env;r,body=update(c,enabled=['mail'])
    rid=body['request_id']
    result=c.get(P+'/operations/'+rid)
    assert result.status_code==200,result.text
    record=result.json()
    assert record['action']=='capability-policy' and record['status']=='committed'
    assert record['request']['reason']==body['reason']
    assert record['result']==r.json() and record['preview'] is None
    assert c.post(P+'/operations/'+rid+'/confirm',json={'idempotency_key':uuid.uuid4().hex}).status_code==404
    assert c.get(P+'/operations/'+uuid.uuid4().hex).status_code==404
    c.cookies.clear()
    assert c.get(P+'/operations/'+rid).status_code==401
