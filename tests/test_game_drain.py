"""Synthetic fixed s6 driver. Never signals a process or connects to Docker."""
import copy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
from game_drain import GameDrain, PROGRAMS, DEPENDENCIES, Refused


class FakeHost:
    def __init__(self):
        self.cfg={'components':['mysql','game_siroco11','game_template','mysql-log']}
        self.ident={'container_id':'c'*64,'pid':101,'boot_id':'12345678-1234-1234-1234-123456789abc','container_started_at':'fixture',
                    'image_digest':'sha256:'+'a'*64,'program_sha256':next(iter(PROGRAMS)),'pvf_sha256':'b'*64,'policy_sha256':'d'*64}
        self.rows={'mysql':(True,True,True,False,3),'mysql-log':(True,True,True,True,4),
                   'game_siroco11':(True,True,True,True,9),'game_template':(False,False,False,False,-1)}
        for i,name in enumerate(DEPENDENCIES,20):
            if name not in self.rows:
                self.cfg['components'].append(name);self.rows[name]=(True,True,True,True,i)
        self.process={'pid':109,'nspid':9,'start_ticks':12345};self.calls=[];self.exit=(0,0)
    def identity(self):return copy.deepcopy(self.ident)
    def services(self):return copy.deepcopy(self.rows)
    def game_process(self,*args):return dict(self.process)
    def exit_result(self,*args):return self.exit
    def command(self,args,timeout=10):
        assert args[:3]==['docker','exec',self.ident['container_id']]
        self.calls.append(args)
        old=self.rows['game_siroco11']
        if args[3:5]==['s6-svc','-O']:self.rows['game_siroco11']=(True,False,True,True,9)
        elif args[3]=='touch':self.rows['game_siroco11']=(True,False,False,True,9)
        elif args[3:5]==['s6-svc','-2']:pass
        elif args[3]=='s6-svwait':self.rows['game_siroco11']=(False,False,False,True,-1)
        else:raise AssertionError(args)
        return ''


def test_prepare_is_readonly_and_drain_never_kills_restarts_or_claims_permit():
    host=FakeHost();adapter=GameDrain(host);plan=adapter.prepare();events=[]
    assert not host.calls
    result=adapter.execute(plan,lambda stage,data:events.append((stage,data)))
    assert result['state']=='game_drained' and result['maintenance_permit'] is False
    assert [e[0] for e in events]==['drain-started','inhibit-intent','inhibit-applied','marker-intent','marker-applied','signal-intent','signal-sent','game-drained','drain-finished']
    assert all('/run/service/mysql' not in a and 'systemctl' not in a for a in host.calls)
    assert all(not any(x in a for x in ('-D','-d','-k','-K','restart','stop')) for a in host.calls if a[3]=='s6-svc')
    assert host.calls[2][3:]==['s6-svc','-2','/run/service/game_siroco11']
    assert host.rows['mysql']==(True,True,True,False,3)


@pytest.mark.parametrize('field',['container_id','container_started_at','boot_id','image_digest','pvf_sha256','policy_sha256'])
def test_changed_binding_refuses_before_any_signal(field):
    h=FakeHost();d=GameDrain(h);plan=d.prepare();h.ident[field]='changed'
    with pytest.raises(Refused,match='preview_changed'):d.execute(plan,lambda *a:None)
    assert not h.calls


def test_unknown_program_does_not_guess_signal_protocol():
    h=FakeHost();h.ident['program_sha256']='e'*64
    with pytest.raises(Refused,match='protocol_unadapted'):GameDrain(h).prepare()
    assert not h.calls


@pytest.mark.parametrize('stage',['drain-started','inhibit-intent','inhibit-applied','marker-intent','marker-applied','signal-intent'])
def test_failed_durable_intent_prevents_its_signal(stage):
    h=FakeHost();d=GameDrain(h);plan=d.prepare()
    def record(actual,data):
        if actual==stage:raise OSError('synthetic persistence failure')
    with pytest.raises(OSError):d.execute(plan,record)
    assert not any('-2' in c for c in h.calls)


