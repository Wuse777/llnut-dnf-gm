import json
import os
from pathlib import Path
import struct
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pymysql
import pytest
from fastapi import HTTPException

from dnfgm.inventory_codec import pack,unpack,patch,digest
from dnfgm.inventory_fence import MaintenanceFence,BOUND_FIELDS,boot_id
from dnfgm.inventory_operations import InventoryOperations,ACTIONS
from dnfgm.inventory_reconcile import settle_window
from dnfgm.release_files import atomic_json
from dnfgm.security import COOKIE,digest as token_digest

P='/dnf-gm/api/v1'


def archive():
    raw=bytearray(61*3)
    raw[1]=1;struct.pack_into('<I',raw,2,990001);raw[6]=0xa3;raw[51]=2
    raw[62]=3;struct.pack_into('<I',raw,63,990002);struct.pack_into('<I',raw,68,4)
    return pack(bytes(raw))


@pytest.fixture
def inv(env,tmp_path):
    client,s,db,app=env
    s.image_digest='sha256:'+'b'*64;s.inventory_program_sha256='c'*64
    s.writes=(*s.writes,*ACTIONS);s.write_approvals.update({a:True for a in ACTIONS})
    live=json.loads(Path(s.status_file).read_text());live.update(core_ok=False,image_digest=s.image_digest)
    Path(s.status_file).write_text(json.dumps(live))
    root=tmp_path/'maintenance';root.mkdir(mode=0o755);(root/'fence.lock').touch(mode=0o644)
    now=int(time.time());mono=time.monotonic()
    permit=dict(version=1,id='d'*32,created_at=now-1,expires_at=now+600,reason='synthetic maintenance',
        created_monotonic=mono-1,expires_monotonic=mono+600,container_id='e'*64,container_started_at='synthetic-start',
        image_digest=s.image_digest,pvf_sha256=s.pvf_sha256,program_sha256=s.inventory_program_sha256,
        components=['mysql','game'],boot_id=boot_id(),policy_sha256='f'*64)
    evidence={**{k:permit[k] for k in BOUND_FIELDS},'permit_id':permit['id'],'safe':True,
        'collected_at':time.time(),'collected_monotonic':time.monotonic(),'all_writers_down':True,'mysql_up':True,
        'non_game_core_ok':True,'no_unmanaged_processes':True,'mem_available_mib':512,'swap_free_mib':4096}
    atomic_json(root/'permit.json',permit);atomic_json(root/'evidence.json',evidence)
    fence=MaintenanceFence(root,**app.state.inventory_operations.versions(),owner=os.geteuid())
    app.state.inventory_operations.fence=fence
    blob=archive()
    with db.connect() as c,c.cursor() as q:
        q.execute('INSERT INTO taiwan_cain_2nd.inventory(charac_no,money,inventory,equipslot) VALUES(900001,567,%s,%s)',(blob,blob))
        q.execute("INSERT INTO taiwan_cain_2nd.charac_inven_expand(charac_no,cargo,jewel,switch_equipslot,expand_equipslot,redeem_info) VALUES(900001,%s,'','','','')",(blob,))
        q.execute('INSERT INTO taiwan_cain.account_cargo(m_id,money,cargo) VALUES(900001,890,%s)',(blob,));c.commit()
    return client,s,db,app,root


def inspect(inv,container='inventory',slot=0):
    r=inv[0].get(f'{P}/inventory/characters/900001/{container}/{slot}')
    assert r.status_code==200,r.text
    return r.json()


def draft(inv,container='inventory',slot=0,**extra):
    item=inspect(inv,container,slot)
    return dict(action='item-edit',uid=900001,charac_no=900001,container=container,slot=slot,
                reference=item['reference'],changes={'enhancement':12},reason='测试',**extra)


def prepare(inv,body=None):
    r=inv[0].post(P+'/inventory/preview',json=body or draft(inv))
    assert r.status_code==200,r.text
    return r.json()


def confirm(inv,op,key=None):
    return inv[0].post(f'{P}/inventory/operations/{op}/confirm',json={'idempotency_key':key or uuid.uuid4().hex})


def blob_read(inv,container='inventory'):
    spec=inv[3].state.inventory_operations.coordinate(dict(container=container,uid=900001,charac_no=900001))
    schema,table,k,col,v=spec
    with inv[2].connect() as c,c.cursor() as q:
        q.execute(f'SELECT `{col}` v FROM `{schema}`.`{table}` WHERE `{k}`=%s',(v,));return q.fetchone()['v']


