import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import importlib.util
import os

import pymysql
import pytest
from fastapi import HTTPException
from dnfgm.support import SupportDesk
from dnfgm.security import COOKIE,digest as token_digest,PASSWORDS
from dnfgm.db import Database

P='/dnf-gm/api/v1';S=P+'/support'
def key():return uuid.uuid4().hex
def create(env,**extra):
    data={'uid':900001,'charac_no':900001,'title':'邮件没收到','category':'mail','description':'合成问题记录','idempotency_key':key(),**extra}
    r=env[0].post(S+'/cases',json=data);assert r.status_code==200,r.text;return r.json()
def detail(env,cid):
    r=env[0].get(S+'/cases/'+cid);assert r.status_code==200,r.text;return r.json()
def reward(env,cid=None):
    r=env[0].post(P+'/operations/preview',json={'action':'currency','uid':900001,'charac_no':900001,'currency':'cera','delta':100,'reason':'问题补偿','support_case_id':cid})
    assert r.status_code==200,r.text;return r.json()
def confirm(env,op):return env[0].post(P+'/operations/'+op+'/confirm',json={'idempotency_key':key()})
def comment(env,cid,revision,note='已检查原投递记录',**extra):
    return env[0].post(S+f'/cases/{cid}/entries',json={'expected_revision':revision,'note':note,'idempotency_key':key(),**extra})


def test_profile_revision_tags_idempotency_and_audit(env):
    c,_,db,_=env;p=c.get(S+'/profiles/900001').json();assert p['revision']==0 and not p['tags']
    data={'notes':'待核对，<script>只存文本</script>','tags':['测试','活动'],'expected_revision':0,'idempotency_key':key()}
    r=c.put(S+'/profiles/900001',json=data);assert r.status_code==200,r.text
    assert c.put(S+'/profiles/900001',json=data).json()==r.json()
    p=c.get(S+'/profiles/900001').json();assert p['revision']==1 and p['notes']==data['notes'] and p['tags']==data['tags']
    assert c.put(S+'/profiles/900001',json={**data,'notes':'另一个内容'}).status_code==409
    assert c.put(S+'/profiles/900001',json={**data,'idempotency_key':key()}).status_code==409
    with db.connect() as conn,conn.cursor() as q:
        q.execute("SELECT COUNT(*) n FROM dnf_gm.audit WHERE action='player-profile'");assert q.fetchone()['n']==1
    assert c.get(S+'/requests/'+data['idempotency_key']).json()==r.json()


@pytest.mark.parametrize('changes',[{'tags':['同一个','同一个']},{'tags':[' ']},{'tags':['x'*25]},{'notes':'x'*4001},{'expected_revision':True},{'tags':['x']*11}])
def test_profile_input_bounds(env,changes):
    data={'notes':'','tags':[],'expected_revision':0,'idempotency_key':key(),**changes}
    assert env[0].put(S+'/profiles/900001',json=data).status_code==422


def test_case_lifecycle_comments_no_deletion_and_immutable_target(env):
    c=env[0];cid=create(env)['case_id'];row=detail(env,cid)['case'];assert row['status']=='open' and row['revision']==1
    update={'title':row['title'],'description':row['description'],'category':row['category'],'status':'in_progress','note':'开始排查','expected_revision':1,'idempotency_key':key()}
    assert c.put(S+'/cases/'+cid,json=update).status_code==200
    assert comment(env,cid,2).status_code==200
    assert comment(env,cid,2).status_code==409
    update.update(status='resolved',expected_revision=3,note='核对后已解决',idempotency_key=key());assert c.put(S+'/cases/'+cid,json=update).status_code==200
    update.update(status='open',expected_revision=4,note='玩家补充新情况，重新打开',idempotency_key=key());assert c.put(S+'/cases/'+cid,json=update).status_code==200
    result=detail(env,cid);assert result['case']['revision']==5 and len(result['events'])==5
    assert c.delete(S+'/cases/'+cid).status_code==405
    update.update(uid=900002,expected_revision=5,idempotency_key=key());assert c.put(S+'/cases/'+cid,json=update).status_code==422


def test_target_ownership_and_deleted_role_inquiry(env):
    c,_,db,_=env
    assert c.post(S+'/cases',json={'uid':900001,'charac_no':99999,'title':'x','description':'y','idempotency_key':key()}).status_code==409
    with db.connect() as conn,conn.cursor() as q:q.execute('UPDATE taiwan_cain.charac_info SET delete_flag=1 WHERE charac_no=900001');conn.commit()
    cid=create(env)['case_id'];assert detail(env,cid)['case']['target']['character']['delete_flag']==1
    # Inquiry records do not grant permission to reward a deleted role.
    r=c.post(P+'/operations/preview',json={'action':'currency','uid':900001,'charac_no':900001,'currency':'cera','delta':10,'reason':'test','support_case_id':cid});assert r.status_code==409


