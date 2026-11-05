import json
import os
from pathlib import Path
import sys
import time
import uuid

import pytest
from dnfgm import maintenance_requests as mod
from dnfgm.release_files import atomic_json
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deploy'))
from maintenance_drain import DrainCoordinator
from maintenance_fixtures import admission
from maintenance_outbox import PreparationWorker
from test_game_drain import FakeHost

BASE='/dnf-gm/api/v1/maintenance'


@pytest.fixture
def setup(env,tmp_path,monkeypatch):
    client,s,db,app=env
    monkeypatch.setattr(mod,'ROOT_UID',os.geteuid())
    from dnfgm import write_gate
    from maintenance_gate import WriteGateManager
    monkeypatch.setattr(write_gate,'ROOT_UID',os.geteuid())
    s.gameplay_gate_dir=str(tmp_path/'write-gate')
    WriteGateManager(s.gameplay_gate_dir,owner=os.geteuid()).initialize()
    root=tmp_path/'transport';root.mkdir(mode=0o755)
    (root/'inbox').mkdir(mode=0o770);(root/'results').mkdir(mode=0o755)
    s.maintenance_dir=str(root);s.writes=(*s.writes,'maintenance');s.write_approvals['maintenance']=True
    host=FakeHost();s.image_digest=host.ident['image_digest'];s.pvf_sha256=host.ident['pvf_sha256'];s.inventory_program_sha256=host.ident['program_sha256']
    host.cfg.update({k:host.ident[k] for k in ('image_digest','pvf_sha256','program_sha256')})
    status=Path(s.status_file);d=json.loads(status.read_text());d.update(image_digest=s.image_digest,pvf_sha256=s.pvf_sha256);status.write_text(json.dumps(d))
    coordinator=DrainCoordinator(tmp_path/'journal',host,owner=os.geteuid(),admission=admission(tmp_path));coordinator.initialize()
    worker=PreparationWorker(root,coordinator,os.geteuid(),owner=os.geteuid())
    worker.tick()
    return client,s,db,app,worker,coordinator,host,root


def start(rig):
    c,*_=rig;op=uuid.uuid4().hex
    response=c.post(BASE+'/requests',json={'request_id':op,'reason':'调整测试角色装备'})
    assert response.status_code==200,response.text
    return op,response.json()


def make_confirmable(rig,op):
    c,s,db,app,worker,coordinator,host,root=rig
    worker.tick()
    # Test fixture for the future complete driver; the actual planning worker
    # never advertises support or sends a game command.
    status=json.loads((root/'status.json').read_text());status['execute_supported']=True;atomic_json(root/'status.json',status)
    return c.get(BASE+'/requests/'+op).json()


def confirm(c,op,detail,**changes):
    payload={'idempotency_key':'fixture-confirm-key-01','fingerprint':detail['result']['fingerprint'],'acknowledge_disconnect':True,**changes}
    return c.post(BASE+'/requests/'+op+'/confirm',json=payload)


def test_real_prepare_transport_persisted_plan_and_cancel_without_game_commands(setup):
    c,s,db,app,worker,coordinator,host,root=setup
    op,initial=start(setup)
    assert initial['status']=='preparing' and initial['result'] is None
    with db.connect() as conn,conn.cursor() as q:
        q.execute('SELECT action FROM dnf_gm.audit WHERE operation_id=%s',(op+':prepare',));assert q.fetchone()['action']=='maintenance-prepare'
    assert worker.tick()['processed']==1
    detail=c.get(BASE+'/requests/'+op).json()
    assert detail['result']['state']=='prepared' and not detail['can_confirm']
    assert not c.get(BASE).json()['execute_supported']
    assert confirm(c,op,detail).status_code==409
    assert c.post(BASE+'/requests/'+op+'/cancel').status_code==200
    worker.tick()
    assert c.get(BASE+'/requests/'+op).json()['result']['state']=='cancelled'
    assert not host.calls
    assert not list((root/'inbox').glob('*.json'))


