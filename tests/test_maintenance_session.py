"""Real filesystem locks/journals and synthetic services; no production commands."""
import copy
import os
from contextlib import contextmanager
from pathlib import Path
import sys

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
from maintenance_session import MaintenanceSession
from inventory_window import WindowManager
from dnfgm.release_files import Refused, atomic_json
from test_service_lifecycle import rig, stopped, RID


def make_window(c, h, tmp_path):
    def probe():
        plan=c._load(RID)['plan']
        c.lifecycle.check(plan,c.lifecycle.stopped_snapshot(plan))
        from dnfgm.inventory_fence import BOUND_FIELDS
        binding={**{k:plan['identity'][k] for k in BOUND_FIELDS if k!='components'},'components':list(h.cfg['components'])}
        return {**binding, 'safe':True,'all_writers_down':True,
            'mysql_up':True,'non_game_core_ok':True,'no_unmanaged_processes':True,
            'collected_at':c.clock(),'collected_monotonic':c.monotonic(),
            'process_set_sha256':'d'*64,'mem_available_mib':512,'swap_free_mib':2048}
    window=WindowManager(tmp_path/'window',probe,owner=os.geteuid(),sleep=lambda _:None,
                         clock=c.clock,monotonic=c.monotonic)
    window.initialize()
    return window


class IdentityDB:
    def __init__(self, settings, server):self.settings,self.server=settings,server
    @contextmanager
    def connect(self):yield self
    @contextmanager
    def cursor(self):yield self
    def execute(self, query):assert query=='SELECT @@server_uuid AS server_uuid'
    def fetchone(self):return {'server_uuid':self.server}


@pytest.fixture
def session(rig,tmp_path,monkeypatch):
    c,h,d=rig
    from dnfgm.inventory_fence import boot_id
    h.ident['boot_id']=boot_id()
    c.admission.db=IdentityDB(c.admission.db.settings,c.admission.server_uuid)
    _,plan=stopped(rig)
    window=make_window(c,h,tmp_path)
    def settle(db,window_id,*,expected_server_uuid):
        assert window_id==RID
        assert expected_server_uuid==plan['admission']['server_uuid']
        if db.server!=expected_server_uuid:raise Refused('maintenance_database_identity_changed')
        return {'resolved_aborted':[],'game_writes':False}
    monkeypatch.setattr('maintenance_session.settle_window',settle)
    return MaintenanceSession(c,window,lambda:{'core_ok':True,'services':{'dnf_gateway':True},
        **{k:h.ident[k] for k in ('image_digest','pvf_sha256')}}),c,h,plan


def test_complete_local_window_close_restore_is_bound_and_idempotent(session):
    s,c,h,plan=session;before=copy.deepcopy(h.calls)
    opened=s.open(RID)
    assert opened['state']=='maintenance_open' and opened['window_requires_live_check']
    assert s.window.status()['id']==RID and h.calls==before
    assert s.open(RID)==opened and h.calls==before
    result=s.close_restore(RID)
    assert result['state']=='completed' and not result['can_replay']
    assert c.admission.gate.read()['state']=='open'
    assert s.window.status()['state']=='closed'
    for name,entry in plan['service_cycle']['entries'].items():
        assert list(h.rows[name][:3])==entry['before'][:3]
    commands=copy.deepcopy(h.calls)
    assert s.close_restore(RID)==result and s.open(RID)==result and h.calls==commands
    # Keep the pointer as history, but mark this request finished so a new one can claim it.
    assert c._active()==RID and c.status(RID)['state']=='completed'


def test_closed_guard_blocks_other_issue_and_shared_writes_during_every_restore(session):
    s,c,h,plan=session;s.open(RID);original=h.command;checks=[]
    def command(args,timeout=10):
        if args[3:5]==['s6-svc','-u']:
            with pytest.raises(Refused,match='busy'):
                with s.window.locked(False):pass
            with pytest.raises(Refused,match='busy'):
                s.window.issue(reason='other',acknowledge_writers_stopped=True)
            checks.append(args[-1])
        return original(args,timeout)
    h.command=command
    assert s.close_restore(RID)['state']=='completed'
    assert len(checks)==len(plan['service_cycle']['entries'])


@pytest.mark.parametrize('phase',['window-issue-intent','window-issued','window-close-intent','window-closed',
    'restore-marker-intent','restore-marker-applied','restore-start-intent','restore-start-sent',
    'service-restored','services-restored','gate-release-intent','gate-released','session-completed'])
@pytest.mark.parametrize('after',[False,True])
def test_receipt_loss_never_replays_a_window_or_service_command(session,phase,after):
    s,c,h,plan=session;once=[True]
    if not phase.startswith('window-issue'):s.open(RID)
    def writer(path,doc,mode):
        hit=path.name.startswith('session-') and doc.get('events') and doc['events'][-1]['phase']==phase and once[0]
        if hit and not after:once[0]=False;raise OSError('synthetic loss before persistence')
        atomic_json(path,doc,mode=mode)
        if hit:once[0]=False;raise OSError('synthetic loss after persistence')
    c.writer=writer
    result=s.open(RID) if phase.startswith('window-issue') else s.close_restore(RID)
    commands=copy.deepcopy(h.calls)
    restarted=MaintenanceSession(c,s.window,s.health)
    assert restarted.open(RID)==result
    assert restarted.close_restore(RID)==result
    assert h.calls==commands
    if result['state']=='completed':assert phase=='session-completed' and after
    else:assert result['state']=='needs_review'


