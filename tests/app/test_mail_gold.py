"""Gold delivery SQL/API guarantees; no simulated client receipt."""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import pytest
from dnfgm.service import Service
from dnfgm.security import COOKIE, digest

P='/dnf-gm/api/v1'
def preview(client, **kw):
    data=dict(action='mail',uid=900001,charac_no=900001,items=[],gold=1000,
              reason='isolated gold mail test',message='GM rewards')
    data.update(kw)
    return client.post(P+'/operations/preview',json=data)
def confirm(c,op,key='gold-delivery-idempotency-001'):
    return c.post(P+'/operations/'+op+'/confirm',json={'idempotency_key':key})
def rows(db):
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT * FROM taiwan_cain_2nd.postal ORDER BY postal_id')
        return list(q.fetchall())

@pytest.mark.parametrize('gold,items',[(1,[]),(100000000,[]),(0,[{'id':990002,'quantity':2}]),(1000,[{'id':990002,'quantity':2},{'id':990001,'quantity':1}]),(1000,[{'id':990002,'quantity':1}]*20)])
def test_delivery_gold_once_and_result_audit_idempotency(env,gold,items):
    c,s,db,app=env
    r=preview(c,gold=gold,items=items);assert r.status_code==200,r.text
    op=r.json()['operation_id'];assert r.json()['preview']['gold']==gold
    first=confirm(c,op);assert first.status_code==200,first.text
    assert first.json()['gold']==gold and first.json()['client_verified'] is False
    assert confirm(c,op).json()==first.json()
    postal=rows(db);assert len(postal)==max(1,len(items))
    assert [r['gold'] for r in postal]==[gold]+[0]*(len(postal)-1)
    if not items:assert postal[0]['item_id']==0 and postal[0]['add_info']==0
    r=c.get(P+'/operations/'+op).json()
    assert sum(m['gold'] for m in r['delivery_records'])==gold
    assert r['result']['gold']==gold
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT request_json,result_json FROM dnf_gm.audit WHERE operation_id=%s',(op,));audit=q.fetchone()
        assert json.loads(audit['request_json'])['gold']==gold
        assert json.loads(audit['result_json'])['gold']==gold
        q.execute('SELECT COUNT(*) n FROM taiwan_cain_2nd.letter');assert q.fetchone()['n']==1

@pytest.mark.parametrize('gold',[-1,100000001,1.5,True,'1000',None])
def test_invalid_gold_rejected_at_api(env,gold):
    c,s,db,app=env
    r=preview(c,gold=gold);assert r.status_code==422
    assert any(e['loc']==['body','gold'] for e in r.json()['detail'])
    assert rows(db)==[]

@pytest.mark.parametrize('updates',[{'gold':0},{'charac_no':900002},{'gold':1000,'items':[{'id':990003,'quantity':1}]},{'action':'ban'},{'action':'currency','currency':'cera','delta':1}])
def test_empty_wrong_owner_special_or_nonmail_gold_rejected(env,updates):
    c,s,db,app=env
    assert preview(c,**updates).status_code in (409,422)
    assert not rows(db)

@pytest.mark.parametrize('stage',['postal','audit'])
def test_transaction_failure_does_not_leave_partial_mail(env,stage):
    c,s,db,app=env
    op=preview(c).json()['operation_id']
    with db.connect() as con,con.cursor() as q:
        table='taiwan_cain_2nd.postal' if stage=='postal' else 'dnf_gm.audit'
        q.execute(f"CREATE TRIGGER {table.split('.')[0]}.gold_fail BEFORE INSERT ON {table} FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='gold injected failure'")
    assert confirm(c,op).status_code==500
    assert rows(db)==[]
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM taiwan_cain_2nd.letter');assert q.fetchone()['n']==0
    assert c.get(P+'/operations/'+op).json()['status']=='preview'

@pytest.mark.parametrize('stale',['pvf','status','deleted','preview-gold'])
def test_confirmation_revalidates_gold_target_and_versions(env,stale):
    c,s,db,app=env;op=preview(c).json()['operation_id']
    if stale=='pvf':s.pvf_sha256='b'*64
    elif stale=='status':
        p=Path(s.status_file);d=json.loads(p.read_text());d['collected_at']=0;p.write_text(json.dumps(d))
    else:
        with db.connect() as con,con.cursor() as q:
            if stale=='deleted':q.execute('UPDATE taiwan_cain.charac_info SET delete_flag=1 WHERE charac_no=900001')
            else:q.execute("UPDATE dnf_gm.operations SET request_json=REPLACE(request_json,'\"gold\":1000','\"gold\":2000') WHERE operation_id=%s",(op,))
            con.commit()
    assert confirm(c,op).status_code in (409,503)
    assert not rows(db)

def test_template_with_supplemental_gold_frozen_in_request_not_template(env):
    c,s,db,app=env
    r=c.post(P+'/gift-templates',json={'name':'Gold companion','enabled':True,'expected_version':0,'items':[{'id':990002,'quantity':2}]});assert r.status_code==200
    tid=r.json()['id'];op=preview(c,template_id=tid,template_version=1).json()['operation_id']
    assert confirm(c,op).status_code==200
    assert rows(db)[0]['gold']==1000
    assert 'gold' not in c.get(P+'/gift-templates').json()['items'][0]['rewards']

def test_old_mail_preview_without_gold_remains_zero_compatible(env):
    c,s,db,app=env
    op=preview(c,gold=0,items=[{'id':990002,'quantity':1}]).json()['operation_id']
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT request_json,preview_json FROM dnf_gm.operations WHERE operation_id=%s',(op,));r=q.fetchone()
        a,b=json.loads(r['request_json']),json.loads(r['preview_json']);a.pop('gold');b.pop('gold')
        q.execute('UPDATE dnf_gm.operations SET request_json=%s,preview_json=%s WHERE operation_id=%s',(json.dumps(a),json.dumps(b),op));con.commit()
    assert confirm(c,op).status_code==200
    assert rows(db)[0]['gold']==0

def test_concurrent_same_operation_commits_gold_once(env):
    c,s,db,app=env
    op=preview(c).json()['operation_id'];session=digest(c.cookies.get(COOKIE))
    service=Service(db,s)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(service.confirm,session,op,'gold-concurrent-same-key') for _ in range(2)]
        results=[f.result(timeout=10) for f in futures]
    assert results[0]==results[1]
    assert len(rows(db))==1 and rows(db)[0]['gold']==1000


def test_commit_response_lost_result_query_never_replays(env):
    c,s,db,app=env;op=preview(c).json()['operation_id']
    class LostReply:
        def __init__(self,connection):self.connection=connection
        def __getattr__(self,name):return getattr(self.connection,name)
        def commit(self):
            self.connection.commit()
            raise OSError('synthetic successful commit, response lost')
    class FaultDb:
        @contextmanager
        def connect(self):
            with db.connect() as conn:yield LostReply(conn)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        Service(FaultDb(),s).confirm(digest(c.cookies.get(COOKIE)),op,'gold-lost-commit-reply')
    assert error.value.status_code==503
    assert c.get(P+'/operations/'+op).json()['result']['gold']==1000
    assert confirm(c,op,'gold-lost-commit-reply').status_code==200
    assert len(rows(db))==1
