import json,time
import pytest
from dnfgm.security import COOKIE

P='/dnf-gm/api/v1'


def preview(c,**kw):
    payload={'action':'currency','uid':900001,'currency':'cera','delta':100,'reason':'测试，不使用生产账号'}
    payload.update(kw)
    return c.post(P+'/operations/preview',json=payload)


def confirm(c,op,key='test-idempotency-key-001'):
    return c.post(P+'/operations/'+op+'/confirm',json={'idempotency_key':key})


def test_read_only_routes_and_no_passwords(env):
    c,s,db,app=env
    for path in ['/overview','/accounts','/accounts/900001','/characters?uid=900001','/online','/catalog','/gift-templates','/audit']:
        r=c.get(P+path);assert r.status_code==200,r.text
        assert 'password_hash' not in r.text and 'fixture-password' not in r.text
    assert c.get(P+'/auth/me').status_code==200
    assert c.get(P+'/auth/methods').json()=={'totp_required':False}


def test_origin_csrf_auth_body_and_xss_encoding(env):
    c,s,db,app=env
    assert c.post(P+'/operations/preview',json={},headers={'Origin':'https://evil.example'}).status_code==403
    assert c.post(P+'/auth/logout',headers={'X-CSRF-Token':'wrong'}).status_code==403
    assert c.post(P+'/auth/login',content='x'*65537).status_code==413
    assert c.get(P+'/accounts',headers={'Host':'evil.example'}).status_code==400
    assert c.get(P+'/accounts?q=%27%20OR%201%3D1--').json()['items']==[]
    c.cookies.clear()
    assert c.get(P+'/accounts').status_code==401


def test_currency_duplicate_stale_and_conflict(env):
    c,s,db,app=env
    r=preview(c);assert r.status_code==200,r.text
    op=r.json()['operation_id']
    first=confirm(c,op);assert first.status_code==200,first.text
    assert first.json()['after']==1100
    assert confirm(c,op).json()==first.json()
    second=preview(c).json()['operation_id']
    assert confirm(c,second).status_code==409
    assert c.get(P+'/accounts/900001').json()['cera']==1100
    assert len(c.get(P+'/audit').json()['items'])==1
    assert confirm(c,second,'a-different-test-key').json()['after']==1200
    assert confirm(c,op,'yet-another-test-key').status_code==409


def test_two_previews_stale_balance(env):
    c,s,db,app=env
    a=preview(c).json()['operation_id'];b=preview(c).json()['operation_id']
    assert confirm(c,a).status_code==200
    assert confirm(c,b,'another-idempotency-key').status_code==409
    assert c.get(P+'/accounts/900001').json()['cera']==1100


@pytest.mark.parametrize('kw', [{'delta':-1001},{'delta':0},{'delta':True},{'currency':'bad'},{'uid':900002,'delta':100}])
def test_currency_bad_inputs(env,kw):
    c,s,db,app=env
    r=preview(c,**kw)
    if r.status_code==200:
        assert confirm(c,r.json()['operation_id']).status_code==403
    else:assert r.status_code in (422,404)


def test_feature_disabled_and_expiry_session(env):
    c,s,db,app=env
    s.writes=()
    op=preview(c).json()['operation_id']
    assert confirm(c,op).status_code==403
    with db.connect() as con,con.cursor() as q:
        q.execute('UPDATE dnf_gm.sessions SET touched_at=0');con.commit()
    assert c.get(P+'/accounts').status_code==401


def test_reauth_and_expired_preview(env):
    c,s,db,app=env
    op=preview(c).json()['operation_id']
    with db.connect() as con,con.cursor() as q:
        q.execute('UPDATE dnf_gm.sessions SET authenticated_at=0');con.commit()
    assert confirm(c,op).status_code==403
    assert c.post(P+'/auth/reauth',json={'username':'admin','password':'fixture-password-no-production'}).status_code==200
    with db.connect() as con,con.cursor() as q:
        q.execute('UPDATE dnf_gm.operations SET expires_at=0');con.commit()
    assert confirm(c,op).status_code==409


def mail(c,items=None,**kw):
    return preview(c,action='mail',currency=None,delta=None,charac_no=900001,items=items or [{'id':990001,'quantity':1},{'id':990002,'quantity':20}],**kw)


def test_mail_atomic_and_results_not_claimed(env):
    c,s,db,app=env
    r=mail(c);assert r.status_code==200,r.text
    op=r.json()['operation_id'];r=confirm(c,op)
    assert r.status_code==200,r.text
    assert r.json()['state']=='database_delivered_not_claimed' and len(r.json()['postal_ids'])==2
    assert confirm(c,op).json()==r.json()
    detail=c.get(P+'/operations/'+op).json()
    assert len(detail['delivery_records'])==2
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT add_info,endurance FROM taiwan_cain_2nd.postal ORDER BY postal_id')
        assert q.fetchall()==[{'add_info':0,'endurance':20},{'add_info':20,'endurance':0}]


