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


def fatigue_setup(inv):
    client,s,db,app,root=inv
    s.writes=(*s.writes,'char-fatigue');s.write_approvals['char-fatigue']=True
    app.state.character_maintenance.fence=app.state.inventory_operations.fence
    with db.connect() as c,c.cursor() as q:
        q.execute('INSERT INTO taiwan_cain.charac_stat(charac_no,fatigue,premium_fatigue,used_fatigue) VALUES(900001,100,20,88)');c.commit()
    r=client.get(P+'/character-maintenance/characters/900001')
    assert r.status_code==200,r.text
    assert r.json()['maintenance']['available']
    return dict(uid=900001,charac_no=900001,reference=r.json()['reference'],changes={'fatigue':0,'premium_fatigue':0},reason='恢复测试疲劳')


def test_fatigue_atomic_commit_history_and_no_generic_confirm(inv):
    body=fatigue_setup(inv);client=inv[0];base=P+'/character-maintenance'
    r=client.post(base+'/preview',json=body);assert r.status_code==200,r.text
    op=r.json()['operation_id'];key=uuid.uuid4().hex
    assert client.post(P+f'/operations/{op}/confirm',json={'idempotency_key':key}).status_code==409
    r=client.post(base+f'/operations/{op}/confirm',json={'idempotency_key':key})
    assert r.status_code==200,r.text
    assert r.json()['status']=='committed'
    with inv[2].connect() as c,c.cursor() as q:
        q.execute('SELECT fatigue,premium_fatigue,used_fatigue FROM taiwan_cain.charac_stat WHERE charac_no=900001')
        assert q.fetchone()==dict(fatigue=0,premium_fatigue=0,used_fatigue=88)
        q.execute('SELECT before_blob,after_blob FROM dnf_gm.inventory_snapshots WHERE operation_id=%s',(op,));snap=q.fetchone()
        assert json.loads(snap['before_blob'])['fatigue']==100
        assert json.loads(snap['after_blob'])['format']=='qf1031-fatigue-1'
        q.execute('SELECT COUNT(*) n FROM dnf_gm.audit WHERE operation_id=%s',(op,));assert q.fetchone()['n']==1
    (inv[4]/'permit.json').unlink()
    assert client.post(base+f'/operations/{op}/confirm',json={'idempotency_key':key}).json()['status']=='committed'
    assert client.get(base+'/operations?charac_no=900001').json()['items'][0]['operation_id']==op
    assert not client.get(P+'/inventory/operations?charac_no=900001').json()['items']
    assert client.get(P+f'/inventory/operations/{op}').status_code==404


def test_fatigue_stale_and_missing_window_refused(inv):
    body=fatigue_setup(inv);base=P+'/character-maintenance';client=inv[0]
    with inv[2].connect() as c,c.cursor() as q:
        q.execute('UPDATE taiwan_cain.charac_stat SET fatigue=101 WHERE charac_no=900001');c.commit()
    assert client.post(base+'/preview',json=body).status_code==409
    body['reference']=client.get(base+'/characters/900001').json()['reference']
    r=client.post(base+'/preview',json=body);assert r.status_code==200,r.text
    op=r.json()['operation_id']
    original=inv[3].state.character_maintenance.apply_archive
    def failed_write(*args):raise RuntimeError('synthetic pre-write failure')
    inv[3].state.character_maintenance.apply_archive=failed_write
    r=client.post(base+f'/operations/{op}/confirm',json={'idempotency_key':uuid.uuid4().hex})
    assert r.status_code==500
    inv[3].state.character_maintenance.apply_archive=original
    (inv[4]/'permit.json').unlink()
    assert client.post(base+'/preview',json=body).status_code==409
    assert settle_window(inv[2],'d'*32)['resolved_aborted']==[op]
    with inv[2].connect() as c,c.cursor() as q:
        q.execute('SELECT fatigue FROM taiwan_cain.charac_stat WHERE charac_no=900001');assert q.fetchone()['fatigue']==101
    assert client.get(base+f'/operations/{op}').json()['status']=='aborted'


def test_semantic_equipment_labels_enchant_search_and_preview_preserve_policy(inv):
    import sqlite3
    from dnfgm.equipment_metadata import enchantment
    client,s,db,app,_=inv
    # Older indexes remain usable; this endpoint does not pretend they contain effects.
    assert client.get(P+'/catalog/enchantments').json()['metadata_state']=='unavailable'
    with sqlite3.connect(s.catalog_file) as c:
        c.executescript('CREATE TABLE equipment_details(item_id INTEGER PRIMARY KEY,part_code TEXT,rarity INTEGER);CREATE TABLE enchantments(item_id INTEGER PRIMARY KEY,targets_json TEXT,effects_json TEXT,summary TEXT);')
        c.execute("INSERT INTO metadata VALUES('equipment_index_version','1')")
        c.execute("INSERT INTO equipment_details VALUES(990001,'[coat]',0)")
        # Deliberately delivery-blocked: the display index must not grant mail rights.
        c.execute("INSERT INTO items VALUES(990004,'火属性卡片','material',1,1,0,0,0,'fixture/card')")
        c.execute('INSERT INTO enchantments VALUES(?,?,?,?)',(990004,'["[coat]"]','[{"tag":"[elemental property]","label":"攻击属性","values":["[fire element]"]}]','攻击属性 火属性'))
    r=client.get(P+'/catalog/enchantments',params={'q':'火属性'});assert r.status_code==200,r.text
    row=r.json()['items'][0];assert row['id']==990004 and row['target_names']==['上衣']
    assert 'effects' in row and 'source_path' not in row
    assert client.get(P+'/catalog/enchantments',params={'q':'%'}).json()['items']==[]
    assert client.get(P+'/catalog/enchantments',params={'q':'9'*80}).json()['items']==[]
    item=inspect(inv,'equipment');assert item['item']['part_name']=='上衣'
    assert item['item']['slot_label']=='武器'  # Actual storage slot, not the PVF item part.
    assert item['item']['base_durability']==20 and item['item']['enchantment']['name']=='无附魔'
    body=draft(inv);body['changes']={'orb_id':990004}
    operation=prepare(inv,body);preview=operation['preview']
    assert preview['item_info']['name']=='测试装备'
    assert preview['before_enchantment']['id']==0
    assert preview['after_enchantment']['name']=='火属性卡片'
    assert preview['after_enchantment']['summary']=='攻击属性 火属性'
    submitted=confirm(inv,operation['operation_id']);assert submitted.status_code==200,submitted.text
    assert inspect(inv)['item']['enchantment']['name']=='火属性卡片'
    detail=client.get(P+'/characters/900001');assert detail.status_code==200,detail.text
    assert '火属性卡片' in detail.text
    assert enchantment({},987)['known'] is False
    with sqlite3.connect(s.catalog_file) as c:assert c.execute('SELECT allowed FROM items WHERE id=990004').fetchone()[0]==0
    client.cookies.clear();assert client.get(P+'/catalog/enchantments').status_code==401