@pytest.mark.parametrize('container',['inventory','equipment','warehouse','account_warehouse'])
def test_edit_same_transaction_snapshots_and_original_key_recovery(inv,container):
    preview=prepare(inv,draft(inv,container));op=preview['operation_id'];key=uuid.uuid4().hex
    r=confirm(inv,op,key);assert r.status_code==200,r.text
    result=r.json();assert result['status']=='committed' and result['result']['client_verified'] is False
    actual=blob_read(inv,container);assert unpack(actual)[6]==0xac
    assert unpack(actual)[7:]==unpack(archive())[7:]
    with inv[2].connect() as c,c.cursor() as q:
        q.execute('SELECT before_blob,after_blob FROM dnf_gm.inventory_snapshots WHERE operation_id=%s',(op,));snap=q.fetchone()
        assert snap=={'before_blob':archive(),'after_blob':actual}
        q.execute('SELECT COUNT(*) n FROM dnf_gm.audit WHERE operation_id=%s',(op,));assert q.fetchone()['n']==1
        q.execute('SELECT money FROM taiwan_cain_2nd.inventory WHERE charac_no=900001');assert q.fetchone()['money']==567
        q.execute('SELECT money FROM taiwan_cain.account_cargo WHERE m_id=900001');assert q.fetchone()['money']==890
    # Successful same-key lookup is idempotent even after permit expires/closes.
    (inv[4]/'permit.json').unlink()
    assert confirm(inv,op,key).json()['status']=='committed'
    assert confirm(inv,op).status_code==409
    history=inv[0].get(P+'/inventory/operations?uid=900001').json()
    assert history['items'][0]['operation_id']==op
    assert all(word not in json.dumps(history) for word in ('before_blob','after_blob','session_hash','idempotency_key'))


def test_quantity_no_pvf_cap_and_restore_reclaim(inv):
    body=draft(inv,slot=1);body['changes']={'quantity':2147483647}
    p=prepare(inv,body);assert confirm(inv,p['operation_id']).status_code==200
    assert inspect(inv,slot=1)['item']['quantity']==2147483647
    body=draft(inv,slot=1);body.update(action='item-reclaim',changes={})
    p=prepare(inv,body);assert confirm(inv,p['operation_id']).status_code==200
    assert inspect(inv,slot=1)['item']['empty']
    source=p['operation_id'];body=draft(inv,slot=1);body.update(action='item-restore',changes={},source_operation_id=source)
    p=prepare(inv,body);r=confirm(inv,p['operation_id']);assert r.status_code==200,r.text
    assert inspect(inv,slot=1)['item']['quantity']==2147483647
    assert r.json()['result']['source_operation_id']==source


def test_restore_rejects_any_subsequent_container_change(inv):
    p=prepare(inv);assert confirm(inv,p['operation_id']).status_code==200
    original=p['operation_id']
    body=draft(inv,slot=1);body['changes']={'quantity':123};p=prepare(inv,body);assert confirm(inv,p['operation_id']).status_code==200
    body=draft(inv);body.update(action='item-restore',changes={},source_operation_id=original)
    r=inv[0].post(P+'/inventory/preview',json=body)
    assert r.status_code==409 and '后续变化' in r.text


@pytest.mark.parametrize('change',['foreign','deleted','reference','changed_blob','disabled','window','expired'])
def test_confirmation_rechecks_all_guards(inv,change):
    p=prepare(inv);client,s,db,app,root=inv
    if change=='foreign':
        with db.connect() as c,c.cursor() as q:q.execute('UPDATE taiwan_cain.charac_info SET m_id=900002 WHERE charac_no=900001');c.commit()
    elif change=='deleted':
        with db.connect() as c,c.cursor() as q:q.execute('UPDATE taiwan_cain.charac_info SET delete_flag=1 WHERE charac_no=900001');c.commit()
    elif change in ('reference','changed_blob'):
        new=patch(archive(),1,{'quantity':987}).after_blob
        with db.connect() as c,c.cursor() as q:q.execute('UPDATE taiwan_cain_2nd.inventory SET inventory=%s WHERE charac_no=900001',(new,));c.commit()
    elif change=='disabled':s.writes=()
    elif change=='window':(root/'permit.json').unlink()
    else:
        with db.connect() as c,c.cursor() as q:q.execute('UPDATE dnf_gm.operations SET expires_at=0 WHERE operation_id=%s',(p['operation_id'],));c.commit()
    r=confirm(inv,p['operation_id']);assert r.status_code in (403,409),r.text
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM dnf_gm.inventory_snapshots');assert q.fetchone()['n']==0


