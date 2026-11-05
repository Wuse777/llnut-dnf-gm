"""Filesystem/concurrency fixtures only. No game commands or production paths."""
import copy
import fcntl
import os
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import Mock

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
from maintenance_gate import WriteGateManager, binding_hash
from dnfgm.write_gate import GameplayWriteGate, WriteGateClosed, validate
from dnfgm.inventory_fence import open_lock
from dnfgm.release_files import Refused, atomic_json
from check_maintenance_idle import assert_idle

OP='a'*32
IDENTITY={'container_id':'c'*64,'pid':101,'boot_id':'11111111-2222-3333-4444-555555555555','container_started_at':'fixture-start',
          'image_digest':'sha256:'+'a'*64,'program_sha256':'b'*64,'pvf_sha256':'d'*64,'policy_sha256':'e'*64}


@pytest.fixture
def rig(tmp_path):
    root=tmp_path/'gate';manager=WriteGateManager(root,owner=os.geteuid());manager.initialize()
    settings=SimpleNamespace(gameplay_gate_dir=str(root));gate=GameplayWriteGate(settings,owner=os.geteuid())
    return manager,gate


def test_legacy_path_is_not_a_maintenance_capability():
    gate=GameplayWriteGate(SimpleNamespace(gameplay_gate_dir=''))
    assert gate.status()=={'configured':False,'state':'not_configured','maintenance_supported':False}
    with gate.writer() as lease:lease.check()


def test_shared_writers_block_freeze_until_both_leave(rig):
    m,g=rig
    with g.writer() as a:
        with g.writer() as b:
            a.check();b.check()
            with pytest.raises(Refused,match='busy'):m.freeze(OP,IDENTITY)
        with pytest.raises(Refused,match='busy'):m.freeze(OP,IDENTITY)
    token=m.freeze(OP,IDENTITY)
    assert g.status()['state']=='frozen' and m.check_frozen(token)==token
    with pytest.raises(WriteGateClosed) as e:
        with g.writer():pytest.fail('frozen writer entered')
    assert e.value.gate_state=='frozen'


def test_restarts_do_not_expire_or_reopen_freeze(rig):
    m,g=rig;token=m.freeze(OP,IDENTITY)
    again=WriteGateManager(m.root,owner=m.owner,clock=lambda:10**12)
    assert again.initialize()==token and again.freeze(OP,IDENTITY)==token
    assert g.status()['state']=='frozen'
    with pytest.raises(WriteGateClosed):
        with g.writer():pass


def test_release_requires_correct_token_and_verified_restore(rig):
    m,g=rig;token=m.freeze(OP,IDENTITY)
    for result in (False,None,1,{},'true'):
        with pytest.raises(Refused,match='restore_not_proven'):m.release(token,lambda:result)
        assert g.status()['state']=='frozen'
    with pytest.raises(Refused,match='token_changed'):m.release({**token,'generation':token['generation']+1},lambda:True)
    with pytest.raises(Refused,match='other_request'):m.freeze('b'*32,IDENTITY)
    with pytest.raises(Refused,match='other_request'):m.freeze(OP,{**IDENTITY,'pvf_sha256':'f'*64})
    proof=Mock(return_value=True);result=m.release(token,proof)
    assert result['state']=='open' and m.release(token,proof)==result and proof.call_count==1
    with g.writer() as lease:lease.check()
    with pytest.raises(Refused,match='already_released'):m.freeze(OP,IDENTITY)
    newer=m.freeze('b'*32,IDENTITY);assert newer['generation']==2
    with pytest.raises(Refused,match='token_changed'):m.release(token,lambda:True)


def test_restore_exception_never_reopens(rig):
    m,g=rig;token=m.freeze(OP,IDENTITY)
    def failed():raise OSError('synthetic restore failure')
    with pytest.raises(OSError):m.release(token,failed)
    assert m.read()==token and g.status()['state']=='frozen'


@pytest.mark.parametrize('file',['state.json','fence.lock'])
def test_missing_state_or_lock_is_not_reinitialized_as_open(rig,file):
    m,g=rig;m.freeze(OP,IDENTITY);(m.root/file).unlink()
    assert g.status()['state']=='unknown'
    with pytest.raises((Refused,OSError)):m.initialize()
    with pytest.raises(WriteGateClosed):
        with g.writer():pass


