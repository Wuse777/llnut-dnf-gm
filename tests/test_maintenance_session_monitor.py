"""Restore monitoring is read-only, bounded and never a game-write permit."""
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
from maintenance_session_monitor import SessionMonitor
from maintenance_session_state import load
from dnfgm.release_files import Refused, atomic_json, canonical
from test_maintenance_session import session
from test_service_lifecycle import rig, RID


def interrupted(session):
    s,c,h,plan=session;s.open(RID);original=c.writer;once=[True]
    def writer(path,doc,mode):
        original(path,doc,mode=mode)
        if path.name.startswith('session-') and doc.get('events') and doc['events'][-1]['phase']=='restore-start-intent' and once[0]:
            once[0]=False;raise OSError('synthetic lost intent receipt')
    c.writer=writer
    assert s.close_restore(RID)['state']=='needs_review'
    return SessionMonitor(c,s.window.root)


def test_monitor_accepts_each_durable_restore_phase_without_writes(session):
    s,c,h,plan=session;s.open(RID);original=c.writer;observed=[]
    def writer(path,doc,mode):
        original(path,doc,mode=mode)
        if path.name.startswith('session-') and doc.get('events'):
            before=copy.deepcopy(h.calls)
            status=SessionMonitor(c,s.window.root).status()
            assert h.calls==before
            if status is not None:
                assert status.get('maintenance_permit') is not True
                assert status['verified'] or status['active'] is False
                observed.append(doc['events'][-1]['phase'])
    c.writer=writer
    assert s.close_restore(RID)['state']=='completed'
    assert 'window-closed' in observed and 'restore-start-intent' in observed and 'gate-released' in observed
    assert SessionMonitor(c,s.window.root).status()['active'] is False
    c.clock=lambda:10**12;c.monotonic=lambda:10**12
    assert SessionMonitor(c,s.window.root).status()['active'] is False


@pytest.mark.parametrize('case',['resident','contract','unplanned_start','reverted_marker','gate','closed','wall','monotonic','identity'])
def test_monitor_never_waives_unplanned_changes_and_only_refreshes_recovery_visibility(session,case):
    s,c,h,plan=session;monitor=interrupted(session)
    assert monitor.status()['verified']
    doc=s._load(RID,plan);first=plan['service_cycle']['start_order'][0]
    if case=='resident':h.rows['mysql']=(False,False,False,True,-1)
    elif case=='contract':h.contracts[first]['startup']='f'*64
    elif case=='unplanned_start':
        untouched=plan['service_cycle']['start_order'][-1]
        h.rows[untouched]=tuple(plan['service_cycle']['entries'][untouched]['before'])
    elif case=='reverted_marker':h.rows[first]=(False,False,False,True,-1)
    elif case=='gate':
        token=c.admission.gate.read();c.admission.gate.save({**token,'state':'open'})
    elif case=='closed':atomic_json(s.window.root/'closed.json',{'id':RID,'safe_to_resume':True})
    elif case=='wall':c.clock=lambda:10**12
    elif case=='monotonic':c.monotonic=lambda:10**12
    else:h.ident['container_id']='f'*64
    calls=copy.deepcopy(h.calls)
    try:result=monitor.status()
    except Refused:pass
    else:
        if case in ('wall','monotonic'):
            assert result['verified'] and result['authority']=='recovery-only' and result['maintenance_permit'] is False
        else:assert not result['verified']
    assert h.calls==calls and s._load(RID,plan)==doc


def test_monitor_binds_restored_process_identity_not_just_pid(session):
    s,c,h,plan=session;s.open(RID);original=c.writer;once=[True]
    def writer(path,doc,mode):
        original(path,doc,mode=mode)
        if path.name.startswith('session-') and doc.get('events') and doc['events'][-1]['phase']=='service-restored' and once[0]:
            once[0]=False;raise OSError('synthetic result loss')
    c.writer=writer;s.close_restore(RID)
    monitor=SessionMonitor(c,s.window.root);assert monitor.status()['verified']
    first=plan['service_cycle']['start_order'][0];h.processes[first]['start_ticks']+=1
    with pytest.raises(Refused,match='maintenance_restore_unexpected_state'):monitor.status()


def test_completed_root_request_requires_valid_complete_session(session):
    s,c,h,plan=session
    raw=c._load(RID);raw['state']='completed';c._write(RID+'.json',raw)
    with pytest.raises((Refused,FileNotFoundError)):c.status(RID)


@pytest.mark.parametrize('field',['state','gate_generation','window_binding','restored_program'])
def test_rehashed_inconsistent_receipts_are_not_completion_proofs(session,field):
    s,c,h,plan=session;s.open(RID);s.close_restore(RID)
    path=c.root/('session-'+RID+'.json');doc=json.loads(path.read_text())
    if field=='state':doc['state']='maintenance_open'
    elif field=='gate_generation':next(e['data'] for e in doc['events'] if e['phase']=='gate-released')['generation']+=1
    elif field=='window_binding':next(e['data'] for e in doc['events'] if e['phase']=='window-closed')['binding']['policy_sha256']='f'*64
    else:next(e['data'] for e in doc['events'] if e['phase']=='service-restored')['process']['program_sha256']='f'*64
    doc['digest']=hashlib.sha256(canonical({k:v for k,v in doc.items() if k!='digest'})).hexdigest()
    atomic_json(path,doc,mode=0o600)
    with pytest.raises(Refused):c.status(RID)