def test_cancel_preview_and_generic_endpoint_cannot_execute_inventory(inv):
    p=prepare(inv);op=p['operation_id']
    r=inv[0].post(P+f'/operations/{op}/confirm',json={'idempotency_key':uuid.uuid4().hex})
    assert r.status_code==409 and '专用' in r.text
    assert inv[0].post(P+f'/inventory/operations/{op}/cancel-preview').json()['status']=='cancelled'
    assert confirm(inv,op).status_code==409
    assert blob_read(inv)==archive()


class Conn:
    def __init__(self,c,commit=None,cursor=None):self.c=c;self.commit_hook=commit;self.cursor_hook=cursor
    def __getattr__(self,k):return getattr(self.c,k)
    def commit(self):return self.commit_hook(self.c) if self.commit_hook else self.c.commit()
    def cursor(self,*a,**k):
        q=self.c.cursor(*a,**k);return self.cursor_hook(q) if self.cursor_hook else q


@pytest.mark.parametrize('commit_number',[1,2])
def test_committed_but_response_lost_never_replays_and_root_can_settle(inv,monkeypatch,commit_number):
    p=prepare(inv);op=p['operation_id'];key=uuid.uuid4().hex;db=inv[2];factory=db.factory;count=[0]
    def commit(c):
        count[0]+=1;c.commit()
        if count[0]==commit_number:raise pymysql.OperationalError(2013,'synthetic response loss')
    monkeypatch.setattr(db,'factory',lambda:Conn(factory(),commit=commit))
    # Inject into the two inventory commits, not the earlier HTTP auth/session
    # touch commit. Endpoint routing and auth are exercised by other tests.
    session=token_digest(inv[0].cookies.get(COOKIE))
    with pytest.raises(HTTPException) as failure:
        inv[3].state.inventory_operations.confirm(session,op,key)
    assert failure.value.status_code==503
    monkeypatch.setattr(db,'factory',factory)
    status=inv[0].get(P+f'/inventory/operations/{op}').json()['status']
    assert status==('executing' if commit_number==1 else 'committed')
    assert confirm(inv,op,key).json()['status']==status
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deploy'))
    from inventory_window import WindowManager
    m=WindowManager(inv[4],None,owner=os.geteuid(),reconcile=lambda wid:settle_window(db,wid))
    close=m.close('d'*32);assert close['safe_to_resume']
    final=inv[0].get(P+f'/inventory/operations/{op}').json()
    assert final['status']==('aborted' if commit_number==1 else 'committed')
    if commit_number==1:assert blob_read(inv)==archive()


def test_failure_after_game_update_rolls_back_snapshot_audit_and_game(inv,monkeypatch):
    p=prepare(inv);op=p['operation_id'];db=inv[2];factory=db.factory
    class Cursor:
        def __init__(self,q):self.q=q
        def __getattr__(self,k):return getattr(self.q,k)
        def __enter__(self):return self
        def __exit__(self,*a):self.q.close()
        def execute(self,sql,*a):
            if sql.startswith('INSERT INTO dnf_gm.inventory_snapshots'):raise pymysql.OperationalError(1105,'synthetic write failure')
            return self.q.execute(sql,*a)
    monkeypatch.setattr(db,'factory',lambda:Conn(factory(),cursor=Cursor))
    assert confirm(inv,op).status_code==500
    monkeypatch.setattr(db,'factory',factory)
    assert blob_read(inv)==archive()
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM dnf_gm.inventory_snapshots');assert q.fetchone()['n']==0
        q.execute('SELECT COUNT(*) n FROM dnf_gm.audit WHERE operation_id=%s',(op,));assert q.fetchone()['n']==0
    assert inv[3].state.inventory_operations.detail(op)['status']=='executing'


def test_parallel_previews_of_same_container_cannot_overwrite(inv):
    a=prepare(inv);body=draft(inv);body['changes']={'enhancement':15};b=prepare(inv,body)
    session=token_digest(inv[0].cookies.get(COOKIE));ops=inv[3].state.inventory_operations
    def execute(op):
        try:return ops.confirm(session,op,uuid.uuid4().hex)['status']
        except Exception:return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(execute,[a['operation_id'],b['operation_id']]))
    assert results.count('committed')==1
    assert unpack(blob_read(inv))[6]&31 in (12,15)


