"""Real isolated MySQL transactions plus root-private gate fixtures; no production."""
import os
import sys
from pathlib import Path
import uuid
import pytest

from dnfgm import write_gate
from dnfgm.db import Database
from dnfgm.release_files import Refused
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deploy'))
from maintenance_gate import WriteGateManager
from test_application import P,preview,confirm,mail
from test_equipment_unlock import prepare as unlock_seed,preview as unlock_preview,read_blob
from test_combined_rewards import enable,read
from test_reward_jobs import job_preview,start
from test_native_control_api import control, preview as native_preview, BASE,KEY
from test_schedules import scheduled,preview as schedule_preview,activate

OP='f'*32
IDENTITY={'container_id':'c'*64,'pid':101,'boot_id':'11111111-2222-3333-4444-555555555555','container_started_at':'fixture-start',
          'image_digest':'sha256:'+'a'*64,'program_sha256':'b'*64,'pvf_sha256':'d'*64,'policy_sha256':'e'*64}


@pytest.fixture
def gate(env,tmp_path,monkeypatch):
    c,s,db,app=env
    monkeypatch.setattr(write_gate,'ROOT_UID',os.geteuid())
    s.gameplay_gate_dir=str(tmp_path/'write-gate')
    manager=WriteGateManager(s.gameplay_gate_dir,owner=os.geteuid());manager.initialize()
    return manager


@pytest.mark.parametrize('action',['currency','mail','ban','unban','equipment-unlock'])
def test_freeze_refuses_new_game_mutations_and_keeps_reads(env,gate,action):
    c,s,db,app=env;before=None
    if action=='equipment-unlock':
        before=unlock_seed(env);r=unlock_preview(c)
    elif action=='mail':r=mail(c)
    else:
        if action=='unban':
            r=preview(c,action='ban',currency=None,delta=None);assert r.status_code==200
            assert confirm(c,r.json()['operation_id'],'initial-ban-before-freeze').status_code==200
        r=preview(c,action=action,**({} if action=='currency' else {'currency':None,'delta':None}))
    assert r.status_code==200,r.text
    op=r.json()['operation_id'];token=gate.freeze(OP,IDENTITY)
    answer=confirm(c,op);assert answer.status_code==409 and '冻结' in answer.text
    assert c.get(P+'/operations/'+op).json()['status']=='preview'
    for path in ('/auth/me','/accounts/900001','/overview','/audit'):
        assert c.get(P+path).status_code==200
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    assert not read(db,'SELECT * FROM taiwan_cain_2nd.postal')
    assert read(db,'SELECT apply_flag FROM d_taiwan.member_punish_info')==([{'apply_flag':1}] if action=='unban' else [])
    if before is not None:assert read_blob(db)==before
    gate.release(token,lambda:True)
    result=confirm(c,op);assert result.status_code==200,result.text


def test_completed_same_key_confirmation_still_returns_original_during_freeze(env,gate):
    c,s,db,app=env;op=preview(c).json()['operation_id'];before=confirm(c,op)
    assert before.status_code==200
    gate.freeze(OP,IDENTITY)
    assert confirm(c,op).json()==before.json()
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100


def test_web_permissions_cannot_disable_transaction_barrier(env,gate):
    from dnfgm.capability_policy import SWITCHES
    c,s,db,app=env;op=preview(c).json()['operation_id'];gate.freeze(OP,IDENTITY)
    r=c.post(P+'/capabilities/policy',json={'request_id':uuid.uuid4().hex,'expected_revision':0,'enabled':list(SWITCHES),'reason':'网页开放全部权限'})
    assert r.status_code==200,r.text
    assert confirm(c,op).status_code==409
    state=c.get(P+'/maintenance').json()
    assert state['enabled'] and state['write_gate']['state']=='frozen' and state['write_gate']['operation_id']==OP


def test_transaction_lease_spans_actual_commit_and_connection_close(env,gate):
    c,s,db,app=env;op=preview(c).json()['operation_id'];checks=[]
    def busy(stage):
        with pytest.raises(Refused,match='busy'):gate.freeze(OP,IDENTITY)
        checks.append(stage)
    class Connection:
        def __init__(self,conn):self.conn=conn
        def __getattr__(self,name):return getattr(self.conn,name)
        def commit(self):
            busy('before-commit');self.conn.commit();busy('after-commit')
        def close(self):
            busy('before-close');self.conn.close();busy('after-close')
    app.state.service.db=Database(s,lambda:Connection(db.factory()))
    result=confirm(c,op);assert result.status_code==200,result.text
    assert checks==['before-commit','after-commit','before-close','after-close']
    assert gate.freeze(OP,IDENTITY)['state']=='frozen'


def test_unverifiable_configured_gate_blocks_write_but_not_lookup(env,gate):
    c,s,db,app=env;op=preview(c).json()['operation_id'];(gate.root/'state.json').unlink()
    assert confirm(c,op).status_code==409
    assert c.get(P+'/operations/'+op).status_code==200
    assert c.get(P+'/maintenance').json()['write_gate']['state']=='unknown'
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000