def test_confirm_audit_and_queue_atomic_same_key_recovers_original(setup):
    c,s,db,app,worker,coordinator,host,root=setup
    op,_=start(setup);detail=make_confirmable(setup,op)
    assert detail['can_confirm']
    r=confirm(c,op,detail);assert r.status_code==200,r.text
    assert r.json()['status']=='queued'
    assert confirm(c,op,detail).status_code==200
    assert confirm(c,op,detail,idempotency_key='fixture-other-key').status_code==409
    assert confirm(c,op,detail,fingerprint='0'*64).status_code==409
    with db.connect() as conn,conn.cursor() as q:
        q.execute('SELECT COUNT(*) AS n FROM dnf_gm.audit WHERE operation_id=%s',(op,));assert q.fetchone()['n']==1
        q.execute('SELECT cera FROM taiwan_billing.cash_cera WHERE account=900001');assert q.fetchone()['cera']==1000
    assert len(list((root/'inbox').glob('*.confirm.json')))==1
    assert c.post(BASE+'/requests/'+op+'/cancel').status_code==409
    # The preparation-only root worker refuses rather than performing an
    # incomplete game exit which would strand the administrator.
    worker.tick()
    r=c.get(BASE+'/requests/'+op).json()
    assert r['result']['state']=='rejected' and not host.calls


def test_same_prepare_id_recovers_even_when_worker_or_permission_unavailable(setup):
    c,s,db,app,worker,coordinator,host,root=setup
    op,_=start(setup);(root/'status.json').unlink();s.writes=tuple(x for x in s.writes if x!='maintenance')
    r=c.post(BASE+'/requests',json={'request_id':op,'reason':'调整测试角色装备'});assert r.status_code==200
    assert c.post(BASE+'/requests',json={'request_id':op,'reason':'换个原因'}).status_code==409
    assert c.get(BASE+'/requests/'+op).status_code==200
    assert c.post(BASE+'/requests/'+op+'/cancel').status_code==200
    assert not host.calls


def test_permission_can_be_enabled_in_web_policy_without_ssh(setup):
    c,s,db,app,*_=setup
    s.writes=tuple(x for x in s.writes if x!='maintenance')
    assert not c.get(BASE).json()['enabled']
    response=c.post('/dnf-gm/api/v1/capabilities/policy',json={'request_id':uuid.uuid4().hex,'expected_revision':0,'enabled':['maintenance'],'reason':'开启网页维护'})
    assert response.status_code==200,response.text
    assert c.get(BASE).json()['enabled']
    start(setup)


@pytest.mark.parametrize('case',['unknown','stale','pvf','image','program'])
def test_unknown_stale_or_version_changed_worker_cannot_prepare(setup,case):
    c,s,db,app,worker,coordinator,host,root=setup
    path=root/'status.json';doc=json.loads(path.read_text())
    if case=='unknown':path.unlink()
    else:
        key={'stale':'collected_at','pvf':'pvf_sha256','image':'image_digest','program':'program_sha256'}[case]
        doc[key]=0 if case=='stale' else 'changed';atomic_json(path,doc)
    op=uuid.uuid4().hex
    assert c.post(BASE+'/requests',json={'request_id':op,'reason':'维护原因'}).status_code==409
    assert not list((root/'inbox').iterdir()) and not host.calls


@pytest.mark.parametrize('changes',[{'acknowledge_disconnect':False},{'acknowledge_disconnect':'true'},{'fingerprint':'0'*64}])
def test_acknowledgement_and_plan_must_match(setup,changes):
    c,*_=setup;op,_=start(setup);detail=make_confirmable(setup,op)
    assert confirm(c,op,detail,**changes).status_code in (409,422)
    assert c.get(BASE+'/requests/'+op).json()['status']=='preparing'


def test_expired_plan_or_corrupt_receipt_cannot_confirm_or_requeue(setup):
    c,s,db,app,worker,coordinator,host,root=setup
    op,_=start(setup);detail=make_confirmable(setup,op);p=root/'results'/(op+'.json')
    receipt=json.loads(p.read_text());receipt['expires_at']=0;atomic_json(p,receipt)
    assert confirm(c,op,detail).status_code==409
    receipt['request_sha256']='0'*64;atomic_json(p,receipt)
    assert c.get(BASE+'/requests/'+op).json()['receipt_error']
    assert c.post(BASE+'/requests/'+op+'/dispatch').status_code==409
    assert not host.calls