def test_completed_request_can_release_logical_ownership_without_erasing_history(session):
    from check_maintenance_idle import assert_idle
    s,c,h,plan=session;s.open(RID);s.close_restore(RID)
    assert c.status(RID)['state']=='completed'
    assert_idle(state=c.root,runtime=s.window.root,gate=c.admission.gate.root,owner=os.geteuid())
    next_id='b'*32
    assert c.prepare(next_id,'下一次合成维护')['state']=='prepared'
    assert c._active()==next_id and c.status(RID)['state']=='completed'
    assert s.close_restore(RID)['state']=='completed'  # Historical request does not reclaim ownership.
    assert c._active()==next_id


@pytest.mark.parametrize('after',[False,True])
def test_lost_retirement_receipt_reconciles_without_restarting_services(session,after):
    s,c,h,plan=session;s.open(RID);original=c.writer;once=[True]
    def writer(path,doc,mode):
        hit=path.name==RID+'.json' and doc.get('state')=='completed' and once[0]
        if hit and not after:once[0]=False;raise OSError('synthetic retirement failure')
        original(path,doc,mode=mode)
        if hit:once[0]=False;raise OSError('synthetic retirement response loss')
    c.writer=writer
    assert s.close_restore(RID)['state']=='completed'
    assert c.status(RID)['state']==('completed' if after else 'needs_review')
    commands=copy.deepcopy(h.calls)
    assert s.close_restore(RID)['state']=='completed'
    assert c.status(RID)['state']=='completed' and h.calls==commands


def test_public_status_includes_restore_history_but_never_private_processes(session):
    s,c,h,plan=session;interrupted(session)
    result=c.status(RID)
    assert result['state']=='needs_review' and result['phase']=='restore-start-intent'
    assert any(e['phase']=='window-closed' for e in result['events'])
    assert [e['sequence'] for e in result['events']]==list(range(1,len(result['events'])+1))
    text=json.dumps(result)
    for private in ('server_uuid','program_sha256','start_ticks','binding_sha256'):
        assert private not in text
    observed=c.observe(RID)
    assert observed['state']=='observed'
    assert any(x['state']=='restore_start_pending' for x in observed['services'])
    assert not observed['maintenance_permit']


def test_installed_monitor_dispatches_restoration_observer_without_refresh_lock(session,monkeypatch):
    import inventory_window
    import maintenance_drain
    import service_lifecycle
    from types import SimpleNamespace
    s,c,h,plan=session;interrupted(session)
    monkeypatch.setattr(maintenance_drain,'STATE',c.root)
    monkeypatch.setattr(maintenance_drain,'DrainCoordinator',lambda *a,**kw:c)
    monkeypatch.setattr(service_lifecycle,'ServiceHost',lambda probe:h)
    adapter=object.__new__(inventory_window.MonitorWindow)
    adapter.manager=SimpleNamespace(root=s.window.root,probe=None)
    adapter.monitored_components=('mysql','llnut_gate','game_siroco11')
    before=copy.deepcopy(h.calls)
    with s.window.locked(True):  # Real restore lock must not block the monitor.
        status=adapter.status()
    assert status['verified'] and status['authority']=='recovery-only'
    assert not status['maintenance_permit'] and h.calls==before


def test_completed_deployment_preflight_remains_stdlib_only(session):
    import subprocess
    s,c,h,plan=session;s.open(RID);s.close_restore(RID)
    repo=Path(__file__).resolve().parents[1]
    code=f'''import sys
sys.path[:0]=[{str(repo/'src')!r},{str(repo/'deploy')!r}]
from check_maintenance_idle import assert_idle
assert_idle(state={str(c.root)!r},runtime={str(s.window.root)!r},gate={str(c.admission.gate.root)!r},owner={os.geteuid()})
assert not any(n in sys.modules for n in ('pymysql','fastapi','cryptography'))
'''
    result=subprocess.run([sys.executable,'-I','-S','-c',code],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('required',['game_template','missing_service'])
def test_restore_does_not_waive_original_core_component_failure(session,required):
    s,c,h,plan=session;interrupted(session)
    with pytest.raises(Refused,match='maintenance_preexisting_component_failure'):
        SessionMonitor(c,s.window.root,required_components=(required,)).status()


def test_expired_window_keeps_recovery_available_without_renewing_writes(session):
    s,c,h,plan=session;s.open(RID)
    permit=json.loads((s.window.root/'permit.json').read_text())
    before={p.name:p.read_bytes() for p in s.window.root.iterdir() if p.is_file()}
    c.clock=lambda:permit['expires_at']+1
    c.monotonic=lambda:permit['expires_monotonic']+1
    s.window.clock=c.clock;s.window.monotonic=c.monotonic
    commands=copy.deepcopy(h.calls)
    status=SessionMonitor(c,s.window.root).recovery(s.window)
    assert status['verified'] and status['authority']=='recovery-only'
    assert status['write_window_expired'] and status['maintenance_permit'] is False
    assert before=={p.name:p.read_bytes() for p in s.window.root.iterdir() if p.is_file()}
    assert commands==h.calls
    from dnfgm.inventory_fence import validate_permit
    with pytest.raises(Refused,match='maintenance_permit_expired'):
        validate_permit(permit,c.clock(),c.monotonic())
    h.rows['mysql']=(False,False,False,True,-1)
    with pytest.raises(Refused):SessionMonitor(c,s.window.root).recovery(s.window)


def test_live_window_cannot_claim_expired_recovery(session):
    s,c,h,plan=session;s.open(RID)
    with pytest.raises(Refused,match='maintenance_recovery_not_expired'):
        SessionMonitor(c,s.window.root).recovery(s.window)
