"""Complete synthetic s6 inventory; NEVER calls Docker or signals processes."""
import copy
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
from service_lifecycle import (ServiceLifecycle, ServiceHost, STOP_ORDER, GRACEFUL, FILES,
                               SETTINGS, parse_contract, validate_cycle, is_game, signal_for)
from game_drain import GameDrain, PROGRAMS
from maintenance_drain import DrainCoordinator
from maintenance_fixtures import admission
from dnfgm.release_files import Refused, atomic_json
from test_game_drain import FakeHost

RID='a'*32


def contract(name):
    v={n:'c'*64 for n in FILES}
    for n in SETTINGS:v['value-'+n]=''
    v.update({'down-signal':'absent','timeout-finish':'absent','timeout-kill':'c'*64,
              'value-timeout-kill':'20000','notification-fd':'c'*64,'value-notification-fd':'3'})
    if name in ('auction','point') or is_game(name):v.update({'down-signal':'c'*64,'value-down-signal':'SIGKILL'})
    if name=='community':v.update({'down-signal':'c'*64,'value-down-signal':'SIGUSR2'})
    if name in ('llnut_gate','scheduler'):v.update({'notification-fd':'absent','value-notification-fd':''})
    return v


class FullHost(FakeHost):
    def __init__(self):
        super().__init__()
        cfg=json.loads((Path(__file__).resolve().parents[1]/'deploy/inventory-maintenance.example.json').read_text())
        self.cfg.update(cfg)
        self.rows={}
        for i,n in enumerate(cfg['components'],100):
            if n in cfg['dormant_components']:self.rows[n]=(False,False,n!='game_template',False,-1)
            else:self.rows[n]=(True,True,True,n not in ('mysql','scheduler','llnut_gate'),i)
        self.processes={}
        for n,r in self.rows.items():
            if r[0]:self.processes[n]=self.proc(n,r[4])
        self.contracts={n:contract(n) for n in (*STOP_ORDER,'game_siroco11')}
        self.exits={};self.nextpid=1000

    def proc(self,name,pid):
        return {'pid':pid+10000,'nspid':pid,'start_ticks':pid*10,
                'program_sha256':GRACEFUL.get(name,next(iter(PROGRAMS)) if is_game(name) else 'b'*64),
                'caught':(1<<11)|(1<<14),'ignored':0}

    def contract(self,identity,name):return copy.deepcopy(self.contracts[name])
    def service_process(self,identity,pid):
        for n,r in self.rows.items():
            if r[4]==pid:return copy.deepcopy(self.processes[n])
        raise Refused('maintenance_service_process_unproven')
    def game_process(self,identity,pid):
        p=self.service_process(identity,pid)
        return {k:p[k] for k in ('pid','nspid','start_ticks')}
    def exit_result(self,cid,name):return self.exits.get(name,(0,0))
    def command(self,args,timeout=10):
        assert args[:3]==['docker','exec',self.ident['container_id']]
        self.calls.append(list(args))
        assert not any(a in args for a in ('-d','-D','-k','-K','restart','stop')) if args[3]=='s6-svc' else True
        name=args[-1].removesuffix('/down').split('/')[-1]
        assert name in STOP_ORDER or is_game(name)
        row=list(self.rows[name])
        if args[3:5]==['s6-svc','-O']:row[1]=False
        elif args[3]=='touch':row[2]=False
        elif args[3]=='rm':row[2]=True
        elif args[3:5] in (['s6-svc','-2'],['s6-svc','-t']):pass
        elif args[3:5]==['s6-svc','-u']:
            row[0]=row[1]=True;row[3]=False;row[4]=self.nextpid;self.nextpid+=1
            self.processes[name]=self.proc(name,row[4])
        elif args[3]=='s6-svwait':
            if args[4]=='-D':row=[False,False,False,True,-1]
            elif args[4] in ('-U','-u'):row[3]=args[4]=='-U'
            else:raise AssertionError(args)
        else:raise AssertionError(args)
        self.rows[name]=tuple(row)
        return ''


@pytest.fixture
def rig(tmp_path):
    h=FullHost();cycle=ServiceLifecycle(h)
    c=DrainCoordinator(tmp_path/'journal',h,owner=os.geteuid(),admission=admission(tmp_path),lifecycle=cycle)
    c.initialize()
    return c,h,cycle


