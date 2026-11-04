import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException

from dnfgm.native_monitor import MONITOR_SHA256
from dnfgm.native_operations import NativeOperations

BASE = '/dnf-gm/api/v1/native-controls'
KEY = 'native-fixture-key-00001'


@pytest.fixture
def control(env):
    client, s, db, app = env
    s.native_monitor_enabled = True
    s.native_control_actions = ('native-notice', 'native-kick')
    s.write_approvals.update({'native-notice': True, 'native-kick': True})
    from pathlib import Path
    p = Path(s.status_file); status = json.loads(p.read_text()); status['native_monitor_sha256'] = MONITOR_SHA256
    p.write_text(json.dumps(status))
    ops = app.state.native_operations
    sent = []
    def send(value):
        # No retained business DB connection during a native side effect.
        assert db.slots._value == 3
        sent.append(value)
        return {'transport_status': 'sent', 'effect_status': 'unknown', 'reason_code': 'no_application_ack', 'automatic_retry_allowed': False}
    ops.transport.kick = send
    ops.transport.notice = send
    return client, s, db, app, ops, sent


def request(action='native-kick', **changes):
    return {'action': action, 'uid': None if action=='native-notice' else 900001,
            'message': '维护公告' if action=='native-notice' else '', 'reason': 'fixture-control', **changes}


def preview(control, action='native-kick', **changes):
    r = control[0].post(BASE+'/preview', json=request(action, **changes))
    assert r.status_code == 200, r.text
    return r.json()['operation_id']


def sql(db, query, args=()):
    with db.connect() as c, c.cursor() as q:
        q.execute(query, args)
        rows = q.fetchall() if q.description else []
        c.commit()
        return rows


@pytest.mark.parametrize('action', ['native-kick', 'native-notice', 'native-ban-kick'])
def test_preview_confirm_history_and_replay(control, action):
    client, s, db, app, ops, sent = control
    if action=='native-notice': s.test_uids=()
    op=preview(control, action)
    assert not sent
    r=client.post(f'{BASE}/{op}/confirm', json={'idempotency_key':KEY})
    assert r.status_code==200,r.text
    result=r.json()
    assert result['status']=='sent' and result['result']['effect_status']=='unknown'
    assert len(sent)==1
    again=client.post(f'{BASE}/{op}/confirm',json={'idempotency_key':KEY})
    assert again.json()==result and len(sent)==1
    assert client.get(BASE).json()['items'][0]['operation_id']==op
    assert client.get(f'{BASE}/{op}').json()==result
    rows=sql(db,'SELECT operation_id,result_json FROM dnf_gm.audit ORDER BY id')
    assert [r['operation_id'] for r in rows]==[op,'native-result:'+op]
    assert json.loads(rows[0]['result_json'])['stage']=='dispatch_claim'
    if action=='native-ban-kick':
        assert result['result']['ban_status']=='committed_login_test_pending'
        assert sql(db,'SELECT apply_flag FROM d_taiwan.member_punish_info WHERE m_id=900001')[0]['apply_flag']==1
        # Ordinary unban remains compatible with the ownership marker.
        p=client.post('/dnf-gm/api/v1/operations/preview',json={'action':'unban','uid':900001,'reason':'fixture-unban'}).json()
        r=client.post('/dnf-gm/api/v1/operations/'+p['operation_id']+'/confirm',json={'idempotency_key':'unban-native-fixture-key'})
        assert r.status_code==200,r.text


@pytest.mark.parametrize('change', [{'uid':True},{'uid':900002},{'uid':None},{'uid':2147483648},{'uid':900001,'message':'cannot chat'},
    {'reason':'   '},{'action':'raw'},{'opcode':1217},{'host':'8.8.8.8'}])
def test_invalid_input_or_test_target_has_no_side_effect(control, change):
    r=control[0].post(BASE+'/preview',json=request(**change))
    assert r.status_code in (409,422),r.text
    assert not control[-1]


def test_broadcast_cannot_hide_behind_test_uid(control):
    assert control[0].post(BASE+'/preview',json=request('native-notice')).status_code==409
    assert control[0].post(BASE+'/preview',json=request('native-notice',uid=900001)).status_code==422
    assert not control[-1]


