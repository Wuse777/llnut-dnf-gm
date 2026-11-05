"""Complete outbox path with durable files and synthetic service processes."""
import copy
import os
from pathlib import Path
import threading
import time

import pytest
from dnfgm.inventory_fence import boot_id
from dnfgm.release_files import Refused, atomic_json, read_json
from dnfgm.maintenance_requests import packet
from maintenance_executor import ExecutionWorker
from maintenance_session import MaintenanceSession
from test_service_lifecycle import rig, RID
from test_maintenance_session import IdentityDB, make_window


class Handshake:
    def __init__(self,host):self.host,self.calls,self.fail=host,[],None
    def check(self,policy,*,healthy=True):
        self.calls.append(healthy)
        if self.fail is not None and self.fail(healthy):raise Refused('maintenance_monitor_snapshot_unhealthy')
        return {'policy_sha256':self.host.ident['policy_sha256'],'healthy':healthy,'maintenance_permit':False}


@pytest.fixture
def worker(rig,tmp_path,monkeypatch):
    c,h,_=rig;h.ident['boot_id']=boot_id()
    h.cfg.update({k:h.ident[k] for k in ('image_digest','pvf_sha256','program_sha256')})
    c.admission.db=IdentityDB(c.admission.db.settings,c.admission.server_uuid)
    window=make_window(c,h,tmp_path)
    def settle(db,window_id,*,expected_server_uuid):
        assert window_id==RID and expected_server_uuid==db.server
        return {'resolved_aborted':[],'game_writes':False}
    monkeypatch.setattr('maintenance_session.settle_window',settle)
    session=MaintenanceSession(c,window,lambda:{'core_ok':True,'services':{'dnf_gateway':True},
        **{k:h.ident[k] for k in ('image_digest','pvf_sha256')}})
    root=tmp_path/'outbox';root.mkdir(mode=0o755)
    (root/'inbox').mkdir(mode=0o770);(root/'results').mkdir(mode=0o755)
    handshake=Handshake(h)
    w=ExecutionWorker(root,c,os.geteuid(),session,handshake,owner=os.geteuid())
    request={'operation_id':RID,'reason':'合成完整维护','created_at':int(time.time()),
             **{k:h.ident[k] for k in ('image_digest','pvf_sha256','program_sha256')}}
    return w,c,h,request


def send(worker,phase):
    w,c,h,request=worker
    args={'fingerprint':c.status(RID)['fingerprint']} if phase in ('confirm','close') else {}
    value=packet(request,phase,**args)
    atomic_json(w.root/'inbox'/(RID+'.'+phase+'.json'),value,mode=0o600)
    return value


def receipt(w):return read_json(w.root/'results'/(RID+'.json'),owner=os.geteuid())


def enter(worker):
    w,c,h,r=worker
    send(worker,'prepare');assert w.tick()['processed']==1
    send(worker,'confirm');assert w.tick()['processed']==1
    assert receipt(w)['state']=='maintenance_open',receipt(w)


def test_full_outbox_enters_window_then_explicitly_restores_original_state(worker):
    w,c,h,r=worker;original=copy.deepcopy(h.rows)
    enter(worker)
    assert w.handshake.calls.count(False)==1
    assert c.admission.gate.read()['state']=='frozen'
    assert w.session.window.status()['state']=='verified'
    count=len(h.calls)
    send(worker,'confirm');w.tick();assert len(h.calls)==count
    send(worker,'close');assert w.tick()['processed']==1
    assert receipt(w)['state']=='completed'
    assert c.admission.gate.read()['state']=='open'
    assert w.session.window.status()['state']=='closed'
    for n,row in original.items():assert h.rows[n][:3]==row[:3]
    commands=copy.deepcopy(h.calls)
    send(worker,'close');w.tick();assert h.calls==commands


@pytest.mark.parametrize('when',['before_freeze','after_settlement'])
def test_unready_monitor_never_sends_game_command(worker,when):
    w,c,h,r=worker;send(worker,'prepare');w.tick()
    w.handshake.fail=lambda healthy:healthy is (True if when=='before_freeze' else False)
    send(worker,'confirm');w.tick()
    assert not h.calls
    if when=='before_freeze':
        assert c.status(RID)['state']=='prepared' and c.admission.gate.read()['state']=='open'
    else:
        assert c.status(RID)['state']=='needs_review' and c.admission.gate.read()['state']=='frozen'
    assert read_json(w.root/'status.json')['execute_supported'] is (when=='after_settlement')


def test_close_cannot_open_or_stop_services(worker):
    w,c,h,r=worker;send(worker,'prepare');w.tick()
    send(worker,'close');w.tick()
    assert c.status(RID)['state']=='prepared' and not h.calls


def test_changed_fingerprint_cannot_restore_wrong_session(worker):
    w,c,h,r=worker;enter(worker);calls=copy.deepcopy(h.calls)
    data=send(worker,'close');data['fingerprint']='f'*64
    atomic_json(w.root/'inbox'/(RID+'.close.json'),data,mode=0o600)
    assert w.tick()['processed']==0 and h.calls==calls
    assert c.admission.gate.read()['state']=='frozen'


def test_crash_after_writers_stop_does_not_replay_or_silently_issue_window(worker,monkeypatch):
    w,c,h,r=worker;send(worker,'prepare');w.tick()
    original=w.session.open
    def crash(op):raise SystemExit('synthetic stop between phases')
    monkeypatch.setattr(w.session,'open',crash);send(worker,'confirm')
    with pytest.raises(SystemExit):w.tick()
    assert c.status(RID)['state']=='writers_stopped'
    commands=copy.deepcopy(h.calls);monkeypatch.setattr(w.session,'open',original)
    w.tick()
    assert h.calls==commands and not (w.session.window.root/'permit.json').exists()
    assert receipt(w)['state']=='writers_stopped'


def test_long_execution_refreshes_only_status_and_never_uses_another_db_connection(worker):
    w,c,h,r=worker;send(worker,'prepare');w.tick();data=send(worker,'confirm')
    calls=[];published=threading.Event();original=w.publish_status
    def publish():calls.append(threading.current_thread().name);original();published.set()
    w.publish_status=publish
    with w.heartbeat(data,interval=.01):assert published.wait(2)
    assert 'gm-maintenance-status' in calls and not h.calls
    assert not any(t.name=='gm-maintenance-status' for t in threading.enumerate())


def test_full_worker_rejects_game_only_adapter(worker):
    w,c,h,r=worker;c.lifecycle=None
    with pytest.raises(Refused,match='full_adapters'):
        ExecutionWorker(w.root,c,os.geteuid(),w.session,w.handshake,owner=os.geteuid())