def test_batch_freeze_keeps_pending_targets_and_attempts_unchanged(env,gate):
    c,s,db,app=env;enable(s);job=job_preview(c);assert start(c,job).status_code==200
    token=gate.freeze(OP,IDENTITY)
    for _ in range(2):assert app.state.reward_jobs.step() is False
    rows=read(db,'SELECT status,attempts FROM dnf_gm.reward_targets')
    assert rows==[{'status':'pending','attempts':0}]
    assert not read(db,'SELECT * FROM taiwan_cain_2nd.postal')
    assert app.state.reward_jobs.detail(job['id'])['status']=='running'
    gate.release(token,lambda:True)
    assert app.state.reward_jobs.step()
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100
    assert read(db,'SELECT status,attempts FROM dnf_gm.reward_targets')==[{'status':'committed','attempts':1}]


def test_batch_lease_also_covers_game_commit(env,gate,monkeypatch):
    c,s,db,app=env;enable(s);job=job_preview(c);assert start(c,job).status_code==200
    original=app.state.reward_jobs.service.apply_reward
    def apply(*a,**kw):
        result=original(*a,**kw)
        with pytest.raises(Refused,match='busy'):gate.freeze(OP,IDENTITY)
        return result
    monkeypatch.setattr(app.state.reward_jobs.service,'apply_reward',apply)
    assert app.state.reward_jobs.step()
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100
    assert gate.freeze(OP,IDENTITY)['state']=='frozen'


@pytest.mark.parametrize('action',['native-kick','native-notice','native-ban-kick'])
def test_native_freeze_does_not_claim_or_send(control,gate,action):
    c,s,db,app,ops,sent=control
    if action=='native-notice':s.test_uids=()
    op=native_preview(control,action);token=gate.freeze(OP,IDENTITY)
    r=c.post(BASE+'/'+op+'/confirm',json={'idempotency_key':KEY})
    assert r.status_code==409,r.text
    assert not sent and not read(db,'SELECT * FROM d_taiwan.member_punish_info')
    assert ops.detail(op)['status']=='preview'
    gate.release(token,lambda:True)
    r=c.post(BASE+'/'+op+'/confirm',json={'idempotency_key':KEY});assert r.status_code==200,r.text
    assert len(sent)==1
    gate.freeze('e'*32,IDENTITY)
    assert c.post(BASE+'/'+op+'/confirm',json={'idempotency_key':KEY}).status_code==200
    assert len(sent)==1


def test_native_holds_gate_across_claim_and_actual_transport(control,gate):
    c,s,db,app,ops,sent=control;op=native_preview(control);original=ops.transport.kick
    def send(uid):
        with pytest.raises(Refused,match='busy'):gate.freeze(OP,IDENTITY)
        return original(uid)
    ops.transport.kick=send
    r=c.post(BASE+'/'+op+'/confirm',json={'idempotency_key':KEY})
    assert r.status_code==200,r.text
    assert len(sent)==1 and gate.freeze(OP,IDENTITY)['state']=='frozen'


def test_scheduled_occurrence_is_not_consumed_during_freeze(scheduled,gate):
    c,s,db,app,engine,now=scheduled
    item=schedule_preview(scheduled);assert activate(c,item).status_code==200
    now[0]=item['request']['first_due'];token=gate.freeze(OP,IDENTITY)
    assert not engine.step()
    assert not engine.runs(item['id'])['items']
    assert engine.detail(item['id'])['next_due']==now[0]
    assert not read(db,'SELECT * FROM dnf_gm.reward_jobs')
    gate.release(token,lambda:True)
    assert engine.step()
    assert len(engine.runs(item['id'])['items'])==1
    assert len(read(db,'SELECT * FROM dnf_gm.reward_jobs'))==1


def test_unlock_batch_frozen_is_atomic_and_can_resume_original(env,gate):
    from test_unlock_center import seed,batch,stored
    c,s,db,app=env;original=seed(env)
    p=batch(c);assert p.status_code==200,p.text
    op=p.json()['operation_id'];token=gate.freeze(OP,IDENTITY)
    assert confirm(c,op).status_code==409
    assert all(stored(db,cid)==original for cid in (900001,900003))
    assert not read(db,'SELECT * FROM dnf_gm.audit WHERE operation_id=%s',(op,))
    gate.release(token,lambda:True)
    result=confirm(c,op);assert result.status_code==200,result.text
    assert all(stored(db,cid)!=original for cid in (900001,900003))
    gate.freeze('e'*32,IDENTITY)
    assert confirm(c,op).json()==result.json()


def test_combined_reward_blocks_balances_and_mail_together(env,gate):
    from test_mail_gold import preview as reward_preview
    c,s,db,app=env;enable(s)
    p=reward_preview(c,action='reward',currency_rewards={'cera':50,'cera_point':20,'mileage':30},items=[{'id':990002,'quantity':100}])
    assert p.status_code==200,p.text
    op=p.json()['operation_id'];token=gate.freeze(OP,IDENTITY)
    assert confirm(c,op).status_code==409
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    assert not read(db,'SELECT * FROM d_taiwan.member_miles')
    assert not read(db,'SELECT * FROM taiwan_cain_2nd.postal')
    gate.release(token,lambda:True)
    result=confirm(c,op);assert result.status_code==200,result.text
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1050
    assert len(read(db,'SELECT * FROM taiwan_cain_2nd.postal'))==1