def test_untrusted_receipt_file_and_extra_fields_are_not_exposed(setup,tmp_path):
    c,s,db,app,worker,coordinator,host,root=setup
    op,_=start(setup);worker.tick();p=root/'results'/(op+'.json')
    data=json.loads(p.read_text());data['private_plan']={'password':'do-not-expose'};atomic_json(p,data)
    assert 'do-not-expose' not in c.get(BASE+'/requests/'+op).text
    target=tmp_path/'receipt';p.rename(target);p.symlink_to(target)
    assert c.get(BASE+'/requests/'+op).json()['receipt_error']
    assert not host.calls


def test_origin_csrf_recent_password_and_generic_confirm_cannot_bypass(setup):
    c,s,db,app,worker,coordinator,host,root=setup
    op,_=start(setup);detail=make_confirmable(setup,op)
    payload={'idempotency_key':'fixture-confirm-key-01','fingerprint':detail['result']['fingerprint'],'acknowledge_disconnect':True}
    assert c.post(BASE+'/requests/'+op+'/confirm',headers={'Origin':'https://evil.invalid'},json=payload).status_code==403
    assert c.post(BASE+'/requests/'+op+'/confirm',headers={'X-CSRF-Token':'bad'},json=payload).status_code==403
    assert c.post('/dnf-gm/api/v1/operations/'+op+'/confirm',json={'idempotency_key':'fixture-confirm-key-01'}).status_code==409
    with db.connect() as conn,conn.cursor() as q:q.execute('UPDATE dnf_gm.sessions SET authenticated_at=0');conn.commit()
    assert confirm(c,op,detail).status_code==403
    assert c.get(BASE+'/requests/'+op).status_code==200
    assert not host.calls


def test_unauthenticated_and_input_injection_rejected(setup):
    c,s,db,app,worker,coordinator,host,root=setup
    assert c.post(BASE+'/requests',json={'request_id':uuid.uuid4().hex,'reason':'维护','command':'rm -rf /'}).status_code==422
    assert c.post(BASE+'/requests',json={'request_id':'../../bad','reason':'维护'}).status_code==422
    assert c.get(BASE+'/requests?cursor=bad').status_code==422
    c.cookies.clear()
    assert c.get(BASE).status_code==401
    assert c.get(BASE+'/requests').status_code==401
    assert not host.calls


def test_cancel_before_worker_prepare_is_persistent_tombstone(setup):
    c,s,db,app,worker,coordinator,host,root=setup
    op,_=start(setup)
    c.post(BASE+'/requests/'+op+'/cancel')
    worker.tick();worker.tick()
    assert c.get(BASE+'/requests/'+op).json()['result']['state']=='cancelled'
    assert not host.calls
    assert coordinator._active() is None


def test_outbox_failure_keeps_db_request_and_explicit_same_id_dispatch(setup,monkeypatch):
    c,s,db,app,worker,coordinator,host,root=setup
    original=mod.atomic_json
    def fail(*a,**kw):raise OSError('private credentials must not leak')
    monkeypatch.setattr(mod,'atomic_json',fail)
    op=uuid.uuid4().hex
    r=c.post(BASE+'/requests',json={'request_id':op,'reason':'测试投递失败'})
    assert r.status_code==503 and 'credentials' not in r.text
    result=c.get(BASE+'/requests/'+op).json();assert result['status']=='preparing' and result['retry_dispatch_allowed']
    monkeypatch.setattr(mod,'atomic_json',original)
    assert c.post(BASE+'/requests/'+op+'/dispatch').status_code==200
    worker.tick();assert c.get(BASE+'/requests/'+op).json()['result']['state']=='prepared'
    assert not host.calls


def test_history_cursor_retains_same_second_requests(setup):
    c,s,db,app,*_=setup
    with db.connect() as conn,conn.cursor() as q:
        for i in range(35):
            op=f'{i:032x}'
            q.execute("INSERT INTO dnf_gm.operations(operation_id,session_hash,fingerprint,action,request_json,preview_json,status,created_at,expires_at) VALUES(%s,%s,%s,'maintenance',%s,'{}','cancelled',1000,1300)",(op,'a'*64,'b'*64,json.dumps({'reason':'history'})))
        conn.commit()
    first=c.get(BASE+'/requests').json();second=c.get(BASE+'/requests?cursor='+first['next_cursor']).json()
    ids=[r['operation_id'] for r in first['items']+second['items']]
    assert len(set(ids))==len(ids)==35 and second['next_cursor'] is None