@pytest.mark.parametrize('change',['garbage','link','hardlink','mode','owner','directory','state_type','generation_bool','version_bool'])
def test_untrusted_state_fails_closed(rig,tmp_path,change):
    m,g=rig;path=m.root/'state.json'
    if change=='garbage':path.write_text('{broken')
    elif change=='link':
        path.rename(tmp_path/'real.json');path.symlink_to(tmp_path/'real.json')
    elif change=='hardlink':os.link(path,tmp_path/'link.json')
    elif change=='mode':path.chmod(0o666)
    elif change=='owner':g.owner=os.geteuid()+1
    elif change=='directory':m.root.chmod(0o777)
    elif change=='state_type':atomic_json(path,[])
    else:
        data=m.read();data['generation' if change=='generation_bool' else 'version']=True;atomic_json(path,data)
    assert g.status()['state']=='unknown'
    with pytest.raises(WriteGateClosed):
        with g.writer():pass


def test_lease_rechecks_lock_and_state_before_commit(rig):
    m,g=rig
    with g.writer() as lease:
        initial=m.read();atomic_json(m.root/'state.json',{**initial,'changed_at':initial['changed_at']+1})
        with pytest.raises(WriteGateClosed):lease.check()
    with g.writer() as lease:
        (m.root/'fence.lock').rename(m.root/'old.lock');(m.root/'fence.lock').touch(mode=0o644)
        with pytest.raises(WriteGateClosed):lease.check()


def test_exclusive_initialization_or_transition_refuses_new_writers(rig):
    m,g=rig
    with m.locked(True):
        assert g.status()['state']=='unknown'
        with pytest.raises(WriteGateClosed):
            with g.writer():pass
    assert g.status()['state']=='open'


def test_application_exception_releases_shared_lock(rig):
    m,g=rig
    with pytest.raises(RuntimeError):
        with g.writer():raise RuntimeError('transaction rolled back')
    assert m.freeze(OP,IDENTITY)['state']=='frozen'


def test_freeze_survives_executor_process_exit(rig):
    m,g=rig
    pid=os.fork()
    if pid==0:
        try:m.freeze(OP,IDENTITY)
        except BaseException:os._exit(2)
        os._exit(0)
    _,status=os.waitpid(pid,0);assert os.waitstatus_to_exitcode(status)==0
    assert g.status()['state']=='frozen'
    with pytest.raises(WriteGateClosed):
        with g.writer():pass


def test_lost_atomic_write_reconciles_original_state(rig,monkeypatch):
    import maintenance_gate as module
    m,g=rig;original=module.atomic_json
    def lost(*a,**kw):original(*a,**kw);raise OSError('response lost after replace')
    monkeypatch.setattr(module,'atomic_json',lost)
    with pytest.raises(OSError):m.freeze(OP,IDENTITY)
    token=m.freeze(OP,IDENTITY);assert g.status()['state']=='frozen'
    with pytest.raises(OSError):m.release(token,lambda:True)
    assert m.release(token,lambda:pytest.fail('must not repeat proof'))['state']=='open'


def test_installer_refuses_frozen_gate_without_a_drain_journal(rig,tmp_path):
    m,g=rig
    assert_idle(state=tmp_path/'missing-drain',runtime=tmp_path/'missing-permit',gate=m.root,owner=m.owner)
    m.freeze(OP,IDENTITY)
    with pytest.raises(Refused,match='game_writes_frozen'):
        assert_idle(state=tmp_path/'missing-drain',runtime=tmp_path/'missing-permit',gate=m.root,owner=m.owner)


@pytest.mark.parametrize('field',['container_id','program_sha256','pvf_sha256','policy_sha256','image_digest','pid','boot_id','container_started_at','extra'])
def test_forged_binding_cannot_freeze(rig,field):
    m,g=rig;identity=copy.deepcopy(IDENTITY);identity[field]=True
    with pytest.raises(Refused,match='binding_invalid'):m.freeze(OP,identity)
    assert g.status()['state']=='open'
