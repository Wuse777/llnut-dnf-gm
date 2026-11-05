"""Web close intent: real MySQL transactions, explicit root receipt fixtures."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from dnfgm.db import Database
from dnfgm.maintenance_requests import close_id
from dnfgm.release_files import atomic_json
from test_maintenance_requests import setup, start, make_confirmable, confirm, BASE

KEY='fixture-close-key-0001'


@pytest.fixture
def opened(setup):
    c,s,db,app,w,coordinator,host,root=setup
    op,_=start(setup);detail=make_confirmable(setup,op)
    assert confirm(c,op,detail).status_code==200
    (root/'inbox'/(op+'.confirm.json')).unlink()
    p=root/'results'/(op+'.json');receipt=json.loads(p.read_text())
    receipt.update(state='maintenance_open',can_confirm=False,can_cancel=False,window_requires_live_check=True)
    atomic_json(p,receipt)
    return setup,op,receipt['fingerprint']


def payload(fp,**changes):
    return {'idempotency_key':KEY,'fingerprint':fp,'acknowledge_restore':True,**changes}


def close(opened,**changes):
    setup,op,fingerprint=opened
    return setup[0].post(BASE+'/requests/'+op+'/close',json=payload(fingerprint,**changes))


def test_close_is_atomic_original_bound_and_replay_does_not_create_another_intent(opened):
    setup,op,fingerprint=opened;c,s,db,app,w,coordinator,host,root=setup
    assert c.get(BASE+'/requests/'+op).json()['can_close']
    first=close(opened);assert first.status_code==200,first.text
    result=first.json();assert result['close_requested'] and not result['can_close']
    assert result['close_operation_id']==close_id(op) and result['dispatch_phase']=='close'
    assert close(opened).status_code==200
    assert close(opened,idempotency_key='different-close-key').status_code==409
    assert close(opened,fingerprint='f'*64).status_code==409
    with db.connect() as conn,conn.cursor() as q:
        q.execute("SELECT * FROM dnf_gm.operations WHERE action='maint-close'");rows=q.fetchall()
        assert len(rows)==1 and rows[0]['status']=='queued'
        q.execute("SELECT * FROM dnf_gm.audit WHERE action='maintenance-close'");audits=q.fetchall()
        assert len(audits)==1 and audits[0]['operation_id']==rows[0]['operation_id']
        assert json.loads(audits[0]['request_json'])==json.loads(rows[0]['request_json'])
    data=json.loads((root/'inbox'/(op+'.close.json')).read_text())
    assert data['fingerprint']==fingerprint and data['phase']=='close'
    assert not host.calls


def test_disabling_new_maintenance_and_original_session_expiry_does_not_prevent_restore(opened):
    setup,op,_=opened;c,s,db,app,*_=setup
    s.write_approvals['maintenance']=False
    with db.connect() as conn,conn.cursor() as q:
        q.execute('UPDATE dnf_gm.operations SET session_hash=%s WHERE operation_id=%s',('e'*64,op));conn.commit()
    assert c.get(BASE+'/requests/'+op).json()['can_close']
    assert close(opened).status_code==200


@pytest.mark.parametrize('state',['prepared','running','writers_stopped','needs_review','resuming','completed'])
def test_cannot_close_wrong_lifecycle_stage(opened,state):
    setup,op,_=opened;c,*_=setup;root=setup[-1]
    p=root/'results'/(op+'.json');data=json.loads(p.read_text());data['state']=state;atomic_json(p,data)
    assert not c.get(BASE+'/requests/'+op).json()['can_close']
    assert close(opened).status_code==409
    assert not list((root/'inbox').glob('*.close.json'))


@pytest.mark.parametrize('broken',['missing','stale','changed','unready'])
def test_cannot_close_without_fresh_compatible_executor(opened,broken):
    setup,op,_=opened;c,*_=setup;root=setup[-1];p=root/'status.json'
    d=json.loads(p.read_text())
    if broken=='missing':p.unlink()
    else:
        if broken=='stale':d['collected_at']=time.time()-100
        if broken=='changed':d['pvf_sha256']='f'*64
        if broken=='unready':d['execute_supported']=False
        atomic_json(p,d)
    assert not c.get(BASE+'/requests/'+op).json()['can_close']
    assert close(opened).status_code==409


@pytest.mark.parametrize('committed',[False,True])
def test_close_commit_response_loss_queries_original_never_enqueues(opened,committed):
    setup,op,_=opened;c,s,db,app,*_=setup;root=setup[-1]
    class LostCommit:
        def __init__(self,conn):self.conn=conn
        def __getattr__(self,key):return getattr(self.conn,key)
        def commit(self):
            if committed:self.conn.commit()
            raise ConnectionError('synthetic lost reply')
    app.state.maintenance.db=Database(s,lambda:LostCommit(db.factory()))
    response=close(opened);assert response.status_code==503,response.text
    app.state.maintenance.db=db
    detail=c.get(BASE+'/requests/'+op).json()
    assert detail['close_requested'] is committed
    assert not list((root/'inbox').glob('*.close.json'))
    # Only an explicit authenticated action resumes transport, with the same ID.
    if committed:response=c.post(BASE+'/requests/'+op+'/dispatch')
    else:response=close(opened)
    assert response.status_code==200,response.text
    assert response.json()['close_operation_id']==close_id(op)


def test_global_idempotency_collision_has_no_close_link_or_audit(opened):
    setup,op,_=opened;c,s,db,*_=setup
    with db.connect() as conn,conn.cursor() as q:
        q.execute('UPDATE dnf_gm.operations SET idempotency_key=%s WHERE operation_id=%s',(KEY,op));conn.commit()
    assert close(opened).status_code==409
    assert not c.get(BASE+'/requests/'+op).json()['close_requested']
    with db.connect() as conn,conn.cursor() as q:
        q.execute("SELECT COUNT(*) n FROM dnf_gm.audit WHERE action='maintenance-close'");assert q.fetchone()['n']==0


def test_origin_csrf_ack_recent_password_and_extra_fields_required(opened):
    setup,op,fp=opened;c,s,db,*_=setup;url=BASE+'/requests/'+op+'/close'
    assert c.post(url,json=payload(fp),headers={'Origin':'https://evil.invalid'}).status_code==403
    assert c.post(url,json=payload(fp),headers={'X-CSRF-Token':'bad'}).status_code==403
    assert close(opened,acknowledge_restore=False).status_code==422
    assert close(opened,acknowledge_restore='true').status_code==422
    assert close(opened,command='restart docker').status_code==422
    with db.connect() as conn,conn.cursor() as q:q.execute('UPDATE dnf_gm.sessions SET authenticated_at=0');conn.commit()
    assert close(opened).status_code==403
    c.cookies.clear();assert close(opened).status_code==401


def test_duplicate_close_after_restore_is_query_only(opened):
    setup,op,_=opened;c,*_=setup;root=setup[-1]
    assert close(opened).status_code==200
    (root/'inbox'/(op+'.close.json')).unlink()
    path=root/'results'/(op+'.json');d=json.loads(path.read_text());d['state']='completed';atomic_json(path,d)
    assert close(opened).json()['result']['state']=='completed'
    assert c.post(BASE+'/requests/'+op+'/dispatch').status_code==200
    assert not list((root/'inbox').glob('*.close.json'))


def test_concurrent_close_keys_have_one_atomic_winner(opened):
    setup,op,fp=opened;c,s,db,app,*_=setup
    with db.connect() as conn,conn.cursor() as q:session=app.state.maintenance.row(q,op)['session_hash']
    barrier=Barrier(2)
    def run(key):
        barrier.wait()
        try:return app.state.maintenance.close(session,op,payload(fp,idempotency_key=key))
        except HTTPException as error:return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[KEY,'other-concurrent-key']))
    assert sum(isinstance(r,dict) for r in results)==1 and 409 in results


def test_parent_link_without_original_audit_cannot_dispatch_close(opened):
    setup,op,_=opened;c,s,db,*_=setup;root=setup[-1]
    assert close(opened).status_code==200
    (root/'inbox'/(op+'.close.json')).unlink()
    with db.connect() as conn,conn.cursor() as q:
        q.execute('DELETE FROM dnf_gm.audit WHERE operation_id=%s',(close_id(op),));conn.commit()
    assert c.post(BASE+'/requests/'+op+'/dispatch').status_code==409
    assert not list((root/'inbox').glob('*.close.json'))


def test_private_monitor_attestation_does_not_reach_overview(setup):
    c,s,*_=setup
    from pathlib import Path
    path=Path(s.status_file);data=json.loads(path.read_text())
    data['maintenance_monitor']={'release':'/private/release','boot_id':'private-boot','policy_sha256':'private-config-hash'}
    atomic_json(path,data)
    response=c.get('/dnf-gm/api/v1/overview')
    assert response.status_code==200 and response.json()['server']['fresh']
    assert 'maintenance_monitor' not in response.text
    assert '/private/release' not in response.text


def test_readiness_failure_explained_without_leaking_private_handshake(setup):
    c,*_=setup;root=setup[-1]
    p=root/'status.json';d=json.loads(p.read_text())
    d.update(executor_protocol=1,execute_supported=False,readiness_error='/private/program-or-config')
    atomic_json(p,d)
    response=c.get(BASE)
    assert '暂未通过' in response.json()['message']
    assert '/private' not in response.text


def test_audit_failure_rolls_back_close_child_parent_link_and_transport(opened):
    setup,op,_=opened;c,s,db,*_=setup;root=setup[-1]
    with db.connect() as conn,conn.cursor() as q:
        q.execute("CREATE TRIGGER dnf_gm.reject_close_audit BEFORE INSERT ON dnf_gm.audit FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic audit unavailable'")
        conn.commit()
    assert close(opened).status_code==500
    assert not c.get(BASE+'/requests/'+op).json()['close_requested']
    with db.connect() as conn,conn.cursor() as q:
        q.execute("SELECT COUNT(*) n FROM dnf_gm.operations WHERE action='maint-close'");assert q.fetchone()['n']==0
    assert not list((root/'inbox').glob('*.close.json'))
