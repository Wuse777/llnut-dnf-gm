"""Local synthetic /proc, Docker output and files. Never contacts production."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
from inventory_probe import (LinuxProbe, Refused, S6_SCRIPT, cgroups, in_container,
                             parse_components, run_command, stat_identity, validate)
from inventory_window import WindowManager
from dnfgm.inventory_fence import BOUND_FIELDS, MaintenanceFence
from dnfgm.release_files import atomic_json

BOOT='12345678-1234-1234-1234-123456789abc'


def stat_line(pid,ppid):
    fields=['S',str(ppid)]+['0']*17+['12345']+['0']*30
    return f'{pid} (safe name) tricky)) '+ ' '.join(fields)


@pytest.fixture
def scene(tmp_path):
    proc=tmp_path/'proc';proc.mkdir()
    (proc/'sys/kernel/random').mkdir(parents=True)
    (proc/'sys/kernel/random/boot_id').write_text(BOOT)
    (proc/'meminfo').write_text('MemAvailable: 524288 kB\nSwapFree: 2097152 kB\n')
    ns=tmp_path/'pid-ns';ns.write_text('namespace')
    cfg={'container':'dnf','components':['mysql','channel','game_siroco11'],
         'protected_services':{'docker':'docker.service','dnf':'dnf.service','mihomo':'mihomo.service','cliproxyapi':'cliproxyapi.service'},
         'image_digest':'sha256:'+'a'*64,'process_rules':[]}
    for key in ('pvf','program'):
        path=tmp_path/key;path.write_bytes(('synthetic-'+key).encode())
        cfg[key+'_path']=str(path);cfg[key+'_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    for host,parent,name,role,nspid in [(101,1,'init','init',1),(102,101,'supervisor','supervisor',2),(103,102,'mysqld','mysql',3)]:
        exe=tmp_path/name;exe.write_bytes(('synthetic executable '+name).encode())
        rule={'id':name,'exe':str(exe),'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
              'argv':[name],'uid':0,'role':role,'parents':[] if role=='init' else ['init' if role=='supervisor' else 'supervisor']}
        cfg['process_rules'].append(rule)
        entry=proc/str(host);entry.mkdir();(entry/'ns').mkdir();os.link(ns,entry/'ns/pid')
        (entry/'exe').symlink_to(exe);(entry/'cmdline').write_bytes(name.encode()+b'\0')
        (entry/'stat').write_text(stat_line(host,parent))
        (entry/'cgroup').write_text('0::/docker/synthetic\n')
        (entry/'status').write_text(f'Uid:\t0\t0\t0\t0\nNSpid:\t{host}\t{nspid}\n')
    states='mysql=true true true false 3\nchannel=false false false true -1\ngame_siroco11=false false false true -1\n'
    inspect={'Running':True,'OOMKilled':False,'Paused':False,'Restarting':False,'Pid':101,'StartedAt':'2026-11-05T00:00:00Z'}
    calls=[]
    def runner(args,timeout):
        assert 0<timeout<=5;calls.append(args)
        if args[:2]==['docker','inspect']:
            return 'b'*64+'|'+cfg['image_digest']+'|'+json.dumps(inspect)
        if args[:2]==['docker','exec']:
            assert args==['docker','exec','dnf','sh','-c',S6_SCRIPT]
            return states
        assert args[:3]==['systemctl','is-active','--quiet']
        assert args[3] in cfg['protected_services'].values()
        return ''
    clock=[1100.0]
    probe=LinuxProbe(cfg,runner=runner,proc=proc,clock=lambda:clock[0],monotonic=lambda:clock[0])
    return cfg,probe,proc,calls,clock,inspect


def test_full_readonly_probe(scene):
    cfg,probe,_,calls,_,_=scene
    data=probe()
    assert data['safe'] and data['no_unmanaged_processes'] and data['all_writers_down']
    assert data['mem_available_mib']==512 and data['swap_free_mib']==2048
    assert data['boot_id']==BOOT and len(data['process_set_sha256'])==64
    assert data['pvf_sha256']==cfg['pvf_sha256']
    assert len(calls)==8 # two inspections, two s6 samples, four systemctl reads
    assert all('stop' not in c and 'start' not in c and 'restart' not in c for c in calls)
    assert probe()['process_set_sha256']==data['process_set_sha256']


@pytest.mark.parametrize('row', ['true false false true 9','false true false true -1',
    'false false true true -1','false false false false -1','false false false true 9'])
def test_down_means_no_restart_and_finish_complete(row):
    with pytest.raises(Refused,match='writers_not_quiescent'):
        parse_components('mysql=true true true false 3\nchannel='+row,['mysql','channel'])


@pytest.mark.parametrize('text', ['mysql=true true true false 3',
    'mysql=true true true false 3\nchannel=false false false true -1\nextra=false false false true -1',
    'mysql=true true true false 3\nchannel=false false false true -1\nchannel=false false false true -1',
    'mysql=1 true true false 3\nchannel=false false false true -1',
    'mysql=true true true false abc\nchannel=false false false true -1'])
def test_component_discovery_cannot_omit_writers(text):
    with pytest.raises(Refused):parse_components(text,['mysql','channel'])


@pytest.mark.parametrize('path,value', [('container','--help'),('components',['mysql',{}]),('protected_services',{}),
    ('image_digest','latest'),('program_path','relative'),('pvf_sha256','x'),('process_rules',[])])
def test_config_rejects_unreviewed_or_unknown_policy(scene,path,value):
    cfg,*_=scene;bad=copy.deepcopy(cfg);bad[path]=value
    with pytest.raises(Refused):validate(bad)


@pytest.mark.parametrize('key,value', [('role','game'),('id',{}),('argv','bash'),('argv',['x\0y']),
    ('parents',['unknown']),('uid',True),('sha256',''),('exe','relative')])
def test_process_rule_validation(scene,key,value):
    cfg,*_=scene;bad=copy.deepcopy(cfg);bad['process_rules'][1][key]=value
    with pytest.raises(Refused):validate(bad)


@pytest.mark.parametrize('key,value', [('Running',False),('OOMKilled',True),('Paused',True),('Restarting',True),('Pid',1),('Pid',True),('StartedAt','')])
def test_container_must_be_unchanged_and_alive(scene,key,value):
    _,probe,_,_,_,state=scene;state[key]=value
    with pytest.raises(Refused):probe()


@pytest.mark.parametrize('case', ['extra_process','argv','exe_bytes','uid','parent','zombie','nested_ns','missing_mysql','namespace_root','unknown_cgroup_child'])
def test_unmanaged_or_unstable_process_refuses_window(scene,case):
    cfg,probe,proc,*_=scene;entry=proc/'103'
    if case in ('extra_process','unknown_cgroup_child'):
        import shutil
        extra=proc/'104';shutil.copytree(entry,extra,symlinks=True)
        (extra/'ns/pid').unlink();os.link(entry/'ns/pid',extra/'ns/pid')
        (extra/'cmdline').write_bytes(b'game_writer\0')
        if case=='unknown_cgroup_child':(extra/'cgroup').write_text('0::/docker/synthetic/hidden\n')
    elif case=='argv':(entry/'cmdline').write_bytes(b'mysqld\0--new-option\0')
    elif case=='exe_bytes':Path(cfg['process_rules'][2]['exe']).write_bytes(b'replaced')
    elif case=='uid':(entry/'status').write_text('Uid:\t0\t1\t0\t0\nNSpid:\t103\t3\n')
    elif case=='parent':(entry/'stat').write_text(stat_line(103,101))
    elif case=='zombie':(entry/'stat').write_text(stat_line(103,102).replace(' S ',' Z '))
    elif case=='nested_ns':(entry/'ns/pid').unlink();(entry/'ns/pid').write_text('another')
    elif case=='missing_mysql':
        import shutil;shutil.rmtree(entry)
    else:(proc/'101/cgroup').write_text('0::/\n')
    with pytest.raises((Refused,OSError)):probe()


def test_mutating_pvf_invalidates_cached_hash(scene):
    cfg,probe,*_=scene;probe()
    Path(cfg['pvf_path']).write_bytes(b'changed')
    with pytest.raises(Refused,match='version_changed'):probe()


def test_changed_mysql_pid_between_samples(scene):
    _,probe,*_=scene;original=probe.components;n=[0]
    def components():
        value=original();n[0]+=1
        if n[0]>1:value['mysql']=(True,True,True,False,9)
        return value
    probe.components=components
    with pytest.raises(Refused,match='probe_changed'):probe()


def test_low_resources_and_failed_core(scene):
    _,probe,proc,*_=scene
    (proc/'meminfo').write_text('MemAvailable: 1000 kB\nSwapFree: 3000000 kB\n')
    with pytest.raises(Refused,match='resources_low'):probe()
    (proc/'meminfo').write_text('MemAvailable: 524288 kB\nSwapFree: 2097152 kB\n')
    original=probe.runner
    def fail(args,timeout):
        if args[0]=='systemctl':raise Refused('maintenance_probe_command_failed')
        return original(args,timeout)
    probe.runner=fail
    with pytest.raises(Refused,match='command_failed'):probe()


def test_parser_handles_parentheses_in_process_name():
    assert stat_identity(stat_line(103,102))==(102,12345)
    with pytest.raises(Refused):stat_identity('bad')
    assert in_container(cgroups('0::/docker/test/child'),cgroups('0::/docker/test'))
    assert not in_container(cgroups('0::/docker/test2'),cgroups('0::/docker/test'))


def test_fixed_probe_runner_enforces_output_and_deadline():
    assert run_command([sys.executable,'-c','print("ok")'],2)=='ok\n'
    for code,timeout in [('print("x"*70000)',2),('import time;time.sleep(5)',0.05),('raise SystemExit(2)',2)]:
        with pytest.raises(Refused):run_command([sys.executable,'-c',code],timeout)


@pytest.fixture
def manager(scene,tmp_path):
    cfg,probe,_,_,clock,_=scene
    root=tmp_path/'maint';root.parent.chmod(0o700)
    def sleep(seconds):clock[0]+=seconds
    manager=WindowManager(root,probe,owner=os.geteuid(),clock=lambda:clock[0],sleep=sleep,monotonic=lambda:clock[0])
    manager.initialize()
    fence=MaintenanceFence(root,**{k:cfg[k] for k in ('image_digest','pvf_sha256','program_sha256')},
                             owner=os.geteuid(),clock=lambda:clock[0],boot=lambda:BOOT,monotonic=lambda:clock[0])
    return manager,fence,clock


def issue(m):return m.issue(reason='合成测试',acknowledge_writers_stopped=True)


def test_operator_lifecycle_serializes_close_and_never_changes_services(manager):
    m,fence,clock=manager
    inode=(m.root/'fence.lock').stat().st_ino
    result=issue(m)
    assert result['state']=='issued' and fence.check()['id']==result['id']
    with fence.hold() as lease:
        with pytest.raises(Refused,match='busy'):m.close(result['id'])
        with pytest.raises(Refused,match='busy'):m.refresh()
        assert lease.check()['id']==result['id']
    clock[0]+=15;m.refresh();assert fence.check()['id']==result['id']
    assert m.close(result['id'])=={'state':'closed','id':result['id'],'services_changed':False}
    with pytest.raises(FileNotFoundError):fence.check()
    assert m.close(result['id'])['state']=='already_closed'
    m.initialize();assert (m.root/'fence.lock').stat().st_ino==inode


def test_issue_requires_ack_and_no_existing_permit_even_expired(manager):
    m,_,clock=manager
    with pytest.raises(Refused,match='ack_required'):m.issue(reason='test')
    result=issue(m)
    clock[0]=result['expires_at']+1
    with pytest.raises(Refused,match='already_open'):issue(m)
    assert m.close(result['id'])['state']=='closed'


def test_refresh_failure_invalidates_evidence_without_restarting_anything(manager):
    m,fence,_=manager;result=issue(m)
    def fail():raise RuntimeError('secret command must never be written')
    m.probe=fail
    with pytest.raises(RuntimeError):m.refresh()
    assert 'secret' not in (m.root/'evidence.json').read_text()
    with pytest.raises(Refused,match='not_proven'):fence.check()
    assert m.close(result['id'])['state']=='closed'


def test_replacing_policy_or_container_refuses_refresh(manager):
    m,fence,_=manager;issue(m);original=m.probe
    m.probe=lambda:{**original(),'policy_sha256':'1'*64}
    with pytest.raises(Refused,match='version_changed'):m.refresh()
    with pytest.raises(Refused):fence.check()


def test_failed_second_probe_never_publishes_permit(manager):
    m,_,_=manager;original=m.probe;n=[0]
    def probe():
        e=original();n[0]+=1
        if n[0]==2:e['process_set_sha256']='0'*64
        return e
    m.probe=probe
    with pytest.raises(Refused,match='probe_changed'):issue(m)
    assert not (m.root/'permit.json').exists()


def test_expiry_and_wrong_id_cannot_authorize_or_close_other_window(manager):
    m,fence,clock=manager;result=issue(m)
    with pytest.raises(Refused,match='window_changed'):m.close('1'*32)
    clock[0]+=31
    with pytest.raises(Refused,match='stale'):fence.check()
    m.refresh();assert fence.check()
    clock[0]=result['expires_at']
    with pytest.raises(Refused):m.refresh()
    with pytest.raises(Refused):fence.check()
    assert m.close(result['id'])['state']=='closed'


def test_issue_response_loss_reconciles_without_replacing_permit(manager):
    m,fence,_=manager;result=issue(m)
    # A lost CLI response must be reconciled using status; re-issue won't
    # replace the original token even if the operator repeats the command.
    with pytest.raises(Refused,match='already_open'):issue(m)
    assert fence.check()['id']==result['id']


def test_crash_between_evidence_and_permit_cannot_authorize(manager,monkeypatch):
    import inventory_window
    m,fence,_=manager;original=inventory_window.atomic_json
    def crash(path,data,*args,**kwargs):
        if path.name=='permit.json':raise OSError('synthetic power loss')
        return original(path,data,*args,**kwargs)
    monkeypatch.setattr(inventory_window,'atomic_json',crash)
    with pytest.raises(OSError):issue(m)
    with pytest.raises(FileNotFoundError):fence.check()
    assert not (m.root/'permit.json').exists()


def test_monitor_adapter_cannot_waive_core_or_target_mismatch(scene,tmp_path,monkeypatch):
    import inventory_window
    cfg,probe,*_=scene;config=tmp_path/'inventory.json'
    atomic_json(config,cfg)
    monkeypatch.setattr(inventory_window,'CONFIG',config)
    # Test only the cross-configuration contract, not the independently tested
    # root file/ancestor guard.
    monkeypatch.setattr(inventory_window,'directory',lambda *a:None)
    monkeypatch.setattr(inventory_window,'read_json',lambda *a,**k:copy.deepcopy(cfg))
    monitor_cfg={'container':'dnf','pvf_path':cfg['pvf_path'],'components':cfg['components'],
                 'core_services':['docker','dnf','mihomo.service','cliproxyapi.service']}
    window=inventory_window.MonitorWindow(monitor_cfg)
    assert window.manager.probe.cfg==cfg
    for field,value in [('container','other'),('pvf_path','/other'),('components',['mysql','channel']),('core_services',['extra-core.service'])]:
        bad={**monitor_cfg,field:value}
        with pytest.raises(Refused,match='config_mismatch'):inventory_window.MonitorWindow(bad)


def test_monitor_adapter_refreshes_explicit_window_only(manager):
    import inventory_window
    m,fence,_=manager;adapter=object.__new__(inventory_window.MonitorWindow)
    adapter.manager=m;adapter.fence=fence
    assert adapter.status()=={'active':False,'verified':False}
    result=issue(m)
    assert adapter.status()['verified'] is True
    m.probe=lambda:(_ for _ in ()).throw(OSError('secret'))
    status=adapter.status()
    assert status=={'active':True,'verified':False,'reason':'maintenance_probe_failed'}
    m.close(result['id']);assert not adapter.status()['active']


def test_proven_maintenance_does_not_bypass_normal_write_guard(monkeypatch):
    from fastapi import HTTPException
    from dnfgm.config import Settings
    from dnfgm.service import Service
    import dnfgm.service as service_module
    settings=Settings(writes=('currency',),image_digest='image',test_uids=())
    service=Service(None,settings)
    monkeypatch.setattr(service_module,'snapshot',lambda _:dict(fresh=True,core_ok=False,image_digest='image',
        maintenance={'active':True,'verified':True},mem_available_mib=1000,swap_free_mib=2000))
    class NoSQL:
        def execute(self,*a):raise AssertionError('Must refuse before any database write')
    with pytest.raises(HTTPException) as failure:service.check_write(NoSQL(),{'action':'currency','uid':1},{})
    assert failure.value.status_code==503


def test_mysql_service_pid_cannot_point_at_init(scene):
    _,probe,*_=scene;original=probe.components
    def components():
        value=original();value['mysql']=(True,True,True,False,1);return value
    probe.components=components
    with pytest.raises(Refused,match='mysql_unproven'):probe()
