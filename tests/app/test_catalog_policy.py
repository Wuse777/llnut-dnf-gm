"""Dynamic policy tests use only the isolated MySQL 5.7 laboratory."""
import json
import sqlite3
import time
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from test_application import P, confirm, mail


def add_items(s,n=65):
    with sqlite3.connect(s.catalog_file) as c:
        c.executemany('INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?)',[(991000+i,'可试发材料'+str(i),'material',1,100,0,0,0,'stackable/material') for i in range(n)])
        c.execute("INSERT INTO items VALUES(992000,'上限未知','material',1,0,0,0,0,'stackable/unknown')")


def policy(c,enabled=True,item_id=None,filters=None,reason='隔离环境策略验收'):
    return c.post(P+'/catalog/policy/preview',json={'enabled':enabled,'item_id':item_id,'filters':filters or {},'reason':reason})


def apply(c,**kw):
    p=policy(c,**kw);assert p.status_code==200,p.text
    op=p.json()['operation_id'];r=confirm(c,op,uuid.uuid4().hex);assert r.status_code==200,r.text
    return op,r.json()


def scalar(db,sql):
    with db.connect() as c,c.cursor() as q:q.execute(sql);return next(iter(q.fetchone().values()))


def test_original_items_are_trial_not_client_verified(env):
    c,s,db,app=env
    d=c.get(P+'/catalog').json();assert d['total']==3
    by={i['id']:i for i in d['items']}
    assert by[990001]['policy_state']=='trial'
    assert by[990001]['verification_evidence']=='' and by[990003]['policy_state']=='blocked'
    assert by[990003]['supported'] is False
    assert c.get(P+'/catalog?state=verified').json()['total']==0
    assert c.get(P+'/catalog?allowed_only=1').json()['total']==2


def test_enable_unreviewed_is_trial_mail_template_accept_it(env):
    c,s,db,app=env;add_items(s)
    apply(c,item_id=991000)
    i=c.get(P+'/catalog?q=991000').json()['items'][0]
    assert i['sendable'] and not i['reviewed'] and i['policy_state']=='trial'
    r=mail(c,[{'id':991000,'quantity':5}]);assert r.status_code==200,r.text
    assert confirm(c,r.json()['operation_id'],uuid.uuid4().hex).status_code==200
    gift={'name':'试发材料','enabled':True,'expected_version':0,'items':[{'id':991000,'quantity':1}]}
    assert c.post(P+'/gift-templates',json=gift).status_code==200
    assert c.get(P+'/gift-templates').json()['items'][0]['rewards']['items'][0]['policy_state']=='trial'
    apply(c,enabled=False,item_id=991000)
    assert mail(c,[{'id':991000,'quantity':1}]).status_code==422
    assert c.post(P+'/gift-templates',json=gift).status_code==422


def test_full_filter_batch_not_current_page_and_idempotent(env):
    c,s,db,app=env;add_items(s)
    p=policy(c,filters={'q':'可试发材料','category':'material'}).json()
    assert p['preview']['matched']==65 and p['preview']['affected']==65
    op=p['operation_id'];key=uuid.uuid4().hex
    a=confirm(c,op,key);assert a.status_code==200,a.text
    assert confirm(c,op,key).json()==a.json()
    assert confirm(c,op,uuid.uuid4().hex).status_code==409
    d=c.get(P+'/catalog?allowed_only=1&category=material&page=2').json()
    assert len(d['items'])==16 and d['total']==66
    assert scalar(db,'SELECT COUNT(*) FROM dnf_gm.catalog_policy_items')==65
    assert scalar(db,'SELECT COUNT(*) FROM dnf_gm.audit')==1
    assert scalar(db,'SELECT COUNT(*) FROM taiwan_cain_2nd.postal')==0


@pytest.mark.parametrize('item_id',[990003,992000,123456])
def test_special_unknown_cap_unknown_id_cannot_enable(env,item_id):
    c,s,db,app=env;add_items(s)
    assert policy(c,item_id=item_id).status_code==422
    assert scalar(db,'SELECT COUNT(*) FROM dnf_gm.catalog_policy_items')==0


def test_batch_skips_special_and_noop(env):
    c,s,db,app=env;add_items(s,1)
    p=policy(c).json()['preview'];assert p['matched']==5 and p['skipped']==2 and p['affected']==1 and p['unchanged']==2
    apply(c)
    assert policy(c).status_code==422
    assert not c.get(P+'/catalog?q=992000').json()['items'][0]['sendable']


def test_disabled_after_mail_preview_invalidates_old_preview(env):
    c,s,db,app=env
    m=mail(c).json()['operation_id']
    apply(c,enabled=False,item_id=990001)
    assert confirm(c,m,uuid.uuid4().hex).status_code in (409,422)
    assert scalar(db,'SELECT COUNT(*) FROM taiwan_cain_2nd.postal')==0


