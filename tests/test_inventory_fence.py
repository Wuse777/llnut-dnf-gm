import copy
import fcntl
import json
import os
from pathlib import Path

import pytest

from dnfgm.inventory_fence import (BOUND_FIELDS, MaintenanceFence, Refused, open_lock,
                                  read_permit, validate_permit)

BOOT = '12345678-1234-1234-1234-123456789abc'


def permit():
    return dict(version=1, id='a'*32, created_at=1000, expires_at=1200, created_monotonic=1000, expires_monotonic=1200, reason='测试维护窗口',
                container_id='b'*64, container_started_at='2026-11-05T00:00:00Z',
                image_digest='sha256:'+'c'*64, pvf_sha256='d'*64, program_sha256='e'*64,
                components=['mysql', 'channel', 'game_siroco11'], boot_id=BOOT, policy_sha256='f'*64)


def evidence(p=None):
    p = p or permit()
    return {**{key:p[key] for key in BOUND_FIELDS}, 'permit_id':p['id'], 'collected_at':1090, 'collected_monotonic':1090,
            'safe':True, 'all_writers_down':True, 'mysql_up':True, 'non_game_core_ok':True,
            'no_unmanaged_processes':True, 'mem_available_mib':256, 'swap_free_mib':1536}


@pytest.fixture
def rig(tmp_path):
    root = tmp_path / 'maintenance'; root.mkdir(mode=0o755)
    (root / 'fence.lock').touch(mode=0o644)
    write(root, 'permit.json', permit()); write(root, 'evidence.json', evidence())
    clock = [1100]
    fence = MaintenanceFence(root, image_digest=permit()['image_digest'], pvf_sha256=permit()['pvf_sha256'],
                             program_sha256=permit()['program_sha256'], owner=os.geteuid(), clock=lambda:clock[0], boot=lambda:BOOT, monotonic=lambda:clock[0])
    return root, fence, clock


def write(root, name, value):
    # Replacement matches production's atomic rename (all readers see complete JSON).
    temp = root / (name+'.tmp')
    temp.write_text(json.dumps(value)); temp.chmod(0o644); temp.replace(root / name)


def test_valid_hold_and_commit_time_recheck(rig):
    root, fence, clock = rig
    with fence.hold() as lease:
        assert lease.state['id'] == permit()['id']
        assert lease.check() == fence.check()
    with pytest.raises(Refused, match='lease_released'):
        lease.check()


@pytest.mark.parametrize('key,value', [('version',True), ('version',2), ('id',None), ('id','a'*31),
    ('created_at',True), ('expires_at',5000), ('reason',' '), ('reason','x'*201),
    ('container_id','b'*63), ('image_digest','c'*64), ('pvf_sha256',3),
    ('boot_id','invalid'), ('components',[{},'mysql']), ('components',['mysql','mysql']),
    ('components',['mysql']), ('components',['mysql','../game']), ('components',['game','channel'])])
def test_malformed_permit_is_structured_refusal(rig,key,value):
    root, fence, _ = rig
    p = permit(); p[key] = value; write(root,'permit.json',p)
    with pytest.raises(Refused):
        fence.check()


@pytest.mark.parametrize('now', [999, 1200, 1201, float('nan'), float('inf'), True])
def test_expiry_or_clock_failure(rig, now):
    _, fence, clock = rig; clock[0] = now
    with pytest.raises(Refused):
        fence.check()


@pytest.mark.parametrize('field', ['safe','all_writers_down','mysql_up','non_game_core_ok','no_unmanaged_processes'])
@pytest.mark.parametrize('value', [False, None, 1, 'true'])
def test_all_evidence_flags_require_actual_true(rig, field, value):
    root, fence, _ = rig; e=evidence(); e[field]=value; write(root,'evidence.json',e)
    with pytest.raises(Refused):
        fence.check()


@pytest.mark.parametrize('value', [999, 1069, 1101, True, None, '1090', float('nan'), float('inf')])
def test_old_future_pre_permit_or_nonfinite_evidence(rig,value):
    root, fence, _ = rig; e=evidence(); e['collected_at']=value; write(root,'evidence.json',e)
    with pytest.raises(Refused):
        fence.check()


@pytest.mark.parametrize('field', ['mem_available_mib','swap_free_mib'])
@pytest.mark.parametrize('value', [None,'3000',True,-1,[],{},float('nan'),float('inf'),255])
def test_resource_protection_types_and_floor(rig,field,value):
    root, fence, _ = rig; e=evidence(); e[field]=value; write(root,'evidence.json',e)
    with pytest.raises(Refused):
        fence.check()


@pytest.mark.parametrize('field', list(BOUND_FIELDS)+['permit_id'])
def test_evidence_must_bind_current_window(rig,field):
    root, fence, _ = rig; e=evidence(); e[field]=None; write(root,'evidence.json',e)
    with pytest.raises(Refused):
        fence.check()


def test_old_evidence_cannot_cross_boot(rig):
    _, fence, _ = rig; fence.boot=lambda:'00000000-0000-0000-0000-000000000000'
    with pytest.raises(Refused, match='version_changed'):
        fence.check()