def planned(rig):
    c,h,d=rig
    p=c.prepare(RID,'合成完整组件维护')
    return p,c._load(RID)['plan']


def stopped(rig):
    p,plan=planned(rig);c,h,d=rig
    result=c.confirm(RID,p['fingerprint'])
    assert result['state']=='writers_stopped',result
    return result,plan


def test_full_plan_binds_60_services_and_skips_residents_and_dormant(rig):
    p,plan=planned(rig);c,h,d=rig;cycle=plan['service_cycle']
    assert c._load(RID)['version']==3 and not h.calls
    assert len(plan['services_before'])==60
    assert cycle['stop_order']==list(STOP_ORDER)
    assert cycle['start_order'][-3:]==['game_siroco11','scheduler','llnut_gate']
    assert set(cycle['unchanged'])==set(h.cfg['resident_components'])|set(h.cfg['dormant_components'])
    assert all(cycle['entries'][n]['signal']=='SIGUSR2' for n in GRACEFUL)
    assert validate_cycle(plan)==cycle


def test_durable_full_stop_and_explicit_restore_preserve_original_services(rig):
    c,h,d=rig;before=copy.deepcopy(h.rows)
    result,plan=stopped(rig)
    assert result['maintenance_permit'] is False and result['can_resume'] is False
    assert c.admission.gate.read()['state']=='frozen'
    assert h.rows=={k:tuple(v) for k,v in d.stopped_snapshot(plan).items()}
    record=[];checks=[]
    def authority():checks.append(1);return True  # Synthetic root close receipt; not production permission.
    d.restore(plan,lambda phase,data:record.append((phase,data)),authority)
    assert len(checks)==len(plan['service_cycle']['start_order'])*2+1
    for n in plan['service_cycle']['unchanged']:assert h.rows[n]==before[n]
    for n in plan['service_cycle']['entries']:
        assert h.rows[n][:3]==before[n][:3]
        assert h.rows[n][4]!=before[n][4]
    assert record[-1][0]=='services-restored' and record[-1][1]['ordinary_writes_open'] is False
    assert c.admission.gate.read()['state']=='frozen' # Restore alone cannot release it.
    assert all('mysql'!=a[-1].split('/')[-1] for a in h.calls)
    assert not any('systemctl' in a or a[1]=='stop' for a in h.calls)


def test_coordinator_repetition_never_replays_auxiliary_stops(rig):
    c,h,d=rig;result,plan=stopped(rig);calls=copy.deepcopy(h.calls)
    restarted=DrainCoordinator(c.root,h,owner=os.geteuid(),admission=c.admission,lifecycle=d)
    assert restarted.confirm(RID,plan['fingerprint'])==result
    assert h.calls==calls


@pytest.mark.parametrize('name',['guild','scheduler'])
def test_originally_stopped_regular_service_remains_untouched(rig,name):
    c,h,d=rig;h.rows[name]=(False,False,True,False,-1)
    result,plan=stopped(rig)
    assert name not in plan['service_cycle']['entries']
    d.restore(plan,lambda *a:None,lambda:True)
    assert h.rows[name]==(False,False,True,False,-1)
    assert all('/run/service/'+name not in a and '/run/service/'+name+'/down' not in a for a in h.calls)


def test_manually_started_normally_down_worker_restores_marker(rig):
    c,h,d=rig;h.rows['guild']=(True,True,False,True,h.rows['guild'][4])
    _,plan=stopped(rig)
    d.restore(plan,lambda *a:None,lambda:True)
    assert h.rows['guild'][:3]==(True,True,False)


@pytest.mark.parametrize('damage',['unknown-service','resident-down','dormant-up','not-ready','handler','hash','signal','ignored'])
def test_unadapted_plan_cannot_mutate_any_service(rig,damage):
    c,h,d=rig
    if damage=='unknown-service':h.rows['unreviewed']=(True,True,True,True,999);h.cfg['components'].append('unreviewed')
    elif damage=='resident-down':h.rows['mysql']=(False,False,False,False,-1)
    elif damage=='dormant-up':h.rows['netbird']=(True,True,True,False,999)
    elif damage=='not-ready':h.rows['guild']=(True,True,True,False,h.rows['guild'][4])
    elif damage=='handler':h.processes['auction']['caught']=0
    elif damage=='hash':h.processes['point']['program_sha256']='f'*64
    elif damage=='signal':h.contracts['guild']['down-signal']='b'*64;h.contracts['guild']['value-down-signal']='SIGKILL'
    elif damage=='ignored':h.processes['guild']['ignored']=1<<14
    with pytest.raises(Refused):planned(rig)
    assert not h.calls