def test_close_does_not_authorize_resume_until_database_row_lock_resolves(inv):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deploy'))
    from inventory_window import WindowManager
    p=prepare(inv);op=p['operation_id'];db=inv[2]
    # Synthetic interrupted intent, then a DB-side transaction whose resolution
    # cannot yet be known after the application lease has disappeared.
    with db.connect() as c,c.cursor() as q:
        q.execute("UPDATE dnf_gm.operations SET status='executing' WHERE operation_id=%s",(op,))
        q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,'owner','item-intent',900001,'test','{}','{}')",('intent:'+op,));c.commit()
    m=WindowManager(inv[4],None,owner=os.geteuid(),reconcile=lambda wid:settle_window(db,wid))
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT operation_id FROM dnf_gm.operations WHERE operation_id=%s FOR UPDATE',(op,))
        with pytest.raises(pymysql.OperationalError):m.close('d'*32)
        assert not (inv[4]/'permit.json').exists()
        assert json.loads((inv[4]/'closed.json').read_text())['safe_to_resume'] is False
        c.rollback()
    assert m.close('d'*32)['safe_to_resume']
    assert inv[3].state.inventory_operations.detail(op)['status']=='aborted'


def test_no_unauthenticated_csrf_or_cross_session_confirmation(inv):
    p=prepare(inv);client=inv[0]
    assert client.post(P+'/inventory/preview',json=draft(inv),headers={'X-CSRF-Token':'wrong'}).status_code==403
    client.post(P+'/auth/logout')
    assert client.get(P+'/inventory/operations').status_code==401
    assert client.get(P+'/inventory/characters/900001/inventory/0').status_code==401
    login=client.post(P+'/auth/login',json={'username':'admin','password':'fixture-password-no-production'})
    client.headers['X-CSRF-Token']=login.json()['csrf']
    assert confirm(inv,p['operation_id']).status_code==403


def test_real_minimal_permissions_allow_archives_but_not_other_game_fields(inv):
    import importlib.util
    from dnfgm.db import Database
    from dnfgm.security import PASSWORDS
    path=Path(__file__).resolve().parents[2]/'deploy/grants.py'
    spec=importlib.util.spec_from_file_location('inventory_grants',path)
    grants=importlib.util.module_from_spec(spec);spec.loader.exec_module(grants)
    root=inv[2]
    sql=grants.bootstrap_sql({'db_user':'inventory_minimal','db_password':'isolated-fixture-password','db_account_host':'localhost'},PASSWORDS.hash('fixture-admin-password'))
    with root.connect() as c,c.cursor() as q:
        q.execute('DROP DATABASE dnf_gm');q.execute("DROP USER IF EXISTS 'inventory_minimal'@'localhost'")
        for statement in sql.split(';'):
            if statement.strip():q.execute(statement)
        c.commit()
    def factory():
        return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'],user='inventory_minimal',password='isolated-fixture-password',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    limited=Database(inv[1],factory)
    service=inv[3].state.inventory_operations
    original=service.db;service.db=limited
    try:
        with limited.connect() as c,c.cursor() as q:
            with pytest.raises(pymysql.OperationalError):q.execute('UPDATE taiwan_cain_2nd.inventory SET inventory=inventory WHERE charac_no=900001')
        with root.connect() as c,c.cursor() as q:
            for statement in grants.inventory_storage_sql("'inventory_minimal'@'localhost'").split(';'):
                if statement.strip():q.execute(statement)
            c.commit()
        for container in ('inventory','equipment','warehouse','account_warehouse'):
            item=service.item(900001,container,0)
            body=dict(action='item-edit',uid=900001,charac_no=900001,container=container,slot=0,reference=item['reference'],changes={'enhancement':12},reason='最小权限测试')
            p=service.preview('f'*64,body)
            assert service.confirm('f'*64,p['operation_id'],uuid.uuid4().hex)['status']=='committed'
        for statement in ('DELETE FROM dnf_gm.inventory_snapshots','UPDATE dnf_gm.inventory_snapshots SET uid=1','UPDATE taiwan_cain_2nd.inventory SET money=0','UPDATE taiwan_cain.account_cargo SET money=0','UPDATE taiwan_cain.charac_info SET lev=1','SELECT password FROM d_taiwan.accounts','DROP TABLE dnf_gm.inventory_snapshots'):
            with limited.connect() as c,c.cursor() as q:
                with pytest.raises(pymysql.OperationalError):q.execute(statement)
        assert settle_window(limited,'d'*32)['game_writes'] is False
    finally:
        service.db=original
        with root.connect() as c,c.cursor() as q:q.execute("DROP USER IF EXISTS 'inventory_minimal'@'localhost'");c.commit()