def test_timeout_does_not_force_kill_or_retry_and_retains_original_intent():
    h=FakeHost();original=h.command;events=[]
    def run(args,timeout=10):
        if args[3]=='s6-svwait':raise TimeoutError('still draining')
        return original(args,timeout)
    h.command=run;d=GameDrain(h)
    with pytest.raises(TimeoutError):d.execute(d.prepare(),lambda stage,data:events.append(stage))
    assert events[-1]=='signal-sent' and sum('-2' in a for a in h.calls)==1
    assert h.rows['game_siroco11']==(True,False,False,True,9)
    with pytest.raises(Refused,match='game_state_unstable'):d.prepare()


@pytest.mark.parametrize('exit_result',[(1,0),(0,9),(-1,9)])
def test_abnormal_game_exit_cannot_authorize_maintenance(exit_result):
    h=FakeHost();h.exit=exit_result;d=GameDrain(h);events=[]
    with pytest.raises(Refused,match='exit_abnormal'):d.execute(d.prepare(),lambda stage,data:events.append(stage))
    assert 'drain-finished' not in events


def test_pid_reuse_between_marking_down_and_signal_refuses():
    h=FakeHost();original=h.command
    def run(args,timeout=10):
        result=original(args,timeout)
        if args[3]=='touch':h.process['start_ticks']+=1
        return result
    h.command=run;d=GameDrain(h)
    with pytest.raises(Refused,match='target_changed'):d.execute(d.prepare(),lambda *a:None)
    assert not any('-2' in a for a in h.calls)


# Exercise the real /proc reader against the same isolated synthetic tree as
# the full maintenance verifier, not only the command-planning double above.
from test_inventory_probe import scene
from game_drain import Host


def test_host_reader_binds_live_namespace_pid_starttime_hash_and_usr2_handler(scene):
    cfg,probe,proc,*_=scene
    status=proc/'103/status';status.write_text(status.read_text()+'SigCgt:\t0000000000000800\n')
    identity={'pid':101,'program_sha256':cfg['process_rules'][2]['sha256']}
    assert Host(probe).game_process(identity,3)=={'pid':103,'nspid':3,'start_ticks':12345}


@pytest.mark.parametrize('case',['no_handler','wrong_hash','wrong_namespace_pid'])
def test_host_reader_rejects_unproven_signal_target(scene,case):
    cfg,probe,proc,*_=scene
    status=proc/'103/status';status.write_text(status.read_text()+'SigCgt:\t0000000000000800\n')
    identity={'pid':101,'program_sha256':cfg['process_rules'][2]['sha256']}
    nspid=3
    if case=='no_handler':status.write_text(status.read_text().replace('0000000000000800','0000000000000000'))
    elif case=='wrong_hash':identity['program_sha256']='0'*64
    else:nspid=99
    with pytest.raises(Refused):Host(probe).game_process(identity,nspid)


@pytest.mark.parametrize('output',['0 0','0 -1','1 0'])
def test_exit_probe_uses_fixed_s6_fields(output):
    class Probe:
        cfg={}
        def runner(self,args,timeout):
            assert args==['docker','exec','c'*64,'s6-svstat','-o','exitcode,signum','/run/service/game_siroco11']
            return output
    assert Host(Probe()).exit_result('c'*64,'game_siroco11')==tuple(map(int,output.split()))


@pytest.mark.parametrize('output',['0','0 0 extra','0 NA','false 0','0 999999'])
def test_exit_probe_malformed_results_stay_unknown(output):
    class Probe:
        cfg={}
        def runner(self,*args):return output
    with pytest.raises(Refused,match='exit_result_unknown'):Host(Probe()).exit_result('c'*64,'game_siroco11')


@pytest.mark.parametrize('dependency',DEPENDENCIES)
def test_storage_or_shutdown_dependency_down_prevents_any_drain(dependency):
    h=FakeHost();h.rows[dependency]=(False,False,True,False,-1)
    with pytest.raises(Refused,match='storage_unavailable'):GameDrain(h).prepare()
    assert not h.calls


def test_storage_restart_before_signal_prevents_signal():
    h=FakeHost();original=h.command
    def run(args,timeout=10):
        result=original(args,timeout)
        if args[3]=='touch':h.rows['mysql']=(True,True,True,False,999)
        return result
    h.command=run;d=GameDrain(h)
    with pytest.raises(Refused,match='dependencies_changed'):d.execute(d.prepare(),lambda *a:None)
    assert not any('-2' in a for a in h.calls)