@pytest.mark.parametrize('name',['auction','point','community'])
def test_sigkill_defaults_never_used_for_graceful_protocols(rig,name):
    _,plan=stopped(rig);c,h,d=rig
    assert ['docker','exec',h.ident['container_id'],'s6-svc','-2','/run/service/'+name] in h.calls
    assert not any(a[3]=='s6-svc' and a[4] in ('-d','-D','-k','-t') and a[-1]=='/run/service/'+name for a in h.calls)


@pytest.mark.parametrize('name,exit_result,ok', [('llnut_gate',(256,15),True),('auction',(256,12),False),('point',(256,9),False),('guild',(2,0),False)])
def test_unexpected_exits_do_not_claim_all_writers_stopped(rig,name,exit_result,ok):
    c,h,d=rig;h.exits[name]=exit_result
    p,plan=planned(rig);result=c.confirm(RID,p['fingerprint'])
    assert result['state']==('writers_stopped' if ok else 'needs_review')
    if not ok:assert result['error']=='maintenance_writer_exit_abnormal'
    assert c.admission.gate.read()['state']=='frozen'


@pytest.mark.parametrize('phase',['writers-stop-started','writer-inhibit-intent','writer-inhibit-applied','writer-marker-intent','writer-marker-applied','writer-signal-intent','writer-signal-sent','writer-stopped','writers-stopped'])
@pytest.mark.parametrize('after',[False,True])
def test_durable_failure_never_replays_auxiliary_commands(rig,phase,after):
    c,h,d=rig;p,plan=planned(rig);once=[True]
    def writer(path,doc,mode):
        hit=doc.get('events') and doc['events'][-1]['phase']==phase and once[0]
        if hit and not after:once[0]=False;raise OSError('synthetic receipt failure')
        atomic_json(path,doc,mode=mode)
        if hit:once[0]=False;raise OSError('synthetic saved-response loss')
    c.writer=writer;result=c.confirm(RID,p['fingerprint']);before=copy.deepcopy(h.calls)
    restarted=DrainCoordinator(c.root,h,owner=os.geteuid(),admission=c.admission,lifecycle=d)
    assert restarted.confirm(RID,p['fingerprint'])==result and h.calls==before
    assert result['state']==('writers_stopped' if phase=='writers-stopped' and after else 'needs_review')
    assert c.admission.gate.read()['state']=='frozen'


def test_restore_refuses_without_root_close_proof(rig):
    _,plan=stopped(rig);c,h,d=rig;before=copy.deepcopy(h.calls)
    with pytest.raises(Refused,match='close_not_proven'):d.restore(plan,lambda *a:None,lambda:False)
    assert h.calls==before
    with pytest.raises(Refused,match='authority_required'):d.restore(plan,lambda *a:None,True)
    assert h.calls==before


@pytest.mark.parametrize('phase',['restore-marker-intent','restore-marker-applied','restore-start-intent','restore-start-sent','service-restored','services-restored'])
def test_restore_stops_on_unrecorded_phase_without_automatic_retry(rig,phase):
    _,plan=stopped(rig);c,h,d=rig;before=len(h.calls)
    def record(p,data):
        if p==phase:raise OSError('synthetic journal failure')
    with pytest.raises(OSError):d.restore(plan,record,lambda:True)
    if phase=='restore-marker-intent':assert len(h.calls)==before
    assert c.admission.gate.read()['state']=='frozen'


def test_service_contract_change_after_preview_refuses_before_target_signal(rig):
    c,h,d=rig;p,plan=planned(rig);h.contracts['llnut_gate']['startup']='e'*64
    result=c.confirm(RID,p['fingerprint'])
    assert result['state']=='needs_review' and result['error']=='maintenance_service_contract_changed'
    assert all(a[-1].startswith('/run/service/game_') for a in h.calls)