def test_search_treats_sql_wildcards_and_injection_as_literal(env):
    a=create(env,title='邮件100%丢失')['case_id'];create(env,title='另一记录')
    r=env[0].get(S+'/cases',params={'q':'%'}).json();assert [x['case_id'] for x in r['items']]==[a]
    assert env[0].get(S+'/cases',params={'q':"' OR 1=1 --"}).json()['items']==[]
    assert len(env[0].get(S+'/cases',params={'uid':900001,'status':'open','category':'mail'}).json()['items'])==2


def test_reward_association_is_atomic_and_duplicate_count_invalidates_preview(env):
    cid=create(env)['case_id'];a=reward(env,cid);b=reward(env,cid)
    assert a['preview']['support_case']['compensation_count']==0
    r=confirm(env,a['operation_id']);assert r.status_code==200,r.text
    row=detail(env,cid);assert row['case']['compensation_count']==1 and row['case']['status']=='open'
    assert row['links'][0]['operation_id']==a['operation_id'] and row['links'][0]['relation']=='compensation'
    assert row['events'][0]['details']['status_at_link']=='committed_with_reward_transaction'
    assert confirm(env,b['operation_id']).status_code==409
    assert reward(env,cid)['preview']['support_case']['compensation_count']==1


def test_case_change_requires_new_reward_preview(env):
    cid=create(env)['case_id'];p=reward(env,cid)
    assert comment(env,cid,1).status_code==200
    r=confirm(env,p['operation_id']);assert r.status_code==409,r.text
    assert detail(env,cid)['links']==[]


def test_links_distinguish_reference_from_compensation(env):
    cid=create(env)['case_id'];p=reward(env)
    body={'expected_revision':1,'note':'核对原操作','idempotency_key':key(),'operation_id':p['operation_id'],'relation':'compensation'}
    assert env[0].post(S+f'/cases/{cid}/links',json=body).status_code==409
    body.update(relation='reference',idempotency_key=key());assert env[0].post(S+f'/cases/{cid}/links',json=body).status_code==200
    assert detail(env,cid)['case']['compensation_count']==0
    assert confirm(env,p['operation_id']).status_code==200
    body.update(expected_revision=2,relation='compensation',idempotency_key=key());assert env[0].post(S+f'/cases/{cid}/links',json=body).status_code==200
    body.update(expected_revision=3,relation='reference',idempotency_key=key());assert env[0].post(S+f'/cases/{cid}/links',json=body).status_code==409
    assert detail(env,cid)['case']['compensation_count']==1


def test_foreign_account_cannot_link_or_use_reward_case(env):
    cid=create(env)['case_id'];p=reward(env);db=env[2]
    with db.connect() as c,c.cursor() as q:q.execute('UPDATE dnf_gm.support_cases SET uid=900002 WHERE case_id=%s',(cid,));c.commit()
    r=env[0].post(S+f'/cases/{cid}/links',json={'expected_revision':1,'note':'禁止跨账号','idempotency_key':key(),'operation_id':p['operation_id']});assert r.status_code==409
    r=env[0].post(P+'/operations/preview',json={'action':'currency','uid':900001,'currency':'cera','delta':10,'reason':'test','support_case_id':cid});assert r.status_code==409


def test_parallel_revision_updates_have_one_winner(env):
    cid=create(env)['case_id'];support=env[3].state.service.support
    def save(i):
        try:return support.mutation('case-comment',cid,{'idempotency_key':key(),'expected_revision':1,'note':str(i)})['revision']
        except HTTPException as e:return e.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,[1,2]))
    assert sorted(results)==[2,409]
    assert len(detail(env,cid)['events'])==2


def test_failure_to_audit_rolls_back_case_and_request_receipt(env,monkeypatch):
    from test_inventory_operations import Conn
    db=env[2];factory=db.factory
    class Cursor:
        def __init__(self,q):self.q=q
        def __getattr__(self,k):return getattr(self.q,k)
        def __enter__(self):return self
        def __exit__(self,*a):self.q.close()
        def execute(self,sql,*args):
            if sql.startswith('INSERT INTO dnf_gm.audit'):raise pymysql.OperationalError(1105,'synthetic audit failure')
            return self.q.execute(sql,*args)
    monkeypatch.setattr(db,'factory',lambda:Conn(factory(),cursor=Cursor))
    data={'uid':900001,'charac_no':None,'title':'test','description':'test','category':'other','idempotency_key':key()}
    with pytest.raises(pymysql.OperationalError):env[3].state.service.support.mutation('case-create',None,data)
    monkeypatch.setattr(db,'factory',factory)
    assert env[0].get(S+'/cases').json()['items']==[]
    assert env[0].get(S+'/requests/'+data['idempotency_key']).status_code==404