def test_policy_revision_and_selection_changed_require_new_preview(env):
    c,s,db,app=env;add_items(s,1)
    old=policy(c,item_id=991000).json()['operation_id']
    apply(c,enabled=False,item_id=990001)
    assert confirm(c,old,uuid.uuid4().hex).status_code==409
    p=policy(c,item_id=991000).json()['operation_id']
    with sqlite3.connect(s.catalog_file) as sc:sc.execute('UPDATE items SET stack_limit=101 WHERE id=991000')
    assert confirm(c,p,uuid.uuid4().hex).status_code==409
    assert scalar(db,'SELECT COUNT(*) FROM dnf_gm.catalog_policy_items')==1


def test_pvf_isolation_and_stale_snapshot(env):
    c,s,db,app=env;add_items(s,1)
    apply(c,item_id=991000)
    with sqlite3.connect(s.catalog_file) as sc:sc.execute("UPDATE metadata SET value=? WHERE key='pvf_sha256'",('b'*64,))
    assert not c.get(P+'/catalog?q=991000').json()['items'][0]['sendable']
    assert policy(c,item_id=991000).status_code==409
    with sqlite3.connect(s.catalog_file) as sc:sc.execute("UPDATE metadata SET value=? WHERE key='pvf_sha256'",('a'*64,))
    status=Path(s.status_file);d=json.loads(status.read_text());d['collected_at']=time.time()-50;status.write_text(json.dumps(d))
    assert policy(c,item_id=991000,enabled=False).status_code==409


def test_rollback_audit_failure_and_recovery(env):
    c,s,db,app=env;add_items(s,1)
    op=policy(c,item_id=991000).json()['operation_id']
    with db.connect() as con,con.cursor() as q:
        q.execute("CREATE TRIGGER dnf_gm.fail_audit_policy BEFORE INSERT ON dnf_gm.audit FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic failure'");con.commit()
    key=uuid.uuid4().hex
    assert confirm(c,op,key).status_code==500
    assert scalar(db,'SELECT COUNT(*) FROM dnf_gm.catalog_policy_items')==0
    assert scalar(db,'SELECT revision FROM dnf_gm.catalog_policy_state')==0
    assert c.get(P+'/operations/'+op).json()['status']=='preview'
    with db.connect() as con,con.cursor() as q:q.execute('DROP TRIGGER dnf_gm.fail_audit_policy');con.commit()
    assert confirm(c,op,key).status_code==200
    # Fresh service instance can query/retry the SAME committed operation safely.
    from dnfgm.service import Service
    service=Service(db,s)
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT session_hash FROM dnf_gm.operations WHERE operation_id=%s',(op,));session=q.fetchone()['session_hash']
    assert service.confirm(session,op,key)['affected']==1
    assert scalar(db,'SELECT COUNT(*) FROM dnf_gm.audit')==1


def test_policy_guards_reason_csrf_reauth_expiry_and_key_conflict(env):
    c,s,db,app=env
    assert policy(c,enabled=False,item_id=990001,reason='   ').status_code==422
    assert c.post(P+'/catalog/policy/preview',json={'enabled':False,'reason':'CSRF negative test'},headers={'X-CSRF-Token':'wrong'}).status_code==403
    a=policy(c,enabled=False,item_id=990001).json()['operation_id']
    b=policy(c,enabled=False,item_id=990002).json()['operation_id']
    assert confirm(c,a).status_code==200
    assert confirm(c,b).status_code==409
    with db.connect() as con,con.cursor() as q:q.execute('UPDATE dnf_gm.sessions SET authenticated_at=0');con.commit()
    assert policy(c,item_id=990001).status_code==403
    c.post(P+'/auth/reauth',json={'username':'admin','password':'fixture-password-no-production'})
    op=policy(c,item_id=990001).json()['operation_id']
    with db.connect() as con,con.cursor() as q:q.execute('UPDATE dnf_gm.operations SET expires_at=0 WHERE operation_id=%s',(op,));con.commit()
    assert confirm(c,op,uuid.uuid4().hex).status_code==409
    c.cookies.clear();assert c.get(P+'/catalog').status_code==401


def test_literal_filters_and_changed_items_preserve_bounds(env):
    c,s,db,app=env;add_items(s,1);apply(c,item_id=991000)
    assert c.get(P+'/catalog?q=%25').json()['items']==[]
    assert policy(c,filters={'q':"' OR 1=1 --"}).status_code==422
    assert mail(c,[{'id':991000,'quantity':101}]).status_code==422
    assert mail(c,[{'id':990001,'quantity':2}]).status_code==422
    assert mail(c,[{'id':991000,'quantity':1}]*21).status_code==422
    assert mail(c,[{'id':990003,'quantity':1}]).status_code==422


def test_policy_lock_wait_refuses_partial_writes(env):
    c,s,db,app=env;add_items(s,1)
    op=policy(c,item_id=991000).json()['operation_id']
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT revision FROM dnf_gm.catalog_policy_state WHERE id=1 FOR UPDATE')
        r=confirm(c,op,uuid.uuid4().hex);assert r.status_code in (500,503)
    assert scalar(db,'SELECT COUNT(*) FROM dnf_gm.catalog_policy_items')==0