@pytest.mark.parametrize('phase',['prepare','confirm','cancel'])
def test_audit_failure_rolls_back_request_state_and_never_dispatches(setup,phase):
    c,s,db,app,worker,coordinator,host,root=setup
    if phase!='prepare':op,_=start(setup);detail=make_confirmable(setup,op)
    else:op=uuid.uuid4().hex
    with db.connect() as conn,conn.cursor() as q:
        q.execute("CREATE TRIGGER dnf_gm.reject_maintenance_audit BEFORE INSERT ON dnf_gm.audit FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic failure'");conn.commit()
    if phase=='prepare':r=c.post(BASE+'/requests',json={'request_id':op,'reason':'维护审计失败'})
    elif phase=='confirm':r=confirm(c,op,detail)
    else:r=c.post(BASE+'/requests/'+op+'/cancel')
    assert r.status_code==500
    result=c.get(BASE+'/requests/'+op)
    assert result.status_code==404 if phase=='prepare' else result.json()['status']=='preparing'
    assert not list((root/'inbox').glob('*.confirm.json')) and not list((root/'inbox').glob('*.cancel.json'))
    assert not host.calls


def test_explicit_observation_is_readonly_and_available_with_switch_off(setup):
    c,s,db,app,worker,coordinator,host,root=setup
    op,_=start(setup);worker.tick()
    s.writes=tuple(x for x in s.writes if x!='maintenance')
    before=(coordinator.root/(op+'.json')).read_bytes()
    for _ in range(2):
        response=c.post(BASE+'/requests/'+op+'/observe')
        assert response.status_code==200,response.text
        assert response.json()['observation_pending']
    assert len(list((root/'inbox').glob('*.observe.json')))==1
    worker.tick()
    result=c.get(BASE+'/requests/'+op).json()
    assert not result['observation_pending']
    assert result['result']['observation']['state']=='observed'
    assert not result['result']['observation']['maintenance_permit']
    assert not host.calls and (coordinator.root/(op+'.json')).read_bytes()==before
    # Looking up the old result never queues a new host probe.
    c.get(BASE+'/requests/'+op)
    assert not list((root/'inbox').glob('*.json'))


def test_observation_has_origin_csrf_and_readiness_guards(setup):
    c,s,db,app,worker,coordinator,host,root=setup
    op,_=start(setup)
    assert c.post(BASE+'/requests/'+op+'/observe').status_code==409
    worker.tick()
    assert c.post(BASE+'/requests/'+op+'/observe',headers={'Origin':'https://other.test'}).status_code==403
    assert c.post(BASE+'/requests/'+op+'/observe',headers={'X-CSRF-Token':'invalid'}).status_code==403
    assert c.post(BASE+'/requests/'+'f'*32+'/observe').status_code==404
    assert not list((root/'inbox').glob('*.observe.json')) and not host.calls


