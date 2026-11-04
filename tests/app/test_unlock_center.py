"""Synthetic lock-key mapping, atomic multi-role expiration and recovery."""
import json
import struct
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_equipment_unlock import prepare,preview,confirm,read_blob,P
from test_character_detail import slot,blob
from dnfgm.equipment_unlock import decode
from dnfgm.security import COOKIE,digest
from dnfgm.service import Service


def linked(key,item=990001):
    raw=bytearray(slot(item));raw[20]=key;return bytes(raw)


def seed(env):
    original=prepare(env);client,settings,db,_=env
    with db.connect() as c,c.cursor() as q:
        q.execute('INSERT INTO taiwan_cain_2nd.inventory(charac_no,inventory,equipslot) VALUES(%s,%s,%s)',(900001,blob(bytes(61),linked(2)),blob(linked(1))))
        q.execute("INSERT INTO taiwan_cain_2nd.charac_inven_expand(charac_no,cargo,jewel,switch_equipslot,expand_equipslot,redeem_info) VALUES(%s,%s,X'',X'',X'',X'')",(900001,blob(linked(3))))
        q.execute("INSERT INTO taiwan_cain.charac_info(m_id,charac_no,charac_name,element_resist,spec_property,VIP) VALUES(900001,900003,'BatchFixture','','','0')")
        q.execute('INSERT INTO taiwan_cain_2nd.charac_item_lock_info VALUES(900003,%s)',(original,));c.commit()
    return original


def batch(client,targets=None,**kw):
    return client.post(P+'/unlock-batches/preview',json={'reason':'synthetic test only','targets':targets or [{'uid':900001,'charac_no':900003,'lock_keys':[2]},{'uid':900001,'charac_no':900001,'lock_keys':[1]}],**kw})


def stored(db,cid):
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT item_lock_info FROM taiwan_cain_2nd.charac_item_lock_info WHERE charac_no=%s',(cid,));return q.fetchone()['item_lock_info']


def count(db,table):
    assert table in ('audit','operations')
    with db.connect() as c,c.cursor() as q:q.execute('SELECT COUNT(*) n FROM dnf_gm.'+table);return q.fetchone()['n']


def test_map_by_lock_key_not_slot_or_itemid_and_track_processing(env):
    client,_,db,_=env;original=seed(env)
    d=client.get(P+'/characters/900001/unlock-requests').json();a,b,c=d['items']
    assert [i['mapping_state'] for i in d['items']]==['matched']*3
    assert a['item']['id']==b['item']['id'] and a['item']['slot']==0 and b['item']['slot']==1
    assert [i['item']['container'] for i in d['items']]==['equipment','backpack','warehouse']
    assert a['item']['name']=='测试装备' and not a['managed_operation']
    p=preview(client);assert p.status_code==200,p.text
    op=p.json()['operation_id'];assert p.json()['preview']['requests'][0]['item']['id']==990001
    assert confirm(client,op).status_code==200
    after=client.get(P+'/characters/900001/unlock-requests').json()['items']
    assert after[0]['expired'] and after[0]['managed_operation']==op and after[1]['managed_operation'] is None
    assert read_blob(db)!=original


@pytest.mark.parametrize('kind',['duplicate','corrupt','missing','unmapped'])
def test_ambiguous_or_incomplete_mapping_is_never_claimed_unique(env,kind):
    client,_,db,_=env;seed(env)
    with db.connect() as c,c.cursor() as q:
        if kind=='missing':q.execute('DELETE FROM taiwan_cain_2nd.charac_inven_expand WHERE charac_no=900001')
        value=blob(linked(1)) if kind=='duplicate' else b'broken' if kind=='corrupt' else blob(linked(0))
        q.execute('UPDATE taiwan_cain_2nd.inventory SET inventory=%s,equipslot=%s WHERE charac_no=900001',(value,blob(linked(1 if kind!='unmapped' else 0))));c.commit()
    first=client.get(P+'/characters/900001/unlock-requests').json()['items'][0]
    assert first['mapping_state']=={'duplicate':'ambiguous','corrupt':'partial','missing':'partial','unmapped':'unmapped'}[kind]
    if kind=='duplicate':assert len(first['candidates'])==2 and first['item'] is None


