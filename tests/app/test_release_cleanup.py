"""API/transaction tests use synthetic manifests and an isolated MySQL lab only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pymysql
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from dnfgm import release_cleanup as rc
from dnfgm.release_files import atomic_json,canonical,read_json
from dnfgm.db import Database

P='/dnf-gm/api/v1'
C=P+'/release-cleanups'


@pytest.fixture
def clean(env,tmp_path,monkeypatch):
    client,s,db,app=env
    monkeypatch.setattr(rc,'ROOT_UID',os.getuid())
    s.cleanup_enabled=True;s.cleanup_manifest=str(tmp_path/'manifest.json');s.cleanup_dir=str(tmp_path/'cleanup')
    for sub in ('inbox','results'):(Path(s.cleanup_dir)/sub).mkdir(parents=True)
    items=[]
    for name in ('old-a','old-b'):
        d={'name':name,'device':1,'inode':2,'fingerprint':'f'*64,'allocated_bytes':8192,'entries':10,'expires_at':int(time.time())+300}
        items.append({'name':name,'eligible':True,'descriptor':d,'ticket':'b'*64})
    items.append({'name':'current','eligible':False,'reason':'protected_release'})
    atomic_json(s.cleanup_manifest,{'state':'ok','collected_at':time.time(),'items':items})
    return env


def preview(client,names=None):
    r=client.post(C+'/preview',json={'names':names or ['old-a'],'reason':'隔离旧包测试'})
    assert r.status_code==200,r.text
    return r.json()['operation_id']


def confirm(client,op,key=None):
    return client.post(C+'/'+op+'/confirm',json={'idempotency_key':key or uuid.uuid4().hex,'confirmation':'删除旧GM产物'})


def row(db,sql,args=()):
    with db.connect() as c,c.cursor() as q:q.execute(sql,args);return q.fetchone()


def session(db,op):return row(db,'SELECT session_hash FROM dnf_gm.operations WHERE operation_id=%s',(op,))['session_hash']


def test_disabled_and_unavailable_list_fail_closed(env):
    c,s,_,_=env
    assert c.get(C).json()['state']=='disabled'
    assert c.post(C+'/preview',json={'names':['old'],'reason':'x'}).status_code==403
    s.cleanup_enabled=True;s.cleanup_manifest='/no-such-fixture-manifest'
    assert c.get(C).json()['state']=='unavailable'


def test_auth_csrf_origin_recent_password_and_phrase(clean):
    c,s,db,app=clean
    with TestClient(app) as anonymous:assert anonymous.get(C).status_code==401
    op=preview(c)
    assert c.post(C+'/'+op+'/confirm',json={'idempotency_key':'x'*32,'confirmation':'yes'}).status_code==422
    assert c.post(C+'/'+op+'/confirm',headers={'X-CSRF-Token':'wrong'},json={'idempotency_key':'x'*32,'confirmation':'删除旧GM产物'}).status_code==403
    assert c.post(C+'/preview',headers={'Origin':'https://untrusted.test'},json={'names':['old-a'],'reason':'x'}).status_code==403
    with db.connect() as con,con.cursor() as q:q.execute('UPDATE dnf_gm.sessions SET authenticated_at=1');con.commit()
    r=confirm(c,op);assert r.status_code==403 and '重新认证' in r.text
    assert not list((Path(s.cleanup_dir)/'inbox').iterdir())


@pytest.mark.parametrize('names',[['../outside'],['old-a','old-a'],['current'],['missing']])
def test_selection_rejected_without_preview_or_writes(clean,names):
    c,s,db,_=clean
    assert c.post(C+'/preview',json={'names':names,'reason':'x'}).status_code in (409,422)
    assert row(db,'SELECT COUNT(*) n FROM dnf_gm.operations')['n']==0


def test_stale_manifest_resources_and_expired_preview(clean):
    c,s,db,_=clean;op=preview(c)
    with db.connect() as con,con.cursor() as q:q.execute('UPDATE dnf_gm.operations SET expires_at=1 WHERE operation_id=%s',(op,));con.commit()
    assert confirm(c,op).status_code==409
    m=read_json(s.cleanup_manifest);m['collected_at']=1;atomic_json(s.cleanup_manifest,m)
    assert c.get(C).json()['state']=='unavailable'
    assert c.post(C+'/preview',json={'names':['old-a'],'reason':'x'}).status_code==409
    p=Path(s.status_file);d=json.loads(p.read_text());d['mem_available_mib']=255;p.write_text(json.dumps(d))
    assert c.post(C+'/preview',json={'names':['old-a'],'reason':'x'}).status_code==409
    assert not list((Path(s.cleanup_dir)/'inbox').iterdir())


def test_preview_query_hides_tickets_and_never_dispatches(clean):
    c,s,db,_=clean
    assert 'ticket' not in c.get(C).text
    op=preview(c)
    for url in (C+'/'+op,P+'/operations/'+op):
        r=c.get(url);assert r.status_code==200 and 'ticket' not in r.text and 'fingerprint' not in r.text
    assert not list((Path(s.cleanup_dir)/'inbox').iterdir())
    assert row(db,'SELECT COUNT(*) n FROM dnf_gm.audit')['n']==0
    # Dedicated phrase and resource/queue protocol cannot be bypassed.
    r=c.post(P+'/operations/'+op+'/confirm',json={'idempotency_key':'g'*32})
    assert r.status_code==409,r.text


def test_confirm_audits_before_dispatch_and_has_separate_receipt(clean):
    c,s,db,_=clean;op=preview(c);key='k'*32
    r=confirm(c,op,key);assert r.status_code==200,r.text
    assert r.json()['status']=='queued' and r.json()['result'] is None
    inbox=Path(s.cleanup_dir)/'inbox'/(op+'.json');req=read_json(inbox)
    assert req['operation_id']==op and 'ticket' in req['items'][0]
    audit=row(db,'SELECT * FROM dnf_gm.audit WHERE operation_id=%s',(op,))
    assert json.loads(audit['result_json'])['state']=='queued' and 'ticket' not in audit['request_json']
    assert confirm(c,op,key).status_code==200
    assert confirm(c,op,'other-key-'+'x'*20).status_code==409
    assert row(db,'SELECT COUNT(*) n FROM dnf_gm.audit')['n']==1
    result={'operation_id':op,'request_sha256':hashlib.sha256(canonical(req)).hexdigest(),'state':'completed','items':[{'name':'old-a','state':'removed'}]}
    atomic_json(Path(s.cleanup_dir)/'results'/(op+'.json'),result)
    inbox.unlink()
    assert c.get(C+'/'+op).json()['result']==result
    assert c.post(C+'/'+op+'/dispatch').json()['result']==result
    assert not inbox.exists()
    assert row(db,"SELECT cera FROM taiwan_billing.cash_cera WHERE account='900001'")['cera']==1000


def test_same_key_other_parameters_and_new_session_rejected(clean):
    c,s,db,_=clean;op=preview(c);other=preview(c,['old-b']);key='k'*32
    assert confirm(c,op,key).status_code==200
    assert confirm(c,other,key).status_code==409
    with pytest.raises(HTTPException) as e:rc.ReleaseCleanup(db,s).confirm('foreign-session',other,'f'*32)
    assert e.value.status_code==404
    assert len(list((Path(s.cleanup_dir)/'inbox').iterdir()))==1


def test_lost_dispatch_does_not_forge_success_and_can_only_redispatch_original(clean,monkeypatch):
    c,s,db,_=clean;op=preview(c)
    with monkeypatch.context() as m:
        m.setattr(rc,'atomic_json',lambda *a,**kw:(_ for _ in ()).throw(OSError('fixture disk full')))
        assert confirm(c,op).status_code==503
    d=c.get(C+'/'+op).json();assert d['status']=='queued' and d['retry_dispatch_allowed']
    assert not list((Path(s.cleanup_dir)/'inbox').iterdir())
    assert c.post(C+'/'+op+'/dispatch').status_code==200
    assert row(db,'SELECT COUNT(*) n FROM dnf_gm.audit')['n']==1


@pytest.mark.parametrize('committed',[True,False])
def test_commit_response_lost_has_no_dispatch_until_explicit_recovery(clean,committed):
    c,s,db,_=clean;op=preview(c);sid=session(db,op)
    class Lost:
        def __init__(self,c):self.c=c
        def __getattr__(self,n):return getattr(self.c,n)
        def commit(self):
            if committed:self.c.commit()
            raise pymysql.OperationalError(2013,'synthetic lost commit response')
    flaky=Database(s,lambda:Lost(db.factory()))
    with pytest.raises(HTTPException) as e:rc.ReleaseCleanup(flaky,s).confirm(sid,op,'l'*32)
    assert e.value.status_code==503 and not list((Path(s.cleanup_dir)/'inbox').iterdir())
    d=c.get(C+'/'+op).json();assert d['status']==('queued' if committed else 'preview')
    if committed:
        assert c.post(C+'/'+op+'/dispatch').status_code==200
        assert c.post(C+'/'+op+'/cancel-preview').status_code==409
    else:
        assert c.post(C+'/'+op+'/dispatch').status_code==409
        assert c.post(C+'/'+op+'/cancel-preview').json()['status']=='cancelled'
        assert confirm(c,op,'l'*32).status_code==409


def test_cancel_preview_serializes_with_confirm_and_audits(clean):
    c,s,db,_=clean;op=preview(c);sid=session(db,op);service=rc.ReleaseCleanup(db,s)
    def run(action):
        try:return (service.cancel_preview(op) if action=='cancel' else service.confirm(sid,op,'r'*32))['status']
        except HTTPException as e:return e.status_code
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,['cancel','confirm']))
    assert 409 in results and ('cancelled' in results or 'queued' in results)
    assert row(db,'SELECT COUNT(*) n FROM dnf_gm.audit')['n']==1
    if 'cancelled' in results:
        assert not list((Path(s.cleanup_dir)/'inbox').iterdir())
        assert c.post(C+'/'+op+'/cancel-preview').json()['status']=='cancelled'


def test_same_confirmation_concurrently_only_one_audit_and_request(clean):
    c,s,db,_=clean;op=preview(c);sid=session(db,op);svc=rc.ReleaseCleanup(db,s)
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:svc.confirm(sid,op,'p'*32),range(2)))
    assert all(r['status']=='queued' for r in results)
    assert row(db,'SELECT COUNT(*) n FROM dnf_gm.audit')['n']==1
    assert len(list((Path(s.cleanup_dir)/'inbox').iterdir()))==1


def test_untrusted_or_mismatched_receipt_blocks_redispatch(clean):
    c,s,_,_=clean;op=preview(c);assert confirm(c,op).status_code==200
    inbox=Path(s.cleanup_dir)/'inbox'/(op+'.json');inbox.unlink()
    receipt=Path(s.cleanup_dir)/'results'/(op+'.json')
    atomic_json(receipt,{'operation_id':op,'state':'completed','request_sha256':'0'*64})
    d=c.get(C+'/'+op).json();assert d['receipt_error'] and not d['retry_dispatch_allowed']
    assert c.post(C+'/'+op+'/dispatch').json()['receipt_error']
    receipt.chmod(0o666)
    assert c.get(C+'/'+op).json()['receipt_error'] and not inbox.exists()


def test_actual_minimum_grants_with_synthetic_requests(clean):
    from dnfgm.app import create_app
    from dnfgm.security import PASSWORDS
    _,s,rootdb,_=clean
    spec=importlib.util.spec_from_file_location('cleanup_grants',Path(__file__).resolve().parents[2]/'deploy/grants.py')
    grants=importlib.util.module_from_spec(spec);spec.loader.exec_module(grants)
    sql=grants.bootstrap_sql({'db_user':'cleanup_minimal','db_password':'isolated-fixture-password','db_account_host':'localhost'},PASSWORDS.hash('fixture-admin-password'))
    with rootdb.connect() as con,con.cursor() as q:
        q.execute('DROP DATABASE dnf_gm');q.execute("DROP USER IF EXISTS 'cleanup_minimal'@'localhost'")
        for statement in sql.split(';'):
            if statement.strip():q.execute(statement)
        con.commit()
    def factory():return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'],user='cleanup_minimal',password='isolated-fixture-password',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    limited=Database(s,factory)
    with TestClient(create_app(s,limited)) as c:
        c.headers['Origin']='http://testserver'
        r=c.post(P+'/auth/login',json={'username':'admin','password':'fixture-admin-password'});assert r.status_code==200
        c.headers['X-CSRF-Token']=r.json()['csrf'];op=preview(c)
        assert confirm(c,op).status_code==200
        assert c.get(C+'/'+op).json()['status']=='queued'
        cancelled=preview(c,['old-b']);assert c.post(C+'/'+cancelled+'/cancel-preview').json()['status']=='cancelled'
        for sql in ('DELETE FROM dnf_gm.audit','DROP TABLE dnf_gm.operations'):
            with limited.connect() as con,con.cursor() as q:
                with pytest.raises(pymysql.OperationalError):q.execute(sql)


def test_audit_insert_failure_rolls_back_queue_and_records_failed_attempt(clean):
    c,s,db,_=clean;op=preview(c);sid=session(db,op)
    class AuditFailureCursor:
        def __init__(self,q):self.q=q
        def __getattr__(self,n):return getattr(self.q,n)
        def __enter__(self):self.q.__enter__();return self
        def __exit__(self,*a):return self.q.__exit__(*a)
        def execute(self,sql,*a,**kw):
            if sql.startswith('INSERT INTO dnf_gm.audit'):raise pymysql.OperationalError(1142,'synthetic denied audit')
            return self.q.execute(sql,*a,**kw)
    class AuditFailureConnection:
        def __init__(self,c):self.c=c
        def __getattr__(self,n):return getattr(self.c,n)
        def cursor(self):return AuditFailureCursor(self.c.cursor())
    broken=Database(s,lambda:AuditFailureConnection(db.factory()))
    with pytest.raises(pymysql.OperationalError):rc.ReleaseCleanup(broken,s).confirm(sid,op,'a'*32)
    assert row(db,'SELECT status,idempotency_key FROM dnf_gm.operations WHERE operation_id=%s',(op,))=={'status':'preview','idempotency_key':None}
    assert row(db,'SELECT COUNT(*) n FROM dnf_gm.audit')['n']==0
    assert row(db,'SELECT COUNT(*) n FROM dnf_gm.failures WHERE operation_id=%s',(op,))['n']==1
    assert not list((Path(s.cleanup_dir)/'inbox').iterdir())


def test_lock_wait_cannot_dispatch_before_transaction_acquires_operation(clean):
    c,s,db,_=clean;op=preview(c);sid=session(db,op)
    with db.connect() as held,held.cursor() as q:
        q.execute('SELECT * FROM dnf_gm.operations WHERE operation_id=%s FOR UPDATE',(op,))
        with pytest.raises(pymysql.OperationalError) as e:rc.ReleaseCleanup(db,s).confirm(sid,op,'w'*32)
        # The production query budget (1.5s) can fire before InnoDB
        # lock_wait_timeout (2s); either must leave the outbox untouched.
        assert e.value.args[0] in (1205,3024)
    assert row(db,'SELECT status FROM dnf_gm.operations WHERE operation_id=%s',(op,))['status']=='preview'
    assert not list((Path(s.cleanup_dir)/'inbox').iterdir())
