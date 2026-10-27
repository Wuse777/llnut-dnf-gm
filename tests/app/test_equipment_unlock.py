import json
import struct
import time
import zlib
import pytest
from dnfgm.equipment_unlock import decode, WAIT_SECONDS
P='/dnf-gm/api/v1'

def prepare(env,online=0):
    c,s,db,app=env
    raw=bytearray(800)
    struct.pack_into('<IB',raw,0,int(time.time())-100,2)
    struct.pack_into('<IB',raw,8,int(time.time())-200,2)
    struct.pack_into('<IB',raw,16,int(time.time())-300,1)
    blob=struct.pack('<I',800)+zlib.compress(raw)
    with db.connect() as con,con.cursor() as q:
        q.execute('UPDATE taiwan_login.login_account_3 SET login_status=%s WHERE m_id=900001',(online,))
        q.execute('INSERT INTO taiwan_cain_2nd.charac_item_lock_info VALUES(900001,%s)',(blob,));con.commit()
    return blob

def preview(c,**kw):
    return c.post(P+'/operations/preview',json=dict(action='equipment-unlock',uid=900001,charac_no=900001,reason='fixture',lock_keys=[1],**kw))

def confirm(c,op,key='unlock-fixture-operation-key'):
    return c.post(P+'/operations/'+op+'/confirm',json={'idempotency_key':key})

def read_blob(db):
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT item_lock_info FROM taiwan_cain_2nd.charac_item_lock_info WHERE charac_no=900001');return q.fetchone()['item_lock_info']

def test_query_and_atomic_idempotent_unlock(env):
    c,s,db,app=env;original=prepare(env)
    d=c.get(P+'/characters/900001/unlock-requests').json()
    assert len(d['items'])==3 and d['login_status']==0
    assert 'item_lock_info' not in d
    r=preview(c);assert r.status_code==200,r.text
    op=r.json()['operation_id'];r=confirm(c,op);assert r.status_code==200,r.text
    assert r.json()['state']=='requests_expired_pending_game_load'
    assert confirm(c,op).json()==r.json()
    assert confirm(c,op,'unlock-fixture-different-key').status_code==409
    before,_=decode(original);after,records=decode(read_blob(db))
    assert before[4:]==after[4:] and records[0]['due_at']<time.time()
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT * FROM dnf_gm.audit WHERE operation_id=%s',(op,));rows=q.fetchall()
        assert len(rows)==1 and json.loads(rows[0]['result_json'])['lock_keys']==[1]
    assert c.get(P+'/operations/'+op).json()['status']=='committed'

@pytest.mark.parametrize('online',[1,2,None])
def test_online_unknown_rejected(env,online):
    c,s,db,app=env;original=prepare(env,online if online is not None else 0)
    if online is None:
        with db.connect() as con,con.cursor() as q:q.execute('DELETE FROM taiwan_login.login_account_3');con.commit()
    assert c.get(P+'/characters/900001/unlock-requests').status_code==200
    assert preview(c).status_code==409
    assert read_blob(db)==original

@pytest.mark.parametrize('change',['online','blob','deleted','engine','audit','owner'])
def test_confirmation_rechecks_and_rolls_back(env,change):
    c,s,db,app=env;original=prepare(env);op=preview(c).json()['operation_id']
    with db.connect() as con,con.cursor() as q:
        if change=='online':q.execute('UPDATE taiwan_login.login_account_3 SET login_status=1')
        elif change=='blob':q.execute('UPDATE taiwan_cain_2nd.charac_item_lock_info SET item_lock_info=%s',(original+b'x',))
        elif change=='deleted':q.execute('UPDATE taiwan_cain.charac_info SET delete_flag=1 WHERE charac_no=900001')
        elif change=='owner':q.execute('UPDATE taiwan_cain.charac_info SET m_id=900002 WHERE charac_no=900001')
        elif change=='engine':q.execute('ALTER TABLE taiwan_cain_2nd.charac_item_lock_info ENGINE=MyISAM')
        else:q.execute("CREATE TRIGGER dnf_gm.unlock_fail BEFORE INSERT ON dnf_gm.audit FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture failure'")
        con.commit()
    assert confirm(c,op).status_code==(500 if change=='audit' else 409)
    assert read_blob(db)==(original+b'x' if change=='blob' else original)
    assert c.get(P+'/operations/'+op).json()['status']=='preview'

@pytest.mark.parametrize('keys',[[],[0],[101],[1,1],[True],[3],[4]])
def test_invalid_keys(env,keys):
    c,s,db,app=env;prepare(env)
    payload=dict(action='equipment-unlock',uid=900001,charac_no=900001,reason='fixture',lock_keys=keys)
    assert c.post(P+'/operations/preview',json=payload).status_code in (409,422)

def test_mixed_parameters_rejected(env):
    c,s,db,app=env;prepare(env)
    assert preview(c,gold=1).status_code==422
    assert preview(c,items=[{'id':990002,'quantity':1}]).status_code==422
    assert preview(c,currency='cera',delta=1).status_code==422

def test_unsupported_snapshot_fails_closed(env):
    c,s,db,app=env;prepare(env)
    with db.connect() as con,con.cursor() as q:q.execute("UPDATE taiwan_cain_2nd.charac_item_lock_info SET item_lock_info='bad'");con.commit()
    d=c.get(P+'/characters/900001/unlock-requests').json()
    assert d['state']=='unsupported' and not d['write_enabled']
    assert preview(c).status_code==409

def test_unlock_auth_activation_and_cross_action_guard(env):
    c,s,db,app=env;original=prepare(env)
    assert c.post(P+'/operations/preview',json={'action':'currency','uid':900001,'currency':'cera','delta':1,'reason':'fixture','lock_keys':[1]}).status_code==422
    op=preview(c).json()['operation_id'];s.writes=tuple(x for x in s.writes if x!='equipment-unlock')
    assert confirm(c,op).status_code==403 and read_blob(db)==original
    c.cookies.clear()
    assert c.get(P+'/characters/900001/unlock-requests').status_code==401


def test_same_operation_concurrent_confirm_expires_once(env):
    from concurrent.futures import ThreadPoolExecutor
    from dnfgm.service import Service
    from dnfgm.security import COOKIE,digest
    c,s,db,app=env;prepare(env);op=preview(c).json()['operation_id']
    session=digest(c.cookies.get(COOKIE));service=Service(db,s)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(service.confirm,session,op,'unlock-concurrent-fixed-key') for _ in range(2)]
        results=[f.result(timeout=10) for f in futures]
    assert results[0]==results[1]
    with db.connect() as con,con.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM dnf_gm.audit WHERE operation_id=%s',(op,));assert q.fetchone()['n']==1