def test_single_confirmation_rejects_storage_change_and_old_preview(env):
    client,_,db,_=env;original=seed(env);p=preview(client).json()
    with db.connect() as c,c.cursor() as q:
        q.execute('UPDATE taiwan_cain_2nd.inventory SET equipslot=%s WHERE charac_no=900001',(blob(linked(1,1234)),));c.commit()
    assert confirm(client,p['operation_id']).status_code==409 and read_blob(db)==original
    p=preview(client).json()
    with db.connect() as c,c.cursor() as q:
        d=p['preview'];d.pop('inventory_fingerprint')
        q.execute('UPDATE dnf_gm.operations SET preview_json=%s WHERE operation_id=%s',(json.dumps(d),p['operation_id']));c.commit()
    assert confirm(client,p['operation_id'],'old-preview-no-inventory-key').status_code==409


def test_batch_atomic_results_history_and_idempotency(env):
    client,_,db,_=env;original=seed(env);r=batch(client);assert r.status_code==200,r.text
    p=r.json();assert p['preview']['role_count']==2 and p['preview']['request_count']==2
    op=p['operation_id'];r=confirm(client,op);assert r.status_code==200,r.text
    assert len(r.json()['targets'])==2 and r.json()['atomic']
    assert confirm(client,op).json()==r.json() and confirm(client,op,'different-idempotency-key').status_code==409
    for cid,key in [(900001,1),(900003,2)]:
        before,_=decode(original);after,records=decode(stored(db,cid));offset=(key-1)*8
        assert before[:offset]==after[:offset] and before[offset+4:]==after[offset+4:]
        assert next(i for i in records if i['lock_key']==key)['due_at']<time.time()
    assert count(db,'audit')==3
    audit=client.get(P+'/audit?uid=900001').json()['items'];assert len(audit)==2
    assert {json.loads(a['result_json'])['operation_id'] for a in audit}=={op}
    assert client.get(P+'/operations/'+op).json()['result']==r.json()


@pytest.mark.parametrize('change',['inventory','lock','online','owner','deleted','name','audit','engine','disabled','target_restriction','expiry'])
def test_batch_any_failure_rolls_back_all_targets(env,change):
    client,s,db,_=env;original=seed(env);p=batch(client).json();op=p['operation_id']
    with db.connect() as c,c.cursor() as q:
        if change=='inventory':q.execute('INSERT INTO taiwan_cain_2nd.inventory(charac_no,inventory,equipslot) VALUES(900003,%s,%s)',(blob(linked(2)),blob(bytes(61))))
        elif change=='lock':q.execute('UPDATE taiwan_cain_2nd.charac_item_lock_info SET item_lock_info=%s WHERE charac_no=900003',(original+b'bad',))
        elif change=='online':q.execute('UPDATE taiwan_login.login_account_3 SET login_status=1')
        elif change=='owner':q.execute('UPDATE taiwan_cain.charac_info SET m_id=900002 WHERE charac_no=900003')
        elif change=='deleted':q.execute('UPDATE taiwan_cain.charac_info SET delete_flag=1 WHERE charac_no=900003')
        elif change=='name':q.execute("UPDATE taiwan_cain.charac_info SET charac_name='Changed' WHERE charac_no=900003")
        elif change=='audit':q.execute("CREATE TRIGGER dnf_gm.unlock_batch_fail BEFORE INSERT ON dnf_gm.audit FOR EACH ROW BEGIN IF NEW.target_uid IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic failure'; END IF; END")
        elif change=='engine':q.execute('ALTER TABLE taiwan_cain_2nd.inventory ENGINE=MyISAM')
        elif change=='disabled':s.writes=()
        elif change=='target_restriction':s.test_uids=(900002,)
        elif change=='expiry':q.execute('UPDATE dnf_gm.operations SET expires_at=1 WHERE operation_id=%s',(op,))
        c.commit()
    r=confirm(client,op);assert r.status_code== (500 if change=='audit' else 403 if change in ('disabled','target_restriction') else 409),r.text
    assert stored(db,900001)==original
    assert stored(db,900003)==(original+b'bad' if change=='lock' else original)
    assert count(db,'audit')==0
    assert client.get(P+'/operations/'+op).json()['status']=='preview'