def test_changed_expected_version(rig):
    _, fence, _ = rig; fence.expected['program_sha256']='f'*64
    with pytest.raises(Refused, match='version_changed'):
        fence.check()


@pytest.mark.parametrize('name', ['permit.json','evidence.json','fence.lock'])
@pytest.mark.parametrize('unsafe', ['symlink','hardlink','writable','fifo'])
def test_untrusted_files(rig,name,unsafe):
    root, fence, _ = rig; path=root/name
    if unsafe=='symlink':
        backup=root/'backup'; path.rename(backup); path.symlink_to(backup)
    elif unsafe=='hardlink':os.link(path,root/'alias')
    elif unsafe=='writable':path.chmod(0o666)
    else:path.unlink();os.mkfifo(path)
    with pytest.raises((Refused,OSError)):
        with fence.hold():pass


@pytest.mark.parametrize('body', ['{"version":1,"version":1}', 'null','[]','{', 'x'*17000])
def test_invalid_json_never_authorizes(rig,body):
    root,fence,_=rig;(root/'evidence.json').write_text(body)
    with pytest.raises(Refused):fence.check()


def test_directory_symlink_or_writable_rejected(rig):
    root,fence,_=rig;root.chmod(0o777)
    with pytest.raises(Refused):fence.check()
    root.chmod(0o755); moved=root.with_name('moved');root.rename(moved);root.symlink_to(moved)
    with pytest.raises(Refused):fence.check()


def test_root_production_rejects_untrusted_ancestor(tmp_path):
    from dnfgm.inventory_fence import directory
    unsafe=tmp_path/'unsafe';unsafe.mkdir();unsafe.chmod(0o777)
    child=unsafe/'child';child.mkdir(mode=0o755)
    with pytest.raises(Refused):directory(child, owner=0)


def test_close_lock_serializes_against_transactions_and_closing_refuses_new_ones(rig):
    root,fence,_=rig
    other=open_lock(root,owner=os.geteuid())
    try:
        with fence.hold() as lease:
            with pytest.raises(BlockingIOError):fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
            assert lease.check()['id']==permit()['id']
        fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(Refused,match='closing'):
            with fence.hold():pass
    finally:os.close(other)


def test_commit_recheck_detects_expiry_revocation_and_window_swap(rig):
    root,fence,clock=rig
    with fence.hold() as lease:
        clock[0]=1201
        with pytest.raises(Refused):lease.check()
        clock[0]=1100
        p=permit();p['id']='f'*32;write(root,'permit.json',p)
        with pytest.raises(Refused,match='window_changed'):lease.check()
        (root/'permit.json').unlink()
        with pytest.raises(OSError):lease.check()


def test_replacing_lock_does_not_leave_a_false_held_lease(rig):
    root,fence,_=rig
    with fence.hold() as lease:
        (root/'fence.lock').rename(root/'old-lock');(root/'fence.lock').touch(mode=0o644)
        with pytest.raises(Refused,match='lock_changed'):lease.check()


def test_replacing_directory_does_not_leave_a_false_held_lease(rig):
    root,fence,_=rig
    with fence.hold() as lease:
        moved=root.with_name('old-root');root.rename(moved);root.mkdir(mode=0o755)
        os.link(moved/'fence.lock',root/'fence.lock')
        with pytest.raises(Refused):lease.check()


def test_wall_clock_rollback_cannot_extend_window_or_revive_old_evidence(rig):
    root,fence,_=rig
    fence.monotonic=lambda:1201
    with pytest.raises(Refused,match='expired'):fence.check()
    fence.monotonic=lambda:1121
    with pytest.raises(Refused,match='stale'):fence.check()
    fence.monotonic=lambda:1089
    with pytest.raises(Refused,match='stale'):fence.check()


@pytest.mark.parametrize('field', ['created_monotonic','expires_monotonic'])
@pytest.mark.parametrize('value', [None,True,'1100',float('nan'),float('inf')])
def test_monotonic_validity_cannot_be_bypassed(rig,field,value):
    root,fence,_=rig;p=permit();p[field]=value;write(root,'permit.json',p)
    with pytest.raises(Refused):fence.check()


def test_another_process_cannot_close_a_held_application_transaction(rig):
    import subprocess
    import sys
    root,fence,_=rig
    code='''import fcntl,os,sys
fd=os.open(sys.argv[1],os.O_RDONLY)
try:
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    print('closed-lock-acquired')
except BlockingIOError:
    print('busy')
finally:os.close(fd)
'''
    with fence.hold():
        result=subprocess.run([sys.executable,'-c',code,str(root/'fence.lock')],capture_output=True,text=True,timeout=3,check=True)
        assert result.stdout.strip()=='busy'
    result=subprocess.run([sys.executable,'-c',code,str(root/'fence.lock')],capture_output=True,text=True,timeout=3,check=True)
    assert result.stdout.strip()=='closed-lock-acquired'


def test_multiple_transactions_may_share_fence_but_each_checks_freshness(rig):
    _,fence,clock=rig
    with fence.hold() as first, fence.hold() as second:
        assert first.check()==second.check()
        clock[0]+=31
        for lease in (first,second):
            with pytest.raises(Refused,match='stale'):lease.check()