def test_same_snapshot_cannot_race_policy_commit(env):
    c,s,db,app=env
    # A reader has an older REPEATABLE READ snapshot before policy changes.
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT COUNT(*) FROM dnf_gm.audit');q.fetchone()
        apply(c,enabled=False,item_id=990001)
        # Locking policy reads MUST see current state, not the older snapshot.
        with pytest.raises(HTTPException) as e:app.state.service.catalog.items([{'id':990001,'quantity':1}],q=q)
        assert e.value.status_code==422


def test_concurrent_confirms_serialize_and_invalidate_stale_batch(env):
    c,s,db,app=env;add_items(s,1)
    a=policy(c,item_id=991000).json()['operation_id'];b=policy(c,enabled=False,item_id=990001).json()['operation_id']
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT session_hash FROM dnf_gm.operations WHERE operation_id=%s',(a,));session=q.fetchone()['session_hash']
    def run(op):
        try:return app.state.service.confirm(session,op,uuid.uuid4().hex)['state']
        except HTTPException as e:return e.status_code
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,[a,b]))
    assert sorted(map(str,results))==['409','committed']
    assert scalar(db,'SELECT COUNT(*) FROM dnf_gm.audit')==1


def test_commit_succeeded_response_lost_is_queryable_never_replayed(env):
    c,s,db,app=env;add_items(s,1)
    op=policy(c,item_id=991000).json()['operation_id']
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT session_hash FROM dnf_gm.operations WHERE operation_id=%s',(op,));session=q.fetchone()['session_hash']
    from dnfgm.service import Service
    from dnfgm.db import Database
    import pymysql
    class LostResponse:
        def __init__(self,c):self.c=c
        def __getattr__(self,name):return getattr(self.c,name)
        def commit(self):
            self.c.commit()
            raise pymysql.OperationalError(2013,'synthetic response lost after COMMIT')
    flaky=Database(s,lambda:LostResponse(db.factory()))
    key=uuid.uuid4().hex
    with pytest.raises(HTTPException) as e:Service(flaky,s).confirm(session,op,key)
    assert e.value.status_code==503
    d=c.get(P+'/operations/'+op).json();assert d['status']=='committed' and d['result']['affected']==1
    assert app.state.service.confirm(session,op,key)==d['result']
    assert scalar(db,'SELECT COUNT(*) FROM dnf_gm.audit')==1
    assert scalar(db,'SELECT revision FROM dnf_gm.catalog_policy_state')==1


def test_verification_needs_separate_evidence_not_web_switch(env):
    c,s,db,app=env
    assert c.post(P+'/catalog/policy/preview',json={'enabled':True,'reason':'bad','verification_evidence':'forged'}).status_code==422
    # Only fixture maintenance principal inserts evidence, never a web feature.
    with db.connect() as con,con.cursor() as q:
        q.execute('INSERT INTO dnf_gm.catalog_policy_items VALUES(%s,990001,1,%s,0,%s)',(s.pvf_sha256,'隔离测试证据','synthetic fixture: no real client validation claim'));con.commit()
    row=c.get(P+'/catalog?state=verified').json()['items'][0]
    assert row['policy_state']=='verified' and row['id']==990001
    apply(c,enabled=False,item_id=990001)
    assert c.get(P+'/catalog?q=990001').json()['items'][0]['policy_state']=='blocked'
    apply(c,item_id=990001)
    assert c.get(P+'/catalog?q=990001').json()['items'][0]['policy_state']=='verified'


def test_optimized_search_matches_streaming_policy_for_every_filter(env):
    from contextlib import closing
    c,s,db,app=env;add_items(s)
    with db.connect() as con,con.cursor() as q:
        q.executemany('INSERT INTO dnf_gm.catalog_policy_items VALUES(%s,%s,%s,%s,0,%s)',[(s.pvf_sha256,991000+i,i%3!=0,'fixture override','fixture evidence' if i%7==0 else '') for i in range(30)]+[(s.pvf_sha256,990001,0,'fixture disabled','')]);con.commit()
    catalog=app.state.service.catalog
    with db.connect() as con,con.cursor() as q,closing(catalog.connect()) as index:
        _,overrides=catalog.policy(q,s.pvf_sha256)
        for state in ('','trial','blocked','verified'):
            for allowed_only in (False,True):
                for category in ('','material','special','equipment'):
                    filters=dict(q='',category=category,state=state,allowed_only=allowed_only)
                    expected=[i['id'] for i in catalog.rows(index,filters,overrides)]
                    for page in (1,2):
                        r=c.get(P+'/catalog',params={**filters,'page':page});assert r.status_code==200,r.text
                        d=r.json();assert d['total']==len(expected),(filters,d)
                        assert [i['id'] for i in d['items']]==expected[(page-1)*50:page*50],filters