@pytest.mark.parametrize('target',[{'uid':900002,'charac_no':900001,'lock_keys':[1]}, {'uid':900001,'charac_no':900001,'lock_keys':[1,1]}, {'uid':900001,'charac_no':900001,'lock_keys':[True]}, {'uid':900001,'charac_no':900001,'lock_keys':[101]}, {'uid':900001,'charac_no':900001,'lock_keys':[3]}])
def test_invalid_batch_targets(env,target):
    client,_,_,_=env;seed(env);assert batch(client,[target]).status_code in (409,422)


def test_batch_validation_auth_and_csrf(env):
    client,_,db,_=env;seed(env)
    a={'uid':900001,'charac_no':900001,'lock_keys':[1]}
    assert batch(client,[a,a]).status_code==422
    assert batch(client,reason=' ').status_code==422
    assert batch(client,gold=100).status_code==422
    assert client.post(P+'/unlock-batches/preview',json={'targets':[a]*21,'reason':'test'}).status_code==422
    assert client.post(P+'/unlock-batches/preview',headers={'X-CSRF-Token':'bad'},json={'targets':[a],'reason':'test'}).status_code==403
    assert count(db,'audit')==0
    client.cookies.clear();assert client.get(P+'/unlock-requests').status_code==401
    assert batch(client).status_code==401


def test_batch_concurrent_confirmation_once(env):
    client,s,db,_=env;seed(env);op=batch(client).json()['operation_id'];session=digest(client.cookies.get(COOKIE));service=Service(db,s)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(service.confirm,session,op,'batch-concurrent-fixed-key') for _ in range(2)]
        results=[f.result(timeout=10) for f in futures]
    assert results[0]==results[1] and count(db,'audit')==3


def test_list_search_filters_and_pagination_after_empty_page(env):
    client,_,db,_=env;original=seed(env)
    d=client.get(P+'/unlock-requests').json();assert [i['charac_no'] for i in d['items']]==[900001,900003]
    assert 'item_lock_info' not in json.dumps(d)
    assert len(client.get(P+'/unlock-requests?q=GM测试角色').json()['items'])==1
    assert len(client.get(P+'/unlock-requests?q=gm_m0_fixture').json()['items'])==2
    assert client.get(P+'/unlock-requests?q=%27%20OR%201=1--').json()['items']==[]
    assert client.get(P+'/unlock-requests?uid=900002').json()['items']==[]
    with db.connect() as c,c.cursor() as q:
        q.execute('DELETE FROM taiwan_cain_2nd.charac_item_lock_info')
        for cid in range(910000,910027):
            q.execute("INSERT INTO taiwan_cain.charac_info(m_id,charac_no,charac_name,element_resist,spec_property,VIP) VALUES(900001,%s,%s,'','','0')",(cid,'P'+str(cid)))
            q.execute('INSERT INTO taiwan_cain_2nd.charac_item_lock_info VALUES(%s,%s)',(cid,original if cid==910026 else struct.pack('<I',800)+zlib.compress(bytes(800))))
        c.commit()
    d=client.get(P+'/unlock-requests').json();assert d['items']==[] and d['next_after']==910024 and d['scanned']==25
    d=client.get(P+'/unlock-requests?after='+str(d['next_after'])).json();assert len(d['items'])==1 and d['items'][0]['charac_no']==910026 and d['next_after'] is None