@pytest.mark.parametrize('items',[ [{'id':990003,'quantity':1}], [{'id':990001,'quantity':2}], [{'id':990002,'quantity':100}], [{'id':12345,'quantity':1}] ])
def test_mail_restricts_special_and_quantity(env,items):
    assert mail(env[0],items).status_code==422


def test_mail_version_mismatch_and_wrong_owner(env):
    c,s,db,app=env
    r=mail(c);op=r.json()['operation_id']
    s.pvf_sha256='b'*64
    assert confirm(c,op).status_code==409
    s.pvf_sha256='a'*64
    r=preview(c,action='mail',currency=None,delta=None,charac_no=900002,items=[{'id':990002,'quantity':1}])
    assert r.status_code==409


def test_audit_failure_rolls_back_money(env):
    c,s,db,app=env
    op=preview(c).json()['operation_id']
    with db.connect() as con,con.cursor() as q:
        q.execute("CREATE TRIGGER dnf_gm.fail_audit BEFORE INSERT ON dnf_gm.audit FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic failure'")
    assert confirm(c,op).status_code==500
    assert c.get(P+'/accounts/900001').json()['cera']==1000
    assert c.get(P+'/operations/'+op).json()['status']=='preview'


def test_gifts_versions_and_immutable_payload(env):
    c,s,db,app=env
    payload={'name':'测试礼包','enabled':True,'expected_version':0,'items':[{'id':990002,'quantity':2}]}
    r=c.post(P+'/gift-templates',json=payload);assert r.status_code==200,r.text
    tid=r.json()['id']
    payload.update(name='新版',expected_version=1,items=[{'id':990002,'quantity':3}])
    assert c.put(P+f'/gift-templates/{tid}',json=payload).json()['version']==2
    assert c.put(P+f'/gift-templates/{tid}',json=payload).status_code==409
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT payload_json FROM dnf_gm.gift_versions WHERE template_id=%s AND version=1',(tid,))
        assert json.loads(q.fetchone()['payload_json'])['items'][0]['quantity']==2
    r=preview(c,action='mail',currency=None,delta=None,charac_no=900001,items=[],template_id=tid,template_version=2)
    op=r.json()['operation_id']
    payload.update(expected_version=2,enabled=False)
    assert c.put(P+f'/gift-templates/{tid}',json=payload).status_code==200
    assert confirm(c,op).status_code==409


def test_ban_and_unban_own_records_only(env):
    c,s,db,app=env
    r=preview(c,action='ban',currency=None,delta=None);assert r.status_code==200,r.text
    assert confirm(c,r.json()['operation_id']).json()['blocked'] is True
    r=preview(c,action='unban',currency=None,delta=None)
    assert confirm(c,r.json()['operation_id'],'different-key-for-unban').json()['blocked'] is False
    with db.connect() as con,con.cursor() as q:
        q.execute("UPDATE d_taiwan.member_punish_info SET admin_id='other-source',apply_flag=1 WHERE m_id=900001");con.commit()
    assert preview(c,action='unban',currency=None,delta=None).status_code==409


def test_stale_status_fails_closed(env):
    c,s,db,app=env
    op=preview(c).json()['operation_id']
    from pathlib import Path
    d=json.loads(Path(s.status_file).read_text());d['collected_at']=0
    Path(s.status_file).write_text(json.dumps(d))
    assert confirm(c,op).status_code==503
    assert c.get(P+'/overview').json()['server']['state']=='unknown'


def test_operation_result_survives_new_session(env):
    c,s,db,app=env
    op=preview(c).json()['operation_id']
    confirm(c,op)
    c.post('/dnf-gm/api/v1/auth/logout')
    r=c.post('/dnf-gm/api/v1/auth/login',json={'username':'admin','password':'fixture-password-no-production'})
    c.headers['X-CSRF-Token']=r.json()['csrf']
    r=c.get('/dnf-gm/api/v1/operations/'+op)
    assert r.status_code==200 and r.json()['status']=='committed'
    assert confirm(c,op).status_code==404  # confirmation is still preview-session-bound