def test_management_commit_response_loss_readback_never_duplicates(env,monkeypatch):
    from test_inventory_operations import Conn
    db=env[2];factory=db.factory;support=env[3].state.service.support
    def lost(c):c.commit();raise pymysql.OperationalError(2013,'synthetic commit acknowledgement loss')
    monkeypatch.setattr(db,'factory',lambda:Conn(factory(),commit=lost))
    data={'uid':900001,'charac_no':None,'title':'test','description':'test','category':'other','idempotency_key':key()}
    with pytest.raises(HTTPException) as fail:support.mutation('case-create',None,data)
    assert fail.value.status_code==503
    monkeypatch.setattr(db,'factory',factory)
    result=support.request(data['idempotency_key']);assert support.mutation('case-create',None,data)==result
    assert len(support.cases()['items'])==1


def test_failed_compensation_link_rolls_back_reward(env,monkeypatch):
    cid=create(env)['case_id'];p=reward(env,cid);service=env[3].state.service
    before=env[0].get(P+'/accounts/900001').json()['cera']
    def fail(*args):raise RuntimeError('synthetic support link failure')
    monkeypatch.setattr(service.support,'attach_reward',fail)
    assert confirm(env,p['operation_id']).status_code==500
    assert env[0].get(P+'/accounts/900001').json()['cera']==before
    assert detail(env,cid)['links']==[]


def test_pagination_and_append_only_events(env):
    cid=create(env)['case_id'];support=env[3].state.service.support
    for i in range(24):support.mutation('case-comment',cid,{'idempotency_key':key(),'expected_revision':i+1,'note':str(i)})
    first=support.detail(cid);second=support.detail(cid,event_page=2)
    assert len(first['events'])==20 and first['events_has_more']
    assert len(second['events'])==5 and not second['events_has_more']
    assert not {r['revision'] for r in first['events']} & {r['revision'] for r in second['events']}


def test_auth_csrf_and_origins_protect_support(env):
    c=env[0]
    assert c.post(S+'/cases',json={'uid':900001,'title':'x','description':'x','idempotency_key':key()},headers={'X-CSRF-Token':'wrong'}).status_code==403
    assert c.post(S+'/cases',json={'uid':900001,'title':'x','description':'x','idempotency_key':key()},headers={'Origin':'https://evil.example'}).status_code==403
    assert 'access-control-allow-origin' not in c.get(S+'/cases',headers={'Origin':'https://evil.example'}).headers
    c.post(P+'/auth/logout')
    for path in ('/cases','/profiles/900001','/requests/'+'a'*32):assert c.get(S+path).status_code==401


def test_minimal_permissions_management_and_transactional_compensation(env):
    from dnfgm.service import Service
    root=env[2];path=Path(__file__).resolve().parents[2]/'deploy/grants.py'
    spec=importlib.util.spec_from_file_location('support_grants',path);grants=importlib.util.module_from_spec(spec);spec.loader.exec_module(grants)
    sql=grants.bootstrap_sql({'db_user':'support_minimal','db_password':'isolated-fixture-password','db_account_host':'localhost'},PASSWORDS.hash('fixture-admin-password'))
    with root.connect() as c,c.cursor() as q:
        q.execute('DROP DATABASE dnf_gm');q.execute("DROP USER IF EXISTS 'support_minimal'@'localhost'")
        for statement in sql.split(';'):
            if statement.strip():q.execute(statement)
        c.commit()
    def factory():return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'],user='support_minimal',password='isolated-fixture-password',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    db=Database(env[1],factory);service=Service(db,env[1]);support=service.support
    try:
        r=support.mutation('case-create',None,{'uid':900001,'charac_no':900001,'title':'test','description':'test','category':'reward','idempotency_key':key()});cid=r['case_id']
        support.mutation('player-profile',900001,{'notes':'test','tags':['x'],'expected_revision':0,'idempotency_key':key()})
        p=service.preview('f'*64,{'action':'currency','uid':900001,'charac_no':900001,'currency':'cera','delta':1,'reason':'test','support_case_id':cid})
        result=service.confirm('f'*64,p['operation_id'],key());assert result['support_case_id']==cid
        assert support.detail(cid)['case']['compensation_count']==1
        for statement in ('DELETE FROM dnf_gm.support_events','UPDATE dnf_gm.support_events SET note=\'x\'','DELETE FROM dnf_gm.support_cases','DROP TABLE dnf_gm.support_cases','SELECT password FROM d_taiwan.accounts','UPDATE taiwan_cain.charac_info SET lev=1'):
            with db.connect() as c,c.cursor() as q:
                with pytest.raises(pymysql.OperationalError):q.execute(statement)
    finally:
        with root.connect() as c,c.cursor() as q:q.execute("DROP USER IF EXISTS 'support_minimal'@'localhost'");c.commit()