@pytest.mark.parametrize('phase',['prepare','confirm','cancel'])
@pytest.mark.parametrize('committed',[False,True])
def test_commit_response_loss_is_only_reconciled_by_original_id(setup,phase,committed):
    from dnfgm.db import Database
    c,s,db,app,worker,coordinator,host,root=setup
    if phase!='prepare':op,_=start(setup);detail=make_confirmable(setup,op)
    else:op=uuid.uuid4().hex
    class LostCommit:
        def __init__(self,conn):self.conn=conn
        def __getattr__(self,name):return getattr(self.conn,name)
        def commit(self):
            if committed:self.conn.commit()
            raise ConnectionError('synthetic lost commit reply')
    # Only the maintenance service's transactions, not auth/rate-limit fixtures.
    app.state.maintenance.db=Database(s,lambda:LostCommit(db.factory()))
    if phase=='prepare':r=c.post(BASE+'/requests',json={'request_id':op,'reason':'核对提交断线'})
    elif phase=='confirm':r=confirm(c,op,detail)
    else:r=c.post(BASE+'/requests/'+op+'/cancel')
    assert r.status_code==503,r.text
    app.state.maintenance.db=db
    result=c.get(BASE+'/requests/'+op)
    if phase=='prepare' and not committed:
        assert result.status_code==404
    else:
        expected={'prepare':'preparing','confirm':'queued','cancel':'cancelled'}[phase] if committed else 'preparing'
        assert result.status_code==200 and result.json()['status']==expected
    assert not list((root/'inbox').glob('*.json')) and not host.calls
    with db.connect() as conn,conn.cursor() as q:
        action={'prepare':'maintenance-prepare','confirm':'maintenance-confirm','cancel':'maintenance-cancel'}[phase]
        q.execute('SELECT COUNT(*) n FROM dnf_gm.audit WHERE action=%s',(action,))
        assert q.fetchone()['n']==int(committed)


def test_confirm_and_cancel_race_has_exactly_one_durable_outcome(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    c,s,db,app,worker,coordinator,host,root=setup
    op,_=start(setup);detail=make_confirmable(setup,op)
    with db.connect() as conn,conn.cursor() as q:
        row=app.state.maintenance.row(q,op)
    gate=Barrier(2)
    def run(action):
        gate.wait()
        try:
            if action=='confirm':return app.state.maintenance.confirm(row['session_hash'],op,{'idempotency_key':'fixture-concurrent-confirm','fingerprint':detail['result']['fingerprint'],'acknowledge_disconnect':True})
            return app.state.maintenance.cancel(op)
        except HTTPException as error:return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,['confirm','cancel']))
    assert sum(isinstance(r,dict) for r in results)==1 and 409 in results
    current=c.get(BASE+'/requests/'+op).json()
    assert current['status'] in ('queued','cancelled')
    phase='confirm' if current['status']=='queued' else 'cancel'
    assert sorted(p.name for p in (root/'inbox').glob('*.json'))==[op+'.'+phase+'.json']
    with db.connect() as conn,conn.cursor() as q:
        q.execute("SELECT action FROM dnf_gm.audit WHERE action IN ('maintenance-confirm','maintenance-cancel')")
        assert [r['action'] for r in q.fetchall()]==['maintenance-'+phase]
    assert not host.calls


@pytest.mark.parametrize('state',['frozen','unknown','not_configured'])
def test_prepared_request_cannot_offer_confirmation_without_open_gate(setup,state):
    from maintenance_gate import WriteGateManager
    c,s,db,app,worker,coordinator,host,root=setup
    op,_=start(setup);detail=make_confirmable(setup,op)
    assert detail['can_confirm']
    if state=='not_configured':s.gameplay_gate_dir=''
    elif state=='unknown':(Path(s.gameplay_gate_dir)/'state.json').unlink()
    else:WriteGateManager(s.gameplay_gate_dir,owner=os.geteuid()).freeze(op,{**host.ident,'boot_id':'11111111-2222-3333-4444-555555555555'})
    assert c.get(BASE).json()['write_gate']['state']==state
    assert not c.get(BASE+'/requests/'+op).json()['can_confirm']
    result=confirm(c,op,detail);assert result.status_code==409,result.text
    assert not list((root/'inbox').glob('*.confirm.json'))
    assert not host.calls


def test_writers_stopped_receipt_is_readable_but_not_a_window_or_resume_authority(setup):
    c,s,db,app,worker,coordinator,host,root=setup
    op,_=start(setup);worker.tick();path=root/'results'/(op+'.json')
    receipt=json.loads(path.read_text())
    receipt.update(state='writers_stopped',can_confirm=False,can_cancel=False,
                   maintenance_permit=False,can_resume=False,can_replay=False)
    atomic_json(path,receipt)
    response=c.get(BASE+'/requests/'+op)
    assert response.status_code==200
    result=response.json()
    assert not result.get('receipt_error')
    assert result['result']['state']=='writers_stopped'
    assert not result['can_confirm']
    assert not result['result']['maintenance_permit']
    assert not result['result']['can_resume']
    assert not host.calls