def test_service_restart_with_reused_pid_before_stop_is_rejected(rig):
    c,h,d=rig;p,plan=planned(rig);h.processes['llnut_gate']['start_ticks']+=1
    result=c.confirm(RID,p['fingerprint'])
    assert result['error']=='maintenance_service_process_changed'
    assert all(a[-1].startswith('/run/service/game_') for a in h.calls)


def test_restored_wrong_binary_keeps_writes_frozen(rig):
    _,plan=stopped(rig);c,h,d=rig;original=h.command
    def command(args,timeout=10):
        result=original(args,timeout)
        if args[3:5]==['s6-svc','-u']:h.processes[args[-1].split('/')[-1]]['program_sha256']='e'*64
        return result
    h.command=command
    with pytest.raises(Refused,match='restored_program_changed'):d.restore(plan,lambda *a:None,lambda:True)
    assert c.admission.gate.read()['state']=='frozen'


def test_contract_parser_accepts_only_bounded_known_fields():
    expected=contract('auction')
    assert parse_contract('\n'.join(k+'='+v+'\n' for k,v in expected.items()))==expected
    for text in ('x=y', 'x'*8193, '\n'.join(k+'='+v for k,v in expected.items())+'\nstartup=absent'):
        with pytest.raises(Refused):parse_contract(text)


def test_service_host_never_accepts_arbitrary_names(rig):
    c,h,d=rig
    host=object.__new__(ServiceHost);calls=[];host.command=lambda *a:calls.append(a)
    for name in ('mysql','mihomo','docker','../mysql','guild;echo hi','netbird'):
        with pytest.raises(Refused):host.contract(h.ident,name)
    assert not calls


def test_observation_covers_stopped_writers_without_granting_permit(rig):
    from maintenance_drain import DrainMonitor
    _, plan = stopped(rig)
    c, h, d = rig
    commands = copy.deepcopy(h.calls)
    status = DrainMonitor(c).status()
    assert status['verified'] and not status['maintenance_permit']
    assert len(status['services']) == len(plan['service_cycle']['entries'])
    assert all(x['state'] == 'down_normal' for x in status['services'])
    assert h.calls == commands


@pytest.mark.parametrize('phase', ['inhibit-applied', 'marker-intent', 'marker-applied', 'signal-intent', 'signal-sent', 'stopped'])
def test_observation_rejects_reverted_original_state(rig, phase):
    _, plan = planned(rig)
    c, h, d = rig
    observed = d.observe(plan, [{'phase': 'writer-'+phase, 'data': {'service': 'guild'}}])
    assert next(x for x in observed if x['service'] == 'guild')['state'] == 'changed'
    assert not h.calls


@pytest.mark.parametrize('change', ['resident', 'pid_reuse', 'unexpected_stop', 'contract'])
def test_observation_detects_unplanned_changes(rig, change):
    _, plan = planned(rig)
    c, h, d = rig
    if change == 'resident':
        h.rows['mysql'] = (False, False, False, True, -1)
    elif change == 'pid_reuse':
        h.processes['guild']['start_ticks'] += 1
    elif change == 'unexpected_stop':
        h.rows['guild'] = (False, False, False, True, -1)
    else:
        h.contracts['guild']['startup'] = 'f'*64
    if change in ('resident', 'contract'):
        with pytest.raises(Refused): d.observe(plan, [])
    else:
        assert next(x for x in d.observe(plan, []) if x['service'] == 'guild')['state'] == 'changed'
    assert not h.calls


def test_monitor_rechecks_gate_after_observation(rig):
    from maintenance_drain import DrainMonitor
    stopped(rig)
    c, h, d = rig
    original = c.observe
    def observe(request_id):
        result = original(request_id)
        state = c.admission.gate.read()
        c.admission.gate.save({**state, 'state': 'open'})
        return result
    c.observe = observe
    commands = copy.deepcopy(h.calls)
    result = DrainMonitor(c).status()
    assert not result['verified'] and not result['maintenance_permit']
    assert h.calls == commands