@pytest.mark.parametrize('field,value',[('quantity',0),('quantity',2147483648),('enhancement',32),('orb_id',4294967296),('orb_id',999999)])
def test_invalid_or_unindexed_changes_never_create_preview(inv,field,value):
    body=draft(inv,slot=1 if field=='quantity' else 0);body['changes']={field:value}
    r=inv[0].post(P+'/inventory/preview',json=body)
    assert r.status_code in (409,422),r.text
    assert blob_read(inv)==archive()


def test_nontransactional_game_archive_refuses_instead_of_changing_engine(inv):
    with inv[2].connect() as c,c.cursor() as q:q.execute('ALTER TABLE taiwan_cain_2nd.inventory ENGINE=MyISAM');c.commit()
    r=inv[0].post(P+'/inventory/preview',json=draft(inv))
    assert r.status_code==409 and 'InnoDB' in r.text
    assert blob_read(inv)==archive()


@pytest.mark.parametrize('change',['foreign_slot','missing','corrupt_before','corrupt_after','old_version'])
def test_restore_snapshot_provenance_is_rechecked(inv,change):
    p=prepare(inv);assert confirm(inv,p['operation_id']).status_code==200
    source=p['operation_id']
    body=draft(inv);body.update(action='item-restore',changes={},source_operation_id=source)
    if change=='foreign_slot':body=draft(inv,slot=1);body.update(action='item-restore',changes={},source_operation_id=source)
    elif change=='missing':body['source_operation_id']='0'*32
    else:
        # Deliberate root-only corruption: runtime account cannot edit snapshots.
        column={'corrupt_before':'before_sha256','corrupt_after':'after_sha256','old_version':'program_sha256'}[change]
        with inv[2].connect() as c,c.cursor() as q:q.execute(f'UPDATE dnf_gm.inventory_snapshots SET {column}=%s WHERE operation_id=%s',('0'*64,source));c.commit()
    r=inv[0].post(P+'/inventory/preview',json=body)
    assert r.status_code==409,r.text


@pytest.mark.parametrize('stage',[1,2])
def test_commit_failure_before_database_acceptance_never_requires_replay(inv,monkeypatch,stage):
    p=prepare(inv);op=p['operation_id'];db=inv[2];factory=db.factory;count=[0]
    def fail_before_commit(c):
        count[0]+=1
        if count[0]==stage:raise pymysql.OperationalError(2013,'synthetic pre-acceptance disconnect')
        c.commit()
    monkeypatch.setattr(db,'factory',lambda:Conn(factory(),commit=fail_before_commit))
    with pytest.raises(HTTPException) as failure:
        inv[3].state.inventory_operations.confirm(token_digest(inv[0].cookies.get(COOKIE)),op,uuid.uuid4().hex)
    assert failure.value.status_code==503
    monkeypatch.setattr(db,'factory',factory)
    assert blob_read(inv)==archive()
    assert inv[3].state.inventory_operations.detail(op)['status']==('preview' if stage==1 else 'executing')
    from inventory_window import WindowManager
    receipt=WindowManager(inv[4],None,owner=os.geteuid(),reconcile=lambda wid:settle_window(db,wid)).close('d'*32)
    assert receipt['safe_to_resume']
    assert inv[3].state.inventory_operations.detail(op)['status']==('preview' if stage==1 else 'aborted')
    assert blob_read(inv)==archive()


def test_fence_lease_failure_immediately_before_game_commit_rolls_back(inv,monkeypatch):
    from dnfgm.inventory_fence import FenceLease,Refused
    p=prepare(inv);op=p['operation_id'];checks=[0];original=FenceLease.check
    def check(lease):
        checks[0]+=1
        if checks[0]==2:raise Refused('synthetic_last_moment_evidence_change')
        return original(lease)
    monkeypatch.setattr(FenceLease,'check',check)
    response=confirm(inv,op)
    assert response.status_code==409,response.text
    assert checks[0]==2 and blob_read(inv)==archive()
    assert inv[3].state.inventory_operations.detail(op)['status']=='executing'
    with inv[2].connect() as c,c.cursor() as q:
        q.execute('SELECT COUNT(*) n FROM dnf_gm.inventory_snapshots');assert q.fetchone()['n']==0
        q.execute('SELECT COUNT(*) n FROM dnf_gm.audit WHERE operation_id=%s',(op,));assert q.fetchone()['n']==0
