"""Real local files/fake proc and service PID. Never contacts systemd or Docker."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
import maintenance_readiness as ready
from dnfgm.release_files import atomic_json, Refused
from test_inventory_probe import scene, stat_line


@pytest.fixture
def rig(scene, tmp_path, monkeypatch):
    policy, _, proc, _, clock, _ = scene
    root=tmp_path/'release';root.mkdir(mode=0o755)
    repo=Path(__file__).resolve().parents[1]
    for relative in ready.SOURCES.values():
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((repo/relative).read_bytes());path.chmod(0o644)
        parent=path.parent
        while parent!=root:parent.chmod(0o755);parent=parent.parent
    cfg={'container':policy['container'],'pvf_path':policy['pvf_path'],'disk_path':str(tmp_path),
         'gateway_url':'http://127.0.0.1:5505/health','core_services':list(policy['protected_services'].values()),
         'components':policy['components'],'min_memory_mib':256,'min_swap_free_mib':1536,
         'inventory_maintenance_enabled':True}
    config=tmp_path/'monitor.json';policy_path=tmp_path/'policy.json'
    atomic_json(config,cfg);atomic_json(policy_path,policy)
    installed=ready.InstalledMonitor(root=root,config=config,policy=policy_path,owner=os.geteuid())
    pid=[400];(proc/'400').mkdir();(proc/'400/stat').write_text(stat_line(400,1))
    (proc/'400/cmdline').write_bytes(b'/fixture/python\0'+str(root/'deploy/monitor.py').encode()+b'\0')
    monkeypatch.setattr(ready,'verify_loaded',lambda path:None)
    attester=ready.MonitorAttestation(installed,cfg,pid=400,proc=proc,monotonic=lambda:clock[0])
    sample={**{k:policy[k] for k in ('image_digest','pvf_sha256')},'collector_pid':400,'collected_at':clock[0],
        'core_ok':True,'services':{**{n:True for n in cfg['core_services']},'dnf_components':True,'dnf_gateway':True},
        'mem_available_mib':512,'swap_free_mib':2048,'disk_free_gib':10,'maintenance_monitor':attester()}
    status=tmp_path/'status.json';atomic_json(status,sample)
    verifier=ready.MonitorHandshake(installed,status=status,proc=proc,pid_provider=lambda:pid[0],clock=lambda:clock[0],monotonic=lambda:clock[0])
    return installed,attester,verifier,cfg,policy,sample,status,proc,pid,clock


def test_real_source_config_and_process_bind_to_current_sample(rig):
    installed,attester,v,cfg,policy,sample,status,proc,pid,clock=rig
    proof=v.check(policy)
    assert proof['collector_pid']==400 and proof['process_start_ticks']==12345
    assert proof['source_sha256']==sample['maintenance_monitor']['source_sha256']
    assert proof['maintenance_permit'] is False
    assert status.read_text()==json.dumps(sample,sort_keys=True,separators=(',',':'),ensure_ascii=False)


@pytest.mark.parametrize('mutation',['pid','process_reuse','boot','zombie','command','missing_pid'])
def test_dead_replaced_or_different_monitor_refused(rig,mutation):
    _,_,v,_,policy,sample,status,proc,pid,_=rig
    if mutation=='pid':pid[0]=401
    if mutation=='missing_pid':pid[0]=0
    if mutation=='process_reuse':(proc/'400/stat').write_text(stat_line(400,1).replace('12345','54321'))
    if mutation=='boot':(proc/'sys/kernel/random/boot_id').write_text('f'*8+'-1234-1234-1234-'+'f'*12)
    if mutation=='zombie':(proc/'400/stat').write_text(stat_line(400,1).replace(' S ',' Z '))
    if mutation=='command':(proc/'400/cmdline').write_bytes(b'/fixture/python\0/tmp/old-monitor.py\0')
    with pytest.raises((Refused,OSError)):v.check(policy)


@pytest.mark.parametrize('mutation',['wall_old','wall_future','mono_old','mono_future','nan','missing','bool','source','identity','resources','gateway','core','disabled'])
def test_snapshot_cannot_fake_fresh_healthy_installed_readiness(rig,mutation):
    installed,_,v,cfg,policy,sample,status,_,_,clock=rig
    if mutation=='wall_old':sample['collected_at']-=41
    if mutation=='wall_future':sample['collected_at']+=1
    if mutation=='mono_old':sample['maintenance_monitor']['collected_monotonic']-=41
    if mutation=='mono_future':sample['maintenance_monitor']['collected_monotonic']+=1
    if mutation=='nan':sample['maintenance_monitor']['collected_monotonic']='NaN'
    if mutation=='missing':sample.pop('maintenance_monitor')
    if mutation=='bool':sample['maintenance_monitor']['version']=True
    if mutation=='source':sample['maintenance_monitor']['source_sha256']='f'*64
    if mutation=='identity':sample['image_digest']='sha256:'+'e'*64
    if mutation=='resources':sample['mem_available_mib']=255
    if mutation=='gateway':sample['services']['dnf_gateway']=False
    if mutation=='core':sample['services'][cfg['core_services'][0]]=False
    if mutation=='disabled':cfg['inventory_maintenance_enabled']=False;atomic_json(installed.config,cfg)
    atomic_json(status,sample)
    with pytest.raises(Refused):v.check(policy)


@pytest.mark.parametrize('mutation',['source','policy','config','file_mode','directory_mode','symlink','hardlink','release_switch'])
def test_collector_latches_loaded_source_and_configuration(rig,tmp_path,mutation):
    installed,attester,v,cfg,policy,*_=rig
    file=installed.root/'deploy/monitor_runtime.py'
    if mutation=='source':file.write_text(file.read_text()+'\n# changed\n')
    if mutation=='policy':policy['image_digest']='sha256:'+'f'*64;atomic_json(installed.policy,policy)
    if mutation=='config':cfg['min_memory_mib']=300;atomic_json(installed.config,cfg)
    if mutation=='file_mode':file.chmod(0o666)
    if mutation=='directory_mode':file.parent.chmod(0o777)
    if mutation=='symlink':file.rename(tmp_path/'m.py');file.symlink_to(tmp_path/'m.py')
    if mutation=='hardlink':os.link(file,tmp_path/'linked.py')
    if mutation=='release_switch':
        moved=tmp_path/'other';installed.root.rename(moved);installed.root.symlink_to(moved)
    with pytest.raises((Refused,OSError)):attester()


def test_handshake_rechecks_identity_after_read(rig):
    _,_,v,_,policy,_,_,_,_,_=rig
    calls=[]
    def pid():calls.append(1);return 400 if len(calls)==1 else 401
    v.pid_provider=pid
    with pytest.raises(Refused,match='changed_during'):v.check(policy)


def test_transition_health_does_not_authorize_new_maintenance(rig):
    _,_,v,_,policy,sample,status,_,_,clock=rig
    sample.update(core_ok=False,maintenance={'active':True,'verified':True,'collected_at':clock[0],'expires_at':clock[0]+60})
    sample['services'].update(dnf_components=False,dnf_gateway=False)
    atomic_json(status,sample)
    with pytest.raises(Refused):v.check(policy)
    assert v.check(policy,healthy=False)['healthy'] is False
    sample['maintenance']['verified']=False;atomic_json(status,sample)
    with pytest.raises(Refused):v.check(policy,healthy=False)


def test_collector_requires_same_loaded_configuration(rig):
    installed,_,_,cfg,_,_,_,proc,_,clock=rig
    with pytest.raises(Refused,match='loaded_config'):
        ready.MonitorAttestation(installed,{**cfg,'min_memory_mib':512},pid=400,proc=proc,monotonic=lambda:clock[0])


def test_real_isolated_imports_validate_loaded_files_without_site_packages(rig):
    installed,_,_,cfg,_,_,_,proc,_,clock=rig
    code=f'''
import sys,os,json
from pathlib import Path
sys.path[:0]=[{str(installed.root/'deploy')!r},{str(installed.root/'src')!r}]
from maintenance_readiness import InstalledMonitor,MonitorAttestation,verify_loaded
root=Path({str(installed.root)!r})
installed=InstalledMonitor(root=root,config=Path({str(installed.config)!r}),policy=Path({str(installed.policy)!r}),owner=os.geteuid())
attestation=MonitorAttestation(installed,json.loads(installed.config.read_text()),pid=400,proc=Path({str(proc)!r}))
assert attestation()['collector_pid']==400
import monitor_runtime
monitor_runtime.__file__='/tmp/wrong-release.py'
try:verify_loaded(root)
except ValueError:pass
else:raise AssertionError('wrong module accepted')
assert 'fastapi' not in sys.modules and 'pymysql' not in sys.modules
'''
    child=subprocess.run([sys.executable,'-I','-S','-c',code],capture_output=True,text=True,timeout=10)
    assert child.returncode==0,child.stderr


def test_restore_identity_check_does_not_authorize_expired_permit_or_new_entry(rig):
    _,_,v,cfg,policy,sample,status,_,_,clock=rig
    sample.update(core_ok=False,maintenance={'active':True,'verified':False,'collected_at':clock[0],'expires_at':clock[0]-1})
    sample['services'].update(dnf_components=False,dnf_gateway=False)
    atomic_json(status,sample)
    proof=v.check(policy,healthy=None)
    assert proof['healthy'] is None and proof['maintenance_permit'] is False
    for mode in (True,False):
        with pytest.raises(Refused):v.check(policy,healthy=mode)
    sample['services'][cfg['core_services'][0]]=False;atomic_json(status,sample)
    with pytest.raises(Refused):v.check(policy,healthy=None)


@pytest.mark.parametrize('mutation',['resources','stale','source'])
def test_restore_identity_check_never_skips_resources_freshness_or_source(rig,mutation):
    installed,_,v,_,policy,sample,status,_,_,clock=rig
    if mutation=='resources':sample['mem_available_mib']=255
    if mutation=='stale':sample['collected_at']=clock[0]-41
    if mutation=='source':sample['maintenance_monitor']['source_sha256']='0'*64
    atomic_json(status,sample)
    with pytest.raises(Refused):v.check(policy,healthy=None)
