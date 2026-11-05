import copy
import hashlib
import os
from pathlib import Path
import sys
import time

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
from maintenance_outbox import PreparationWorker, validate_packet
from maintenance_drain import DrainCoordinator
from maintenance_fixtures import admission
from dnfgm.maintenance_requests import packet
from dnfgm.release_files import atomic_json, read_json, Refused
from test_game_drain import FakeHost

OP='c'*32


@pytest.fixture
def rig(tmp_path):
    root=tmp_path/'transport';root.mkdir(mode=0o755)
    (root/'results').mkdir(mode=0o755);(root/'inbox').mkdir(mode=0o770)
    h=FakeHost();h.cfg.update({k:h.ident[k] for k in ('image_digest','pvf_sha256','program_sha256')})
    c=DrainCoordinator(tmp_path/'journal',h,owner=os.geteuid(),admission=admission(tmp_path));c.initialize()
    worker=PreparationWorker(root,c,os.geteuid(),owner=os.geteuid())
    request={'operation_id':OP,'reason':'维护测试','created_at':int(time.time()),**{k:h.ident[k] for k in ('image_digest','pvf_sha256','program_sha256')}}
    return root,h,c,worker,request


def send(rig,phase,**kw):
    root,h,c,w,request=rig
    data=packet(request,phase,**kw);path=root/'inbox'/(OP+'.'+phase+'.json');atomic_json(path,data,mode=0o600)
    return path,data


def receipt(root):return read_json(root/'results'/(OP+'.json'),owner=os.geteuid())


def test_plan_and_cancel_are_real_persistent_flow_with_no_signal(rig):
    root,h,c,w,request=rig
    send(rig,'prepare');assert w.tick()['processed']==1
    result=receipt(root);assert result['state']=='prepared' and result['fingerprint']==c.status(OP)['fingerprint']
    assert read_json(root/'status.json')['execute_supported'] is False
    assert not h.calls
    send(rig,'cancel');w.tick();assert receipt(root)['state']=='cancelled'
    send(rig,'prepare');w.tick();assert receipt(root)['state']=='cancelled' and not h.calls


def test_observe_is_readonly_and_does_not_grant_fence(rig):
    root,h,c,w,_=rig;send(rig,'prepare');w.tick();before=(c.root/(OP+'.json')).read_bytes()
    send(rig,'observe');w.tick();r=receipt(root)
    assert r['observation']['state']=='observed' and not r['observation']['maintenance_permit']
    assert not h.calls and before==(c.root/(OP+'.json')).read_bytes()


def test_forged_confirm_cannot_call_incomplete_game_only_drain(rig):
    root,h,c,w,_=rig;send(rig,'prepare');w.tick()
    send(rig,'confirm',fingerprint=c.status(OP)['fingerprint']);w.tick()
    assert receipt(root)['state']=='rejected' and c.status(OP)['state']=='cancelled'
    assert not h.calls


def test_existing_started_execution_is_not_relabelled_as_clean_rejection(rig):
    root,h,c,w,_=rig;send(rig,'prepare');w.tick();p=c.status(OP)
    c.confirm(OP,p['fingerprint']);count=len(h.calls)
    send(rig,'confirm',fingerprint=p['fingerprint']);w.tick()
    assert receipt(root)['state']=='game_drained' and receipt(root)['command_may_have_run']
    assert len(h.calls)==count


@pytest.mark.parametrize('change', ['command','service','signal','path','wrong_hash','wrong_id','wrong_phase','bool_time'])
def test_packets_cannot_introduce_shell_service_path_or_unbound_content(rig,change):
    root,h,c,w,r=rig
    data=packet(r,'prepare')
    if change in ('command','service','signal','path'):data[change]='untrusted'
    elif change=='wrong_hash':data['request_sha256']='0'*64
    elif change=='wrong_id':data['operation_id']='../unsafe'
    elif change=='wrong_phase':data['phase']='restart'
    else:data['request']['created_at']=True
    path=root/'inbox'/(OP+'.prepare.json');atomic_json(path,data,mode=0o600)
    assert w.tick()=={'processed':0,'invalid':1}
    assert not h.calls and not (root/'results'/(OP+'.json')).exists()


def test_old_unprocessed_prepare_expires_without_claiming_maintenance(rig):
    root,h,c,w,r=rig;r['created_at']=1;send(rig,'prepare');w.tick()
    assert receipt(root)['state']=='expired' and c._active() is None and not h.calls