def test_parallel_same_management_request_deduplicates(env):
    support=env[3].state.service.support
    data={'uid':900001,'charac_no':None,'title':'same','description':'same','category':'other','idempotency_key':key()}
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:support.mutation('case-create',None,data),range(2)))
    assert results[0]==results[1] and len(support.cases()['items'])==1


def test_reward_committed_but_response_lost_keeps_one_compensation(env,monkeypatch):
    from test_inventory_operations import Conn
    cid=create(env)['case_id'];p=reward(env,cid);db=env[2];factory=db.factory;service=env[3].state.service;idem=key()
    session=token_digest(env[0].cookies.get(COOKIE))
    def lost(c):c.commit();raise pymysql.OperationalError(2013,'synthetic acknowledgement loss')
    monkeypatch.setattr(db,'factory',lambda:Conn(factory(),commit=lost))
    with pytest.raises(HTTPException) as fail:service.confirm(session,p['operation_id'],idem)
    assert fail.value.status_code==503
    monkeypatch.setattr(db,'factory',factory)
    assert service.confirm(session,p['operation_id'],idem)['support_case_id']==cid
    assert detail(env,cid)['case']['compensation_count']==1
    assert len(detail(env,cid)['links'])==1


def test_nontransactional_support_table_blocks_reward_before_writing(env):
    cid=create(env)['case_id'];p=reward(env,cid);before=env[0].get(P+'/accounts/900001').json()['cera']
    with env[2].connect() as c,c.cursor() as q:q.execute('ALTER TABLE dnf_gm.support_events ENGINE=MyISAM');c.commit()
    assert confirm(env,p['operation_id']).status_code==503
    assert env[0].get(P+'/accounts/900001').json()['cera']==before


@pytest.mark.parametrize('action',['mail','reward'])
@pytest.mark.parametrize('fail_link',[False,True])
def test_mail_and_combined_compensation_commit_or_rollback_together(env,monkeypatch,action,fail_link):
    from test_combined_rewards import enable
    c,settings,db,app=env;enable(settings)
    cid=create(env)['case_id']
    request={'action':action,'uid':900001,'charac_no':900001,'items':[{'id':990002,'quantity':12345}],
             'gold':1000,'reason':'synthetic support reward','message':'GM rewards','support_case_id':cid}
    if action=='reward':request['currency_rewards']={'cera':50,'cera_point':20,'mileage':30}
    p=c.post(P+'/operations/preview',json=request);assert p.status_code==200,p.text
    op=p.json()['operation_id']
    original=app.state.service.support.attach_reward
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('synthetic failure after support and mail writes')
    if fail_link:monkeypatch.setattr(app.state.service.support,'attach_reward',fail)
    confirmation_key=key()
    r=c.post(P+'/operations/'+op+'/confirm',json={'idempotency_key':confirmation_key});assert r.status_code==(500 if fail_link else 200),r.text
    with db.connect() as conn,conn.cursor() as q:
        for table in ('taiwan_cain_2nd.postal','taiwan_cain_2nd.letter','dnf_gm.mail_batches','dnf_gm.support_links'):
            q.execute('SELECT COUNT(*) n FROM '+table);assert q.fetchone()['n']==(0 if fail_link else 1)
        q.execute('SELECT cera FROM taiwan_billing.cash_cera');assert q.fetchone()['cera']==(1050 if action=='reward' and not fail_link else 1000)
        q.execute('SELECT COUNT(*) n FROM dnf_gm.audit WHERE operation_id=%s',(op,));assert q.fetchone()['n']==(0 if fail_link else 1)
    row=detail(env,cid);assert row['case']['compensation_count']==(0 if fail_link else 1)
    if not fail_link:
        assert c.post(P+'/operations/'+op+'/confirm',json={'idempotency_key':confirmation_key}).json()==r.json()
        assert confirm(env,op).status_code==409
        assert detail(env,cid)['case']['compensation_count']==1
        assert r.json()['client_verified'] is False
