"""Fake clocks/processes only: no production systemctl or Docker calls."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'
sys.path.insert(0, str(DEPLOY))
import monitor_runtime as runtime
import monitor


def test_cached_core_failure_is_not_a_new_observation():
    p = runtime.Protection()
    assert p.observe(0, True, sampled=True, core_ok=False) is None
    for now in (5, 10):
        assert p.observe(now, True) is None
    assert p.bad == 1
    assert p.observe(15, True, sampled=True, core_ok=False) == 'core_failure'


def test_two_transient_timeouts_do_not_stop_gm():
    p = runtime.Protection()
    assert p.observe(0, True, sampled=True) is None
    assert p.observe(23, True, sampled=True) is None
    assert p.observe(46, True, sampled=True, core_ok=True) is None
    assert p.errors == 0


def test_collector_grace_requires_elapsed_time_and_distinct_samples():
    p = runtime.Protection()
    for now in (0, 15, 30, 45):
        assert p.observe(now, True, sampled=True) is None
    assert p.observe(60, True, sampled=True) == 'collector_failed'


def test_unknown_breaks_confirmed_core_failure_streak():
    p = runtime.Protection()
    p.observe(0, True, sampled=True, core_ok=False)
    p.observe(15, True, sampled=True)
    assert p.observe(30, True, sampled=True, core_ok=False) is None


def test_resources_protect_even_without_collector_samples():
    p = runtime.Protection()
    assert p.observe(0, False, sampled=True) is None
    assert p.observe(5, False) == 'resource_failure'
    assert p.observe(10, True) is None


def test_recovery_needs_three_fresh_healthy_samples_over_30_seconds():
    p = runtime.Protection()
    for now in (0, 15):
        p.observe(now, True, sampled=True, core_ok=True)
        assert not p.recovered(now)
    p.observe(30, True, sampled=True, core_ok=True)
    assert p.recovered(30)
    p.observe(35, False)
    assert not p.recovered(35)


@pytest.fixture
def controller(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'STATE', tmp_path / 'protection.json')
    monkeypatch.setattr(runtime, 'INHIBIT', tmp_path / 'no-auto-recover')
    calls = []
    state = ['active', 'old']
    def command(args, *, probe):
        calls.append(args)
        if args[1] == 'stop':
            state[:] = ['inactive', 'owned-token']
        if args[1] == 'start':
            state[:] = ['active', 'owned-token']
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runtime, 'command', command)
    monkeypatch.setattr(runtime, 'unit_state', lambda: tuple(state))
    return runtime.Controller(), calls, state


def test_auto_recovery_only_for_our_collector_stop(controller):
    c, calls, state = controller
    c.apply('collector_failed', False, 60)
    assert c.pending == 'owned-token'
    c.apply(None, False, 75)
    assert len(calls) == 1
    c.apply(None, True, 105)
    assert calls == [['systemctl', 'stop', 'dnf-gm.service'], ['systemctl', 'start', 'dnf-gm.service']]
    d = json.loads(runtime.STATE.read_text())
    assert d['reason'] == 'collector_failed' and d['recovery_result'] == 'started'
    assert not d['manual_restart_required']


@pytest.mark.parametrize('reason', ['resource_failure', 'core_failure'])
def test_real_failures_require_manual_recovery(controller, reason):
    c, calls, _ = controller
    c.apply(reason, False, 0)
    c.apply(None, True, 60)
    assert calls == [['systemctl', 'stop', 'dnf-gm.service']]
    assert json.loads(runtime.STATE.read_text())['manual_restart_required']


@pytest.mark.parametrize('case', ['manual_stop', 'inhibit', 'new_transition', 'monitor_restart'])
def test_never_start_manual_or_unowned_stop(controller, case):
    c, calls, state = controller
    if case == 'manual_stop':
        state[0] = 'inactive'
        c.apply(None, True, 60)
        assert not calls
        return
    c.apply('collector_failed', False, 0)
    if case == 'inhibit':
        runtime.INHIBIT.touch()
    elif case == 'new_transition':
        state[1] = 'another-transition'
    else:
        c = runtime.Controller()
    c.apply(None, True, 60)
    assert len(calls) == 1


def test_resource_failure_revokes_pending_auto_recovery(controller):
    c, calls, _ = controller
    c.apply('collector_failed', False, 0)
    c.apply('resource_failure', False, 5)
    c.apply(None, True, 60)
    assert len(calls) == 1 and c.pending is None
    assert json.loads(runtime.STATE.read_text())['manual_restart_required']


def test_three_restarts_per_hour_budget(controller):
    c, calls, state = controller
    for n in range(3):
        state[0] = 'active'
        c.apply('collector_failed', False, n * 100)
        c.apply(None, True, n * 100 + 40)
    state[0] = 'active'
    c.apply('collector_failed', False, 400)
    c.apply(None, True, 440)
    assert len([a for a in calls if a[1] == 'start']) == 3
    assert json.loads(runtime.STATE.read_text())['manual_restart_required']


def test_timeout_diagnostics_redacted(monkeypatch, capsys):
    def run(args, **kwargs):
        assert kwargs['timeout'] == 8
        raise subprocess.TimeoutExpired(args, 8, output='secret-output')
    monkeypatch.setattr(runtime.subprocess, 'run', run)
    with pytest.raises(subprocess.TimeoutExpired):
        runtime.command(['private-argument'], probe='dnf_components')
    text = capsys.readouterr().out
    assert 'private' not in text and 'secret' not in text
    assert json.loads(text)['probe'] == 'dnf_components'


@pytest.mark.parametrize('case', ['valid', 'missing', 'duplicate', 'extra', 'down', 'nonzero'])
def test_batched_components_are_exact(monkeypatch, tmp_path, case):
    cfg = json.loads((DEPLOY / 'monitor.example.json').read_text())
    pvf = tmp_path / 'Script.pvf'
    pvf.write_bytes(b'synthetic-fixture')
    cfg['pvf_path'] = str(pvf)
    names = cfg['components']
    lines = [name + '=up (pid 1) 10 seconds' for name in names]
    if case == 'missing': lines.pop()
    if case == 'extra': lines.append('other=up ')
    if case == 'duplicate': lines[-1] = lines[0]
    if case == 'down': lines[-1] = names[-1] + '=down '
    calls = []
    def command(args, *, probe):
        calls.append((args, probe))
        if probe == 'container_state':
            return SimpleNamespace(returncode=0, stdout='{"Running":true,"OOMKilled":false}|sha256:fixture')
        return SimpleNamespace(returncode=1 if case == 'nonzero' else 0, stdout='\n'.join(lines))
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(monitor, 'command', command)
    monkeypatch.setattr(monitor, 'build_opener', lambda *args: SimpleNamespace(open=lambda *a, **kw: Response()))
    status = monitor.Collector(cfg)()
    assert status['core_ok'] is (case == 'valid')
    assert len([a for a, probe in calls if probe == 'dnf_components']) == 1
    assert status['image_digest'] == 'sha256:fixture'


def test_failed_sample_invalidates_snapshot_immediately_and_backs_off(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'DEST', tmp_path / 'run/status.json')
    monkeypatch.setattr(runtime, 'STATE', tmp_path / 'state/protection.json')
    monkeypatch.setattr(runtime, 'cpu', lambda: (100, 50))
    monkeypatch.setattr(runtime, 'resources', lambda _: dict(mem_available_mib=700, swap_free_mib=4000, disk_free_gib=10))
    clock, calls, loops = [100], [], []
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(runtime.Controller, 'apply', lambda *a: None)
    def collect():
        calls.append(clock[0])
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(['secret'], 8)
        return dict(core_ok=True, image_digest='test', pvf_sha256='a'*64)
    class End(BaseException): pass
    def sleep(_):
        loops.append(json.loads(runtime.DEST.read_text()))
        clock[0] += 5
        if len(loops) == 4: raise End()
    monkeypatch.setattr(runtime.time, 'sleep', sleep)
    with pytest.raises(End):
        runtime.run(collect, disk_path=str(tmp_path))
    assert calls == [100, 115]
    assert all(not s['core_ok'] and 'pvf_sha256' not in s for s in loops[:3])
    assert loops[-1]['core_ok']


def test_optional_native_program_fingerprint_cache_and_changes(tmp_path,monkeypatch):
    import hashlib
    c=monitor.Collector({})
    path=tmp_path/'monitor';path.write_bytes(b'fixture-program')
    expected=hashlib.sha256(path.read_bytes()).hexdigest()
    assert c._native_file_fingerprint(path)==expected
    original=Path.open
    def no_open(p,*a,**kw):raise AssertionError('Unchanged program should use cached hash')
    with monkeypatch.context() as ctx:
        ctx.setattr(Path,'open',no_open)
        assert c._native_file_fingerprint(path)==expected
    path.write_bytes(b'new-fixture-program')
    assert c._native_file_fingerprint(path)!=expected
    path.unlink();assert c._native_file_fingerprint(path) is None
    assert c.native_sig is None and c.native_sha is None


def test_optional_native_fingerprint_rejects_symlink_directory_empty_and_large(tmp_path):
    c=monitor.Collector({})
    target=tmp_path/'target';target.write_bytes(b'fixture')
    link=tmp_path/'link';link.symlink_to(target)
    empty=tmp_path/'empty';empty.touch()
    large=tmp_path/'large'
    with large.open('wb') as stream:stream.truncate(15*1024*1024+1)
    for path in (tmp_path,link,empty,large):
        assert c._native_file_fingerprint(path) is None
    for pid in (None,True,0,1,'42','../file'):
        assert c.native_fingerprint(pid) is None


@pytest.mark.parametrize('window,expected', [
    (None,False), ({'active':True,'verified':False},False),
    ({'active':True,'verified':True,'collected_at':990,'expires_at':1100},True),
    ({'active':True,'verified':True,'collected_at':969,'expires_at':1100},False),
    ({'active':True,'verified':True,'collected_at':1001,'expires_at':1100},False),
    ({'active':True,'verified':True,'collected_at':990,'expires_at':1000},False),
    ({'active':True,'verified':1,'collected_at':990,'expires_at':1100},False),
    ({'active':True,'verified':True,'collected_at':float('nan'),'expires_at':1100},False),
])
def test_maintenance_protection_does_not_forge_normal_health(window,expected):
    s={'core_ok':False,'maintenance':window}
    assert runtime.protection_health(s,1000) is expected
    assert s['core_ok'] is False


def test_default_collector_does_not_load_maintenance(monkeypatch):
    assert monitor.Collector({}).maintenance is None
    cfg=json.loads((DEPLOY/'monitor.example.json').read_text())
    cfg['inventory_maintenance_enabled']='true'
    with pytest.raises(ValueError):monitor.validate(cfg)


@pytest.mark.parametrize('auxiliary_ok', [True,False])
@pytest.mark.parametrize('verified', [True,False])
def test_maintenance_collector_keeps_game_unhealthy_and_requires_auxiliary(monkeypatch,tmp_path,auxiliary_ok,verified):
    cfg=json.loads((DEPLOY/'monitor.example.json').read_text())
    pvf=tmp_path/'Script.pvf';pvf.write_bytes(b'synthetic');cfg['pvf_path']=str(pvf)
    def command(args,*,probe):
        if probe=='container_state':return SimpleNamespace(returncode=0,stdout='{"Running":true,"OOMKilled":false}|sha256:test')
        if probe=='dnf_components':return SimpleNamespace(returncode=0,stdout='\n'.join(n+'=down' for n in cfg['components']))
        return SimpleNamespace(returncode=0)
    class Window:
        def status(self):return {'active':True,'verified':verified,'collected_at':990,'expires_at':1100}
    monkeypatch.setattr(monitor,'command',command)
    monkeypatch.setattr(monitor,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:(_ for _ in ()).throw(OSError())))
    data=monitor.Collector(cfg,auxiliary=lambda:auxiliary_ok,maintenance=Window())()
    assert data['core_ok'] is False and not data['services']['dnf_gateway']
    assert data['maintenance']['verified'] is (verified and auxiliary_ok)
    assert runtime.protection_health(data,1000) is (verified and auxiliary_ok)


def test_runtime_does_not_autorecover_from_collector_failure_into_maintenance(monkeypatch,tmp_path):
    monkeypatch.setattr(runtime,'DEST',tmp_path/'run/status.json')
    monkeypatch.setattr(runtime,'STATE',tmp_path/'state/protection.json')
    monkeypatch.setattr(runtime,'cpu',lambda:(100,50))
    monkeypatch.setattr(runtime,'resources',lambda _:dict(mem_available_mib=700,swap_free_mib=4000,disk_free_gib=10))
    clock=[1000];calls=[]
    monkeypatch.setattr(runtime.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(runtime.time,'time',lambda:clock[0])
    monkeypatch.setattr(runtime.Controller,'apply',lambda self,reason,recovered,now,metrics:calls.append((reason,recovered)))
    def collect():return {'core_ok':False,'maintenance':{'active':True,'verified':True,'collected_at':clock[0],'expires_at':2000}}
    class End(BaseException):pass
    def sleep(_):
        clock[0]+=5
        if clock[0]>=1050:raise End()
    monkeypatch.setattr(runtime.time,'sleep',sleep)
    with pytest.raises(End):runtime.run(collect,disk_path=str(tmp_path))
    assert all(reason is None and recovered is False for reason,recovered in calls)
    assert json.loads(runtime.DEST.read_text())['core_ok'] is False