def test_two_request_ids_cannot_bypass_coordinator_ownership(rig):
    root,h,c,w,r=rig;send(rig,'prepare');w.tick();r['operation_id']='d'*32
    data=packet(r,'prepare');atomic_json(root/'inbox'/('d'*32+'.prepare.json'),data,mode=0o600)
    w.tick();other=read_json(root/'results'/('d'*32+'.json'))
    assert other['state']=='rejected' and other['error']=='maintenance_other_request_active'
    assert c._active()==OP and not h.calls


def test_receipt_write_loss_recovers_plan_without_second_host_command(rig,monkeypatch):
    import maintenance_outbox as mod
    root,h,c,w,r=rig;send(rig,'prepare');original=mod.atomic_json
    def fail(path,*a,**kw):
        if path.parent.name=='results':raise OSError('lost receipt')
        return original(path,*a,**kw)
    monkeypatch.setattr(mod,'atomic_json',fail);assert w.tick()['invalid']==1
    assert c.status(OP)['state']=='prepared'
    monkeypatch.setattr(mod,'atomic_json',original);assert w.tick()['processed']==1
    assert receipt(root)['state']=='prepared' and not h.calls


def test_conflicting_existing_receipt_never_overwritten(rig):
    root,h,c,w,r=rig;send(rig,'prepare');w.tick();old=receipt(root);old['request_sha256']='0'*64
    atomic_json(root/'results'/(OP+'.json'),old);before=(root/'results'/(OP+'.json')).read_bytes()
    send(rig,'cancel');assert w.tick()['invalid']==1
    assert before==(root/'results'/(OP+'.json')).read_bytes() and not h.calls


def test_cancel_after_lost_public_receipt_preserves_started_journal(rig):
    root,h,c,w,_=rig;send(rig,'prepare');w.tick()
    c.confirm(OP,c.status(OP)['fingerprint']);calls=list(h.calls)
    (root/'results'/(OP+'.json')).unlink()
    send(rig,'cancel');assert w.tick()['processed']==1
    r=receipt(root)
    assert r['state']=='game_drained' and r['command_may_have_run']
    assert not r['maintenance_permit'] and h.calls==calls


def test_old_prepare_with_missing_public_receipt_reads_original_execution(rig):
    root,h,c,w,r=rig;r['created_at']=int(time.time())-10
    send(rig,'prepare');w.tick();c.confirm(OP,c.status(OP)['fingerprint'])
    (root/'results'/(OP+'.json')).unlink();calls=list(h.calls)
    w.clock=lambda:time.time()+600
    send(rig,'prepare');assert w.tick()['processed']==1
    assert receipt(root)['state']=='game_drained' and h.calls==calls


@pytest.mark.parametrize('phase',['prepare','confirm','cancel','observe'])
def test_missing_active_private_journal_cannot_report_clean_terminal_state(rig,phase):
    root,h,c,w,r=rig;send(rig,'prepare');w.tick();fp=c.status(OP)['fingerprint']
    (root/'results'/(OP+'.json')).unlink();(c.root/(OP+'.json')).unlink()
    send(rig,phase,**({'fingerprint':fp} if phase=='confirm' else {}))
    assert w.tick()=={'processed':0,'invalid':1}
    assert not (root/'results'/(OP+'.json')).exists() and not h.calls


@pytest.mark.parametrize('field',['reason','created_at','image_digest','pvf_sha256','program_sha256'])
def test_lost_public_receipt_cannot_rebind_private_plan(rig,field):
    root,h,c,w,r=rig;send(rig,'prepare');w.tick();original=(c.root/(OP+'.json')).read_bytes()
    (root/'results'/(OP+'.json')).unlink()
    if field=='reason':r[field]='另一个维护原因'
    elif field=='created_at':r[field]+=1
    elif field=='image_digest':r[field]='sha256:'+'f'*64
    else:r[field]='f'*64
    send(rig,'prepare');assert w.tick()=={'processed':0,'invalid':1}
    assert not (root/'results'/(OP+'.json')).exists()
    assert (c.root/(OP+'.json')).read_bytes()==original and not h.calls


def test_cancel_tombstone_survives_public_receipt_loss(rig):
    root,h,c,w,r=rig;send(rig,'cancel');assert w.tick()['processed']==1
    assert receipt(root)['state']=='cancelled' and c._active() is None
    (root/'results'/(OP+'.json')).unlink()
    send(rig,'prepare');assert w.tick()['processed']==1
    assert receipt(root)['state']=='cancelled' and c._active() is None and not h.calls
    assert (root/'bindings').stat().st_mode & 0o077==0
    assert (root/'bindings'/(OP+'.json')).stat().st_mode & 0o077==0