def test_restore_checks_closed_proof_again_before_start(rig):
    _, plan = stopped(rig)
    c, h, d = rig
    baseline = len(h.calls)
    proofs = iter([True, False])
    with pytest.raises(Refused, match='close_not_proven'):
        d.restore(plan, lambda *args: None, lambda: next(proofs))
    assert len(h.calls) == baseline+1  # Marker restored, but no start command.
    assert h.calls[-1][3] in ('rm', 'touch')
    assert c.admission.gate.read()['state'] == 'frozen'


from test_inventory_probe import scene


def service_scene(scene):
    cfg, probe, proc, calls, clock, inspect = scene
    status = proc/'103/status'
    status.write_text(status.read_text()+'SigCgt:\t0000000000004800\nSigIgn:\t0000000000000000\n')
    probe.deadline = probe.monotonic()+20
    return ServiceHost(probe), probe.inspect(), proc, calls


def test_service_process_binds_realistic_proc_identity(scene):
    host, identity, proc, calls = service_scene(scene)
    result = host.service_process(identity, 3)
    assert result == {'pid': 103, 'nspid': 3, 'start_ticks': 12345,
                      'program_sha256': scene[0]['process_rules'][2]['sha256'],
                      'caught': 0x4800, 'ignored': 0}
    assert all(args[:2] == ['docker', 'inspect'] for args in calls)


@pytest.mark.parametrize('change', ['namespace', 'signals', 'cgroup', 'start_ticks'])
def test_process_identity_race_during_hash_is_rejected(scene, change):
    host, identity, proc, calls = service_scene(scene)
    original = host.probe.hash_file
    def hash_file(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        entry = proc/'103'
        if change == 'namespace':
            (entry/'ns/pid').unlink(); (entry/'ns/pid').write_text('other namespace')
        elif change == 'signals':
            p=entry/'status';p.write_text(p.read_text().replace('0000000000004800', '0000000000000000'))
        elif change == 'cgroup':
            (entry/'cgroup').write_text('0::/docker/other\n')
        else:
            p=entry/'stat';p.write_text(p.read_text().replace('12345', '12346'))
        return result
    host.probe.hash_file = hash_file
    with pytest.raises(Refused, match='process_unstable'): host.service_process(identity, 3)


@pytest.mark.parametrize('name,startup', [('llnut_gate','/home/template/init/run/start_gate.sh'),
                                        ('auction','/data/run/start_auction.sh'),
                                        ('game_siroco11','/data/run/start_game.sh')])
def test_service_contract_probe_uses_only_fixed_paths(rig, name, startup):
    c,h,d=rig
    host=object.__new__(ServiceHost);calls=[]
    def command(args):
        calls.append(args)
        return '\n'.join(k+'='+v for k,v in contract(name).items())
    host.command=command
    assert host.contract(h.ident,name)==contract(name)
    assert calls[0][:5]==['docker','exec',h.ident['container_id'],'sh','-c']
    assert calls[0][-3:]==['dnfgm-contract','/run/service/'+name,startup]


def test_auxiliary_stop_timeout_never_escalates_or_replays(rig):
    c,h,d=rig;p,plan=planned(rig);original=h.command
    def command(args,timeout=10):
        if args[3]=='s6-svwait' and args[-1]=='/run/service/auction':
            raise TimeoutError('synthetic graceful exit timeout')
        return original(args,timeout)
    h.command=command
    result=c.confirm(RID,p['fingerprint']);calls=copy.deepcopy(h.calls)
    assert result['state']=='needs_review'
    assert c.confirm(RID,p['fingerprint'])==result and h.calls==calls
    assert c.admission.gate.read()['state']=='frozen'


def test_fifo_ack_wait_accepts_only_previous_then_expected(rig):
    c,h,d=rig;_,plan=planned(rig)
    previous=copy.deepcopy(plan['services_before']);expected=copy.deepcopy(previous)
    expected['guild'][1]=False
    samples=iter([previous,previous,expected]);last=[None]
    def services():
        try:last[0]=next(samples)
        except StopIteration:pass
        return {k:tuple(v) for k,v in last[0].items()}
    h.services=services;clock=[0.0]
    d.monotonic=lambda:clock[0];d.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
    d.settle(plan,previous,expected,'guild')
    assert clock[0]==.1 and not h.calls