def test_disabled_or_missing_account(control):
    client,s,db,app,ops,sent=control
    s.test_uids=()
    assert client.post(BASE+'/preview',json=request(uid=999999)).status_code==404
    s.native_control_actions=()
    assert client.post(BASE+'/preview',json=request()).status_code==409
    assert not sent


def test_idempotency_cross_operation_and_key_change(control):
    client=control[0]; op=preview(control)
    assert client.post(f'{BASE}/{op}/confirm',json={'idempotency_key':KEY}).status_code==200
    other=preview(control)
    assert client.post(f'{BASE}/{other}/confirm',json={'idempotency_key':KEY}).status_code==409
    assert client.post(f'{BASE}/{op}/confirm',json={'idempotency_key':KEY+'2'}).status_code==409
    assert len(control[-1])==1


def test_cancel_and_generic_confirm_cannot_send(control):
    client=control[0]; op=preview(control)
    assert client.post('/dnf-gm/api/v1/operations/'+op+'/confirm',json={'idempotency_key':KEY}).status_code==409
    assert client.post(f'{BASE}/{op}/cancel-preview').json()['status']=='cancelled'
    assert client.post(f'{BASE}/{op}/cancel-preview').json()['status']=='cancelled'
    assert client.post(f'{BASE}/{op}/confirm',json={'idempotency_key':KEY}).status_code==409
    assert not control[-1]


@pytest.mark.parametrize('mutation', ['expiry','target','image','activation','resource','fingerprint'])
def test_recheck_before_claim(control, mutation):
    client,s,db,app,ops,sent=control;op=preview(control)
    if mutation=='expiry': sql(db,'UPDATE dnf_gm.operations SET expires_at=0 WHERE operation_id=%s',(op,))
    elif mutation=='target':sql(db,"UPDATE d_taiwan.accounts SET accountname='changed' WHERE UID=900001")
    elif mutation=='image':s.image_digest='changed'
    elif mutation=='activation':s.native_control_actions=()
    elif mutation=='fingerprint':sql(db,"UPDATE dnf_gm.operations SET fingerprint=%s WHERE operation_id=%s",('0'*64,op))
    else:
        from pathlib import Path
        p=Path(s.status_file);data=json.loads(p.read_text());data['mem_available_mib']=1;p.write_text(json.dumps(data))
    assert client.post(f'{BASE}/{op}/confirm',json={'idempotency_key':KEY}).status_code in (409,503)
    assert not sent


def test_wrong_session_and_auth_csrf(control):
    client,s,db,app,ops,sent=control;op=preview(control)
    with pytest.raises(HTTPException) as exc:ops.confirm('not-owner',op,KEY)
    assert exc.value.status_code==404
    assert client.post(f'{BASE}/{op}/confirm',headers={'X-CSRF-Token':'bad'},json={'idempotency_key':KEY}).status_code==403
    client.cookies.clear()
    assert client.get(f'{BASE}/{op}').status_code==401
    assert client.get(BASE).status_code==401
    assert not sent


def test_recent_password_required(control):
    client,s,db,app,ops,sent=control;op=preview(control)
    sql(db,'UPDATE dnf_gm.sessions SET authenticated_at=0')
    r=client.post(f'{BASE}/{op}/confirm',json={'idempotency_key':KEY})
    assert r.status_code==403 and '重新认证' in r.text
    assert not sent


def test_audit_failure_rolls_back_ban_and_claim(control):
    client,s,db,app,ops,sent=control;op=preview(control,'native-ban-kick')
    sql(db,"INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'fixture','fixture','fixture','{}','{}')",(op,))
    assert client.post(f'{BASE}/{op}/confirm',json={'idempotency_key':KEY}).status_code==500
    assert not sent
    assert ops.detail(op)['status']=='preview'
    assert not sql(db,'SELECT * FROM d_taiwan.member_punish_info WHERE m_id=900001')