def test_actual_runtime_grants(env):
    import importlib.util
    import sys
    from pathlib import Path
    import pymysql
    from dnfgm.db import Database
    from dnfgm.app import create_app
    from fastapi.testclient import TestClient
    path=Path(__file__).resolve().parents[2]/'deploy/grants.py'
    spec=importlib.util.spec_from_file_location('gm_grants',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    client,s,rootdb,app=env
    pwd='a'*44
    sql=m.bootstrap_sql({'db_user':'dnf_gm_app','db_password':pwd},'$argon2id$v=19$m=1,t=1,p=1$c2FsdA$aGFzaA')
    sql=sql.replace("'dnf_gm_app'@'127.0.0.1'","'dnf_gm_grants_test'@'localhost'")
    sql=sql[:sql.rfind('INSERT INTO dnf_gm.admins')]
    with rootdb.connect() as conn,conn.cursor() as q:
        q.execute("DROP USER IF EXISTS 'dnf_gm_grants_test'@'localhost'")
        for statement in sql.split(';'):
            if statement.strip():q.execute(statement)
        conn.commit()
    def factory():
        import os
        return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'],user='dnf_gm_grants_test',password=pwd,charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    limited=TestClient(create_app(s,Database(s,factory)),raise_server_exceptions=True)
    limited.headers['Origin']='http://testserver'
    r=limited.post('/dnf-gm/api/v1/auth/login',json={'username':'admin','password':'fixture-password-no-production'})
    assert r.status_code==200,r.text
    limited.headers['X-CSRF-Token']=r.json()['csrf']
    for route in ('overview','accounts','characters','online','characters/900001','catalog'):
        r=limited.get('/dnf-gm/api/v1/'+route);assert r.status_code==200,r.text
    for args in ({},{'action':'mail','charac_no':900001,'currency':None,'delta':None,'gold':1000,'items':[]},{'action':'mail','charac_no':900001,'currency':None,'delta':None,'items':[{'id':990002,'quantity':2}]},{'action':'ban','currency':None,'delta':None},{'action':'unban','currency':None,'delta':None}):
        r=preview(limited,**args);assert r.status_code==200,r.text
        r=confirm(limited,r.json()['operation_id'],key='runtime-grants-'+__import__('uuid').uuid4().hex)
        assert r.status_code==200,r.text
    r=limited.post(P+'/catalog/policy/preview',json={'enabled':False,'item_id':990002,'reason':'最小权限策略变更测试'})
    assert r.status_code==200,r.text
    r=confirm(limited,r.json()['operation_id'],key='policy-minimal-grants-test')
    assert r.status_code==200,r.text
    assert not limited.get(P+'/catalog?q=990002').json()['items'][0]['sendable']
    with factory() as conn,conn.cursor() as q:
        with pytest.raises(pymysql.MySQLError):q.execute("UPDATE dnf_gm.catalog_policy_items SET verification_evidence='forged'")
        with pytest.raises(pymysql.MySQLError):q.execute('SELECT password FROM d_taiwan.accounts')
        with pytest.raises(pymysql.MySQLError):q.execute('DELETE FROM dnf_gm.audit')
        with pytest.raises(pymysql.MySQLError):q.execute('UPDATE taiwan_cain_2nd.inventory SET money=1 WHERE charac_no=900001')
        with pytest.raises(pymysql.MySQLError):q.execute('SELECT VIP FROM taiwan_cain.charac_info')
    limited.close()


def test_template_search_paging_labels_and_empty_name(env):
    c,_,_,_=env
    data={'name':'全功能回归礼包','enabled':True,'expected_version':0,'items':[{'id':990002,'quantity':2}]}
    assert c.post(P+'/gift-templates',json={**data,'name':'  '}).status_code==422
    saved=c.post(P+'/gift-templates',json=data).json()
    result=c.get(P+'/gift-templates',params={'q':'全功能回归','page':1}).json()
    assert len(result['items'])==1 and result['items'][0]['id']==saved['id']
    assert result['items'][0]['rewards']['items'][0]['stack_limit']>0
    assert c.get(P+'/gift-templates',params={'q':'不存在模板'}).json()['items']==[]
    assert c.get(P+'/gift-templates',params={'page':2}).json()['items']==[]


def test_mail_invalid_encoding_rejected_before_confirm(env):
    c,_,_,_=env
    # U+4E01 UTF8 contains byte 0x81, undefined in cp1252 on this game image.
    assert mail(c,message='丁').status_code==422


def test_catalog_allowed_filter_keeps_full_catalog_readable(env):
    c,s,db,app=env
    all_items=c.get(P+'/catalog').json()['items']
    allowed=c.get(P+'/catalog?allowed_only=1').json()['items']
    assert len(all_items)==3
    assert {i['id'] for i in allowed}=={990001,990002}
    assert all(i['allowed'] and i['reviewed'] for i in allowed)
    assert c.get(P+'/catalog?allowed_only=1&category=material').json()['items'][0]['id']==990002
    assert c.get(P+'/catalog?allowed_only=1&q=990003').json()['items']==[]


def test_catalog_allowed_filter_is_read_only_and_requires_auth(env):
    c,s,db,app=env
    assert c.get(P+'/catalog?allowed_only=not-a-bool').status_code==422
    assert c.get(P+'/audit').json()['items']==[]
    c.cookies.clear()
    assert c.get(P+'/catalog?allowed_only=1').status_code==401