def test_audit_failure_rolls_back_then_releases_admission(env,gate):
    c,s,db,app=env;op=preview(c).json()['operation_id']
    with db.connect() as conn,conn.cursor() as q:
        q.execute("CREATE TRIGGER dnf_gm.gate_audit_fail BEFORE INSERT ON dnf_gm.audit FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic audit failure'")
    assert confirm(c,op).status_code==500
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    assert c.get(P+'/operations/'+op).json()['status']=='preview'
    assert gate.freeze(OP,IDENTITY)['state']=='frozen'


def test_commit_response_loss_remains_queryable_without_duplicate_while_frozen(env,gate):
    c,s,db,app=env;op=preview(c).json()['operation_id'];checks=[]
    class LostResponse:
        def __init__(self,conn):self.conn=conn
        def __getattr__(self,name):return getattr(self.conn,name)
        def commit(self):
            self.conn.commit()
            with pytest.raises(Refused,match='busy'):gate.freeze(OP,IDENTITY)
            checks.append('committed')
            raise OSError('synthetic connection loss after database commit')
    app.state.service.db=Database(s,lambda:LostResponse(db.factory()))
    answer=confirm(c,op);assert answer.status_code==503,answer.text
    assert checks==['committed']
    gate.freeze(OP,IDENTITY)
    assert c.get(P+'/operations/'+op).json()['status']=='committed'
    result=confirm(c,op);assert result.status_code==200,result.text
    assert checks==['committed']
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100
    assert len(read(db,'SELECT * FROM dnf_gm.audit WHERE operation_id=%s',(op,)))==1


def test_exclusive_freeze_transition_prevents_new_claim(env,gate):
    from concurrent.futures import ThreadPoolExecutor
    c,s,db,app=env;op=preview(c).json()['operation_id']
    with gate.locked(True),ThreadPoolExecutor(max_workers=1) as worker:
        response=worker.submit(confirm,c,op).result(timeout=10)
        assert response.status_code==409,response.text
    assert c.get(P+'/operations/'+op).json()['status']=='preview'
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    gate.freeze(OP,IDENTITY)
    assert confirm(c,op).status_code==409


def test_health_freeze_suppresses_only_expected_waits_and_resets_progress(scheduled,gate):
    from test_task_health_api import health,codes
    c,s,db,app,engine,now=scheduled
    job=job_preview(c);assert start(c,job).status_code==200
    item=schedule_preview(scheduled);assert activate(c,item).status_code==200
    h=app.state.task_health;monotonic=[0.0];h.clock=lambda:monotonic[0];h.alive=lambda:True
    h.pulse.clock=lambda:monotonic[0];h.wall=lambda:item['request']['first_due']+180
    def snapshot(t):
        monotonic[0]=t
        for name in ('rewards','schedules'):h.pulse.call(name,lambda:False)
        return health(c)
    assert 'overdue' in codes(snapshot(0))
    snapshot(60)
    assert 'no_progress' in codes(snapshot(120))
    token=gate.freeze(OP,IDENTITY)
    for t in (180,240,300):
        result=snapshot(t)
        assert result['state']=='observing' and result['issues']==[]
        assert result['progress']=='maintenance_frozen'
        assert result['write_gate']['operation_id']==OP
    gate.release(token,lambda:True)
    result=snapshot(301)
    assert result['progress']=='observing' and codes(result)==['overdue']


@pytest.mark.parametrize('status',['failed','uncertain','executing'])
def test_health_frozen_does_not_hide_real_target_or_worker_faults(env,gate,status):
    from test_combined_rewards import write
    from test_task_health_api import health,codes,running
    c,s,db,app=env;job=running(env)
    write(db,"UPDATE dnf_gm.reward_targets SET status=%s,last_attempt=0 WHERE job_id=%s",(status,job['id']))
    gate.freeze(OP,IDENTITY)
    result=health(c)
    assert result['state']=='attention'
    assert status in codes(result) and 'worker_stopped' in codes(result)
    assert result['write_gate']['state']=='frozen'


def test_health_missing_gate_never_claims_clear(env,gate):
    from test_task_health_api import health
    c,s,db,app=env;(gate.root/'state.json').unlink()
    result=health(c)
    assert result['state']=='unknown' and result['write_gate']['state']=='unknown'


def test_health_gate_changes_during_snapshot_never_claims_clear(env,gate,monkeypatch):
    from test_task_health_api import health
    c,s,db,app=env;original=write_gate.GameplayWriteGate.status;calls=[]
    def transition(instance):
        calls.append(True)
        if len(calls)==2:gate.freeze(OP,IDENTITY)
        return original(instance)
    monkeypatch.setattr(write_gate.GameplayWriteGate,'status',transition)
    result=health(c)
    assert len(calls)==2
    assert result['state']=='unknown' and result['write_gate']['state']=='frozen'