@pytest.mark.parametrize('stage,after_commit,expected,sends', [(1,False,'preview',0),(1,True,'dispatching',0),(2,False,'dispatching',1),(2,True,'sent',1)])
def test_commit_disconnect_never_replays(control, stage, after_commit, expected, sends):
    client,s,db,app,ops,sent=control
    p=ops.preview('S',request('native-ban-kick'));op=p['operation_id']
    factory=db.factory; count=0
    class Fault:
        def __init__(self,c):self.c=c
        def __getattr__(self,key):return getattr(self.c,key)
        def commit(self):
            nonlocal count
            count+=1
            if count==stage:
                if after_commit:self.c.commit()
                raise OSError('private connection details')
            return self.c.commit()
    db.factory=lambda:Fault(factory())
    try:
        with pytest.raises(HTTPException) as exc:ops.confirm('S',op,KEY)
        assert exc.value.status_code==503 and 'private' not in str(exc.value.detail)
    finally:db.factory=factory
    assert len(sent)==sends and ops.detail(op)['status']==expected
    if expected!='preview':
        assert ops.confirm('S',op,KEY)['status']==expected
        # New service instance models restart; no in-memory token is relied on.
        restart=NativeOperations(app.state.service,app.state.native_monitor)
        restart.transport.kick=lambda *args:pytest.fail('must not replay')
        assert restart.confirm('S',op,KEY)['status']==expected
        assert sql(db,'SELECT apply_flag FROM d_taiwan.member_punish_info WHERE m_id=900001')[0]['apply_flag']==1
    else:assert not sql(db,'SELECT * FROM d_taiwan.member_punish_info WHERE m_id=900001')


def test_concurrent_confirmation_and_cancellation(control):
    client,s,db,app,ops,sent=control
    op=ops.preview('S',request())['operation_id']
    entered,release=Event(),Event()
    def block(uid):
        sent.append(uid);entered.set();assert release.wait(5)
        return {'transport_status':'sent','effect_status':'unknown','reason_code':'no_application_ack'}
    ops.transport.kick=block
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending=pool.submit(ops.confirm,'S',op,KEY)
        try:
            assert entered.wait(5)
            assert ops.confirm('S',op,KEY)['status']=='dispatching'
            with pytest.raises(HTTPException):ops.cancel('S',op)
        finally:release.set()
        assert pending.result(timeout=5)['status']=='sent'
    assert len(sent)==1


@pytest.mark.parametrize('status', ['not_sent','uncertain'])
def test_ban_result_distinct_from_kick(control,status):
    client,s,db,app,ops,sent=control
    ops.transport.kick=lambda uid:{'transport_status':status,'effect_status':'unknown','reason_code':'fixture'}
    op=preview(control,'native-ban-kick')
    r=client.post(f'{BASE}/{op}/confirm',json={'idempotency_key':KEY}).json()
    assert r['status']==status and r['result']['ban_status']=='committed_login_test_pending'


def test_foreign_punishment_never_overwritten(control):
    client,s,db,app,ops,sent=control
    sql(db,"INSERT INTO d_taiwan.member_punish_info(m_id,punish_type,occ_time,punish_value,apply_flag,start_time,end_time,admin_id,reason) VALUES(900001,1,NOW(),1,1,NOW(),'2099-01-01','OTHER','foreign')")
    assert client.post(BASE+'/preview',json=request('native-ban-kick')).status_code==409
    assert not sent


def test_cancel_old_session_preview_for_recovery(control):
    client,s,db,app,ops,sent=control
    op=ops.preview('old-session',request())['operation_id']
    assert client.post(f'{BASE}/{op}/cancel-preview').json()['status']=='cancelled'
    with pytest.raises(HTTPException):ops.confirm('old-session',op,KEY)
    assert not sent


def test_postclaim_readiness_change_preserves_ban_but_sends_nothing(control):
    client,s,db,app,ops,sent=control
    op=ops.preview('S',request('native-ban-kick'))['operation_id']
    original=ops.ready;calls=0
    def ready(action,uid):
        nonlocal calls
        calls+=1
        if calls==2:raise HTTPException(503,'fixture resource failure')
        return original(action,uid)
    ops.ready=ready
    r=ops.confirm('S',op,KEY)
    assert r['status']=='not_sent' and not sent
    assert r['result']['ban_status']=='committed_login_test_pending'


def test_transport_exception_is_durably_uncertain_and_not_replayed(control):
    client,s,db,app,ops,sent=control
    def fail(uid):sent.append(uid);raise RuntimeError('private details')
    ops.transport.kick=fail
    op=ops.preview('S',request())['operation_id']
    r=ops.confirm('S',op,KEY)
    assert r['status']=='uncertain' and 'private details' not in json.dumps(r)
    assert ops.confirm('S',op,KEY)==r and len(sent)==1