@pytest.mark.parametrize('at',['open','close'])
def test_database_replacement_never_issues_or_restores(session,at):
    s,c,h,plan=session
    if at=='close':s.open(RID)
    c.admission.db.server='ffffffff-ffff-ffff-ffff-ffffffffffff'
    before=copy.deepcopy(h.calls)
    with pytest.raises(Refused,match='database_identity_changed'):
        (s.open if at=='open' else s.close_restore)(RID)
    assert h.calls==before and c.admission.gate.read()['state']=='frozen'


def test_failed_database_settlement_revokes_window_without_restoring(session,monkeypatch):
    s,c,h,plan=session;s.open(RID);before=copy.deepcopy(h.calls)
    def fail(*args,**kwargs):raise Refused('maintenance_database_reconciliation_failed')
    monkeypatch.setattr('maintenance_session.settle_window',fail)
    assert s.close_restore(RID)['state']=='needs_review'
    assert s.window.status()['state']=='reconciliation_required'
    assert not (s.window.root/'permit.json').exists()
    assert c.admission.gate.read()['state']=='frozen' and h.calls==before


def test_target_binding_checked_by_issue_under_exclusive_fence(session):
    s,c,h,plan=session;original=s.window.probe
    def probe():return {**original(),'policy_sha256':'f'*64}
    s.window.probe=probe
    assert s.open(RID)['state']=='needs_review'
    assert not (s.window.root/'permit.json').exists()
    assert c.admission.gate.read()['state']=='frozen'


def test_restored_process_replaced_before_release_remains_frozen(session):
    s,c,h,plan=session;s.open(RID);original=c.lifecycle.restore
    def restore(*args):
        result=original(*args)
        h.processes['guild']['start_ticks']+=1
        return result
    c.lifecycle.restore=restore
    result=s.close_restore(RID)
    assert result['state']=='needs_review' and result['error']=='maintenance_restored_process_changed'
    assert c.admission.gate.read()['state']=='frozen'


@pytest.mark.parametrize('field',['core_ok','dnf_gateway','image_digest','pvf_sha256'])
def test_failed_final_health_never_unfreezes(session,field):
    s,c,h,plan=session;s.open(RID);healthy=s.health()
    if field=='dnf_gateway':healthy['services'][field]=False
    else:healthy[field]=False
    s.health=lambda:healthy
    result=s.close_restore(RID)
    assert result['state']=='needs_review' and result['error']=='maintenance_restored_core_unhealthy'
    assert c.admission.gate.read()['state']=='frozen'


def test_close_identity_cannot_be_swapped_after_precheck(session):
    s,c,h,plan=session;s.open(RID)
    before=copy.deepcopy(h.calls);original=s._window_matches
    def swap(*args):
        p=original(*args);p['policy_sha256']='f'*64
        atomic_json(s.window.root/'permit.json',p)
        return p
    s._window_matches=swap
    assert s.close_restore(RID)['state']=='needs_review'
    assert h.calls==before and c.admission.gate.read()['state']=='frozen'


def test_bound_close_receipt_with_maximum_reconciled_ids_remains_readable(session):
    s,c,h,plan=session;s.open(RID)
    binding=s.binding(plan)
    s.window.reconcile=lambda _: {'resolved_aborted':[f'{i:032x}' for i in range(100)],'game_writes':False}
    s.window.close(RID,expected_binding=binding)
    assert (s.window.root/'closed.json').stat().st_size>4096
    assert len(s.window.status()['resolved_aborted'])==100
    with s.window.closed_guard(RID,expected_binding=binding) as proof:assert proof()


def test_close_guard_rejects_receipt_from_another_binding(session):
    s,c,h,plan=session;s.open(RID)
    s.window.reconcile=lambda _: {'resolved_aborted':[],'game_writes':False}
    s.window.close(RID,expected_binding=s.binding(plan))
    wrong={**s.binding(plan),'policy_sha256':'f'*64}
    with pytest.raises(Refused,match='original_window_changed'):
        with s.window.closed_guard(RID,expected_binding=wrong):pass


def test_restored_health_uses_normal_collector_without_maintenance_exception(rig,tmp_path,monkeypatch):
    import json
    import monitor
    from maintenance_session import RestoredHealth
    c,h,d=rig
    cfg=json.loads((Path(__file__).resolve().parents[1]/'deploy/monitor.example.json').read_text())
    cfg.update(container=h.cfg['container'],pvf_path=h.cfg['pvf_path'],inventory_maintenance_enabled=True)
    path=tmp_path/'monitor.json';atomic_json(path,cfg)
    seen=[]
    class Collector:
        def __init__(self,value):seen.append(value)
        def __call__(self):return {'core_ok':True,'synthetic':True}
    monkeypatch.setattr(monitor,'Collector',Collector)
    probe=RestoredHealth(h,path,owner=os.geteuid())
    assert seen[0]['inventory_maintenance_enabled'] is False
    assert probe()=={'core_ok':True,'synthetic':True}
    cfg['container']='other';atomic_json(path,cfg)
    with pytest.raises(Refused,match='health_config_mismatch'):RestoredHealth(h,path,owner=os.geteuid())
    assert not h.calls


def test_gate_cannot_open_when_original_service_contract_changes_on_restore(session):
    s,c,h,plan=session;s.open(RID);original=h.command
    def command(args,timeout=10):
        result=original(args,timeout)
        if args[3:5]==['s6-svc','-u']:
            h.contracts[args[-1].split('/')[-1]]['startup']='f'*64
        return result
    h.command=command
    result=s.close_restore(RID)
    assert result['state']=='needs_review' and c.admission.gate.read()['state']=='frozen'
    assert s.window.status()['safe_to_resume'] is True