@pytest.mark.parametrize('committed',[True,False])
def test_batch_lost_commit_reply_query_never_replays(env,committed):
    from contextlib import contextmanager
    client,s,db,_=env;original=seed(env);op=batch(client).json()['operation_id']
    class Connection:
        def __init__(self,c):self.c=c
        def __getattr__(self,k):return getattr(self.c,k)
        def commit(self):
            if committed:self.c.commit()
            raise OSError('synthetic lost COMMIT response')
    class FaultDB:
        @contextmanager
        def connect(self):
            with db.connect() as c:yield Connection(c)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        Service(FaultDB(),s).confirm(digest(client.cookies.get(COOKIE)),op,'batch-lost-commit-reply-key')
    assert error.value.status_code==503
    assert '待确认' in error.value.detail
    for _ in range(2):
        result=client.get(P+'/operations/'+op).json()
        assert result['status']==('committed' if committed else 'preview')
        assert count(db,'audit')==(3 if committed else 0)
    assert (stored(db,900001)!=original)==committed
    assert (stored(db,900003)!=original)==committed


def test_batch_rejects_partial_target_permission_and_session_binding(env):
    client,s,db,_=env;original=seed(env)
    with db.connect() as c,c.cursor() as q:
        q.execute('UPDATE taiwan_cain.charac_info SET m_id=900002 WHERE charac_no=900003')
        q.execute('INSERT INTO taiwan_login.login_account_3(m_id,login_status,m_channel_no) VALUES(900002,0,3011)');c.commit()
    p=batch(client,[{'uid':900001,'charac_no':900001,'lock_keys':[1]},{'uid':900002,'charac_no':900003,'lock_keys':[2]}]);assert p.status_code==200,p.text
    assert confirm(client,p.json()['operation_id']).status_code==403
    assert stored(db,900001)==original and stored(db,900003)==original
    s.test_uids=(900001,900002)
    service=Service(db,s)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:service.confirm('unrelated-session',p.json()['operation_id'],'unrelated-session-key')
    assert e.value.status_code==404
    assert confirm(client,p.json()['operation_id']).status_code==200


def test_unlock_center_actual_minimum_grants(env):
    import importlib.util,os
    from pathlib import Path
    import pymysql
    from fastapi.testclient import TestClient
    from dnfgm.db import Database
    from dnfgm.app import create_app
    from dnfgm.security import PASSWORDS
    _,settings,rootdb,_=env;seed(env)
    spec=importlib.util.spec_from_file_location('unlock_grants',Path(__file__).resolve().parents[2]/'deploy/grants.py')
    grants=importlib.util.module_from_spec(spec);spec.loader.exec_module(grants)
    sql=grants.bootstrap_sql({'db_user':'unlock_minimal','db_password':'isolated-fixture-password','db_account_host':'localhost'},PASSWORDS.hash('fixture-admin-password'))
    with rootdb.connect() as c,c.cursor() as q:
        q.execute('DROP DATABASE dnf_gm');q.execute("DROP USER IF EXISTS 'unlock_minimal'@'localhost'")
        for statement in sql.split(';'):
            if statement.strip():q.execute(statement)
        c.commit()
    def factory():return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'],user='unlock_minimal',password='isolated-fixture-password',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    limiteddb=Database(settings,factory);client=TestClient(create_app(settings,limiteddb),raise_server_exceptions=True)
    try:
        client.headers['Origin']='http://testserver'
        r=client.post(P+'/auth/login',json={'username':'admin','password':'fixture-admin-password'});assert r.status_code==200
        client.headers['X-CSRF-Token']=r.json()['csrf']
        assert client.get(P+'/unlock-requests').status_code==200
        assert client.get(P+'/characters/900001/unlock-requests').json()['items'][0]['item']['id']==990001
        p=batch(client);assert p.status_code==200,p.text
        assert confirm(client,p.json()['operation_id']).status_code==200
        assert client.get(P+'/characters/900001/unlock-requests').json()['items'][0]['managed_operation']==p.json()['operation_id']
        for statement in ('DELETE FROM dnf_gm.audit','UPDATE taiwan_cain_2nd.inventory SET money=1','DROP TABLE taiwan_cain_2nd.charac_item_lock_info'):
            with limiteddb.connect() as c,c.cursor() as q:
                with pytest.raises(pymysql.err.OperationalError):q.execute(statement)
    finally:
        client.close()
        with rootdb.connect() as c,c.cursor() as q:q.execute("DROP USER 'unlock_minimal'@'localhost'");c.commit()