def test_foreign_punishment_inserted_after_preview_is_not_overwritten(control):
    client,s,db,app,ops,sent=control;op=preview(control,'native-ban-kick')
    sql(db,"INSERT INTO d_taiwan.member_punish_info(m_id,punish_type,occ_time,punish_value,apply_flag,start_time,end_time,admin_id,reason) VALUES(900001,1,NOW(),1,1,NOW(),'2099-01-01','OTHER','foreign')")
    assert client.post(f'{BASE}/{op}/confirm',json={'idempotency_key':KEY}).status_code==409
    assert not sent and sql(db,'SELECT admin_id FROM d_taiwan.member_punish_info WHERE m_id=900001')[0]['admin_id']=='OTHER'


def test_nontransactional_audit_blocks_native_preview(control):
    client,s,db,app,ops,sent=control
    sql(db,'ALTER TABLE dnf_gm.audit ENGINE=MyISAM')
    assert client.post(BASE+'/preview',json=request()).status_code==409
    assert not sent


def test_native_history_migration_idempotence_and_account_filter(control):
    from pathlib import Path
    client,s,db,app,ops,sent=control
    a=ops.preview('S',request())['operation_id'];s.test_uids=()
    b=ops.preview('S',request('native-notice'))['operation_id']
    assert {r['operation_id'] for r in ops.history()['items']}=={a,b}
    assert [r['operation_id'] for r in ops.history(900001)['items']]==[a]
    migration=(Path(__file__).resolve().parents[2]/'migrations/007-native-controls.sql').read_text()
    for _ in range(2):
        with db.connect() as c,c.cursor() as q:
            for statement in migration.split(';'):
                if statement.strip():q.execute(statement)
            c.commit()
    assert len(sql(db,'SELECT * FROM dnf_gm.native_controls'))==2
    assert ops.history(page=2)['items']==[] and not sent


def test_actual_minimum_grants_for_native_controls(control):
    import importlib.util
    import os
    from pathlib import Path
    import pymysql
    from fastapi.testclient import TestClient
    from dnfgm.app import create_app
    from dnfgm.db import Database
    from dnfgm.security import PASSWORDS
    client,s,rootdb,app,ops,sent=control
    spec=importlib.util.spec_from_file_location('native_grants',Path(__file__).resolve().parents[2]/'deploy/grants.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    text=module.bootstrap_sql({'db_user':'native_minimal','db_password':'isolated-fixture-password','db_account_host':'localhost'},PASSWORDS.hash('fixture-admin-password'))
    with rootdb.connect() as c,c.cursor() as q:
        q.execute('DROP DATABASE dnf_gm');q.execute("DROP USER IF EXISTS 'native_minimal'@'localhost'")
        for statement in text.split(';'):
            if statement.strip():q.execute(statement)
        c.commit()
    def factory():return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'],user='native_minimal',password='isolated-fixture-password',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    limited=Database(s,factory);application=create_app(s,limited)
    application.state.native_operations.transport.kick=lambda uid:{'transport_status':'sent','effect_status':'unknown','reason_code':'synthetic'}
    with TestClient(application) as c:
        c.headers['Origin']='http://testserver'
        r=c.post('/dnf-gm/api/v1/auth/login',json={'username':'admin','password':'fixture-admin-password'});assert r.status_code==200,r.text
        c.headers['X-CSRF-Token']=r.json()['csrf']
        r=c.post(BASE+'/preview',json=request('native-ban-kick'));assert r.status_code==200,r.text
        op=r.json()['operation_id']
        r=c.post(f'{BASE}/{op}/confirm',json={'idempotency_key':KEY});assert r.status_code==200,r.text
        assert c.get(BASE+'?uid=900001').json()['items'][0]['operation_id']==op
        assert c.get('/dnf-gm/api/v1/health').status_code==200
    for statement in ('DELETE FROM dnf_gm.audit','DELETE FROM dnf_gm.native_controls','UPDATE dnf_gm.native_controls SET target_uid=1','DROP TABLE dnf_gm.operations'):
        with limited.connect() as c,c.cursor() as q:
            with pytest.raises(pymysql.OperationalError):q.execute(statement)
