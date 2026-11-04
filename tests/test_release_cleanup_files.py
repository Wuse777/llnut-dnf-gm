"""Only temporary synthetic packages are deleted; never /opt or production data."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import time

import pytest
from dnfgm import release_files as rf

KEY=b'fixture-only-cleanup-key-32-bytes!'
UID=os.getuid()
SPEC=importlib.util.spec_from_file_location('cleanup_worker_fixture',Path(__file__).resolve().parents[1]/'deploy/cleanup_worker.py')
worker=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(worker)


@pytest.fixture
def tree(tmp_path):
    base=tmp_path/'gm';root=base/'releases';root.mkdir(parents=True)
    for n in range(6):
        p=root/f'release{n}';p.mkdir()
        for marker in ('SOURCE_REVISION','SHA256SUMS','pyproject.toml'):(p/marker).write_text('synthetic package\n')
        (p/'src').mkdir();(p/'src'/'app.py').write_text('# no executable fixture\n')
        os.utime(p,(1000+n,1000+n))
    for p in [base,root,*root.rglob('*')]:p.chmod(0o755 if p.is_dir() else 0o644)
    (base/'current').symlink_to(root/'release4')
    (base/'previous').symlink_to(root/'release3')
    return base


def request(tree,names=('release0',),op='a'*32):
    items=[]
    for name in names:
        d=rf.describe(tree,name,owner=UID)
        items.append({'descriptor':d,'ticket':rf.sign(d,KEY)})
    return {'operation_id':op,'items':items}


def run(tree,req,tmp_path,**kw):
    with rf.maintenance_lock(tmp_path/'lock'):
        return rf.execute(tree,req,KEY,tmp_path/'receipt.json',owner=UID,**kw)


def test_protected_current_previous_and_two_newest(tree):
    assert rf.protected_names(tree,UID)=={'release3','release4','release5'}
    m=rf.manifest(tree,KEY,owner=UID)
    assert m['state']=='ok'
    assert [r['name'] for r in m['items'] if r['eligible']]==['release0','release1','release2']
    for n in ('release3','release4','release5'):
        with pytest.raises(rf.Refused,match='protected_release'):rf.describe(tree,n,owner=UID)


@pytest.mark.parametrize('name',['../elsewhere','/tmp/x','.', '..','release0/x','x\n','x'*97,''])
def test_no_arbitrary_paths(tree,name):
    with pytest.raises(rf.Refused):rf.describe(tree,name,owner=UID)


def test_package_markers_and_tree_identity(tree):
    d=rf.describe(tree,'release0',owner=UID)
    assert d['entries']==6 and d['allocated_bytes']>0
    assert rf.describe(tree,'release0',owner=UID)['fingerprint']==d['fingerprint']
    (tree/'releases/release0/SHA256SUMS').unlink()
    os.utime(tree/'releases/release0',(1000,1000))
    with pytest.raises(rf.Refused,match='not_a_release_package'):rf.describe(tree,'release0',owner=UID)


@pytest.mark.parametrize('kind',['symlink','hardlink','fifo','writable','wrong_owner','directory_link'])
def test_no_symlinks_special_files_or_mutable_packages(tree,tmp_path,kind):
    p=tree/'releases/release0/src';owner=UID
    if kind=='symlink':(p/'unsafe').symlink_to(tmp_path/'outside')
    if kind=='directory_link':(p/'unsafe').symlink_to(tree/'releases/release4',target_is_directory=True)
    if kind=='hardlink':os.link(p/'app.py',p/'linked')
    if kind=='fifo':os.mkfifo(p/'fifo')
    if kind=='writable':(p/'app.py').chmod(0o666)
    if kind=='wrong_owner':owner=UID+1
    with pytest.raises(rf.Refused):rf.describe(tree,'release0',owner=owner)


def test_protected_pointer_outside_root_fails_closed(tree,tmp_path):
    (tree/'current').unlink();(tree/'current').symlink_to(tmp_path)
    assert rf.manifest(tree,KEY,owner=UID)['state']=='unavailable'
    with pytest.raises(rf.Refused,match='release_pointer_outside'):rf.describe(tree,'release0',owner=UID)


def test_mounts_including_same_device_and_escaped_paths(tree):
    target=tree/'releases/release0/src'
    line=f'55 40 8:1 / {target} rw - ext4 /dev/x rw'
    with pytest.raises(rf.Refused,match='nested_mount'):rf.describe(tree,'release0',owner=UID,mounts=line)
    assert rf.mounted_below(Path('/some space'),r'55 40 8:1 / /some\040space/bind rw - ext4 /dev/x rw')
    assert not rf.mounted_below(Path('/some'),r'55 40 8:1 / /somewhere rw - ext4 /dev/x rw')


def test_depth_and_entry_limits(tree,monkeypatch):
    p=tree/'releases/release0/src';(p/'nested').mkdir(mode=0o755)
    monkeypatch.setattr(rf,'MAX_DEPTH',1)
    with pytest.raises(rf.Refused,match='tree_too_deep'):rf.describe(tree,'release0',owner=UID)
    monkeypatch.setattr(rf,'MAX_DEPTH',48);monkeypatch.setattr(rf,'MAX_FILES',2)
    with pytest.raises(rf.Refused,match='too_many_entries'):rf.describe(tree,'release0',owner=UID)


def test_read_json_rejects_unsafe_files_and_size(tmp_path):
    p=tmp_path/'x';rf.atomic_json(p,{'hello':'world'},0o600)
    assert rf.read_json(p,owner=UID)=={'hello':'world'}
    with pytest.raises(rf.Refused):rf.read_json(p,owner=UID+1)
    with pytest.raises(rf.Refused):rf.read_json(p,limit=3)
    p.chmod(0o666)
    with pytest.raises(rf.Refused):rf.read_json(p)
    p.unlink();p.symlink_to(tmp_path/'absent')
    with pytest.raises(OSError):rf.read_json(p)
    p.unlink();os.mkfifo(p)
    with pytest.raises(rf.Refused):rf.read_json(p)


def test_flock_is_shared_nonblocking_and_released(tmp_path):
    lock=tmp_path/'lock'
    with rf.maintenance_lock(lock):
        with pytest.raises(BlockingIOError):
            with rf.maintenance_lock(lock):pass
    with rf.maintenance_lock(lock):pass
    lock.chmod(0o666)
    with pytest.raises(rf.Refused):
        with rf.maintenance_lock(lock):pass


def test_real_temp_deletion_exact_selection_and_idempotent_receipt(tree,tmp_path):
    req=request(tree,('release0','release1'))
    r=run(tree,req,tmp_path)
    assert r['state']=='completed' and r['atomic'] is False
    assert [x['state'] for x in r['items']]==['removed','removed']
    assert not (tree/'releases/release0').exists()
    assert sorted(p.name for p in (tree/'releases').iterdir())==['release2','release3','release4','release5']
    assert run(tree,req,tmp_path,remover=lambda *a,**k:pytest.fail('must not replay'))==r
    changed=copy.deepcopy(req);changed['items'].pop()
    with pytest.raises(rf.Refused,match='operation_conflict'):run(tree,changed,tmp_path)


@pytest.mark.parametrize('fault',['signature','expired','changed','protected','duplicate','extra_key'])
def test_all_selections_validated_before_any_deletion(tree,tmp_path,fault):
    req=request(tree,('release0','release1'));item=req['items'][1]
    if fault=='signature':item['ticket']='0'*64
    if fault=='expired':
        item['descriptor']['expires_at']=1;item['ticket']=rf.sign(item['descriptor'],KEY)
    if fault=='changed':(tree/'releases/release1/src/app.py').write_text('changed')
    if fault=='protected':(tree/'previous').unlink();(tree/'previous').symlink_to(tree/'releases/release1')
    if fault=='duplicate':req['items'][1]=req['items'][0]
    if fault=='extra_key':item['command']='rm -rf /'
    r=run(tree,req,tmp_path,remover=lambda *a,**k:pytest.fail('preflight must reject'))
    assert r['state']=='rejected'
    assert (tree/'releases/release0').exists() and (tree/'releases/release1').exists()


def test_partial_deletion_has_receipt_and_never_replays(tree,tmp_path):
    req=request(tree,('release0','release1'))
    def partial(name,**kwargs):
        if name=='release1':raise OSError('private filesystem error must not leak')
        shutil.rmtree(name,**kwargs)
    r=run(tree,req,tmp_path,remover=partial)
    assert r['state']=='needs_review' and r['reason']=='deletion_failed'
    assert [i['state'] for i in r['items']]==['removed','partial_or_unknown']
    assert 'private filesystem' not in json.dumps(r)
    assert run(tree,req,tmp_path,remover=lambda *a,**k:pytest.fail('no retry'))==r


def test_killed_worker_reconciles_without_deleting_again(tree,tmp_path):
    req=request(tree)
    class Killed(BaseException):pass
    def kill(*a,**kw):raise Killed()
    with pytest.raises(Killed):run(tree,req,tmp_path,remover=kill)
    assert rf.read_json(tmp_path/'receipt.json')['state']=='executing'
    r=run(tree,req,tmp_path,remover=lambda *a,**kw:pytest.fail('no replay'))
    assert r['state']=='needs_review' and r['items'][0]['state']=='interrupted_unknown'


def queue(tmp_path):
    state=tmp_path/'state';(state/'inbox').mkdir(parents=True);(state/'results').mkdir()
    return state


def tick(tree,state,tmp_path,monkeypatch,ready=True):
    monkeypatch.setattr(worker,'resources_ready',lambda:ready)
    worker.tick(tree,state,tmp_path/'manifest.json',tmp_path/'lock',KEY,UID,owner=UID)


def test_worker_bounded_to_one_request_and_no_database(tree,tmp_path,monkeypatch):
    state=queue(tmp_path)
    for op,name in [('a'*32,'release0'),('b'*32,'release1')]:rf.atomic_json(state/'inbox'/f'{op}.json',request(tree,(name,),op),0o600)
    tick(tree,state,tmp_path,monkeypatch)
    assert len(list((state/'inbox').iterdir()))==1 and len(list((state/'results').iterdir()))==1
    assert not (tree/'releases/release0').exists() and (tree/'releases/release1').exists()
    tick(tree,state,tmp_path,monkeypatch)
    assert not (tree/'releases/release1').exists()


def test_worker_recovery_precedes_resource_gate(tree,tmp_path,monkeypatch):
    state=queue(tmp_path);req=request(tree);op=req['operation_id']
    rf.atomic_json(state/'inbox'/f'{op}.json',req,0o600)
    rf.atomic_json(state/'results'/f'{op}.json',{'operation_id':op,'request_sha256':hashlib.sha256(rf.canonical(req)).hexdigest(),'state':'executing','items':[{'name':'release0','state':'deleting'}]})
    tick(tree,state,tmp_path,monkeypatch,ready=False)
    assert rf.read_json(state/'results'/f'{op}.json')['state']=='needs_review'
    assert (tree/'releases/release0').exists() and not list((state/'inbox').iterdir())


@pytest.mark.parametrize('kind',['resources','list','bad_signature','symlink'])
def test_worker_refuses_bad_queue_and_low_resources(tree,tmp_path,monkeypatch,kind):
    state=queue(tmp_path);op='a'*32;req=request(tree)
    if kind=='list':req=[]
    if kind=='bad_signature':req['items'][0]['ticket']='0'*64
    p=state/'inbox'/f'{op}.json'
    if kind=='symlink':p.symlink_to(tmp_path/'outside')
    else:rf.atomic_json(p,req,0o600)
    tick(tree,state,tmp_path,monkeypatch,ready=kind!='resources')
    r=rf.read_json(state/'results'/f'{op}.json')
    assert r['state']=='rejected' and (tree/'releases/release0').exists()
    assert not list((state/'inbox').iterdir())


def test_worker_cannot_run_while_installer_holds_lock(tree,tmp_path,monkeypatch):
    state=queue(tmp_path);rf.atomic_json(state/'inbox'/('a'*32+'.json'),request(tree),0o600)
    with rf.maintenance_lock(tmp_path/'lock'):
        with pytest.raises(BlockingIOError):tick(tree,state,tmp_path,monkeypatch)
    assert (tree/'releases/release0').exists() and not (tmp_path/'manifest.json').exists()


def test_monitor_and_resource_gate_fail_closed(monkeypatch):
    monkeypatch.setattr(Path,'read_text',lambda self:'MemAvailable: 900000 kB\nSwapFree: 3000000 kB\n')
    for live,expected in [({'core_ok':True,'collected_at':time.time()},True),({'core_ok':False,'collected_at':time.time()},False),({'core_ok':True,'collected_at':1},False),({},False)]:
        monkeypatch.setattr(worker,'read_json',lambda *a,**k:live)
        assert worker.resources_ready() is expected
    monkeypatch.setattr(worker,'read_json',lambda *a,**k:{'core_ok':True,'collected_at':time.time()})
    monkeypatch.setattr(Path,'read_text',lambda self:'MemAvailable: 900000 kB\nSwapFree: 0 kB\n')
    assert not worker.resources_ready()
    monkeypatch.setattr(worker,'read_json',lambda *a,**k:(_ for _ in ()).throw(FileNotFoundError('missing monitor')))
    assert not worker.resources_ready()


def test_non_finite_json_and_invalid_root_receipts_rejected(tmp_path,tree):
    p=tmp_path/'invalid';p.write_text('{"expires_at": NaN}');p.chmod(0o600)
    with pytest.raises(rf.Refused,match='non_finite_json'):rf.read_json(p)
    req=request(tree)
    rf.atomic_json(tmp_path/'receipt.json',[])
    with pytest.raises(rf.Refused,match='invalid_receipt'):run(tree,req,tmp_path)


def test_opt_in_worker_no_service_control_or_database_and_shared_slice():
    root=Path(__file__).resolve().parents[1]
    unit=(root/'deploy/dnf-gm-cleanup.service').read_text()
    source=(root/'deploy/cleanup_worker.py').read_text()
    assert 'Slice=dnf-gm.slice' in unit and 'PrivateNetwork=yes' in unit and 'ProtectSystem=strict' in unit
    assert 'ReadWritePaths=/opt/dnf-gm/releases /var/lib/dnf-gm/cleanup /var/lib/dnf-gm/maintenance.lock /run/dnf-gm' in unit
    assert all(term not in source for term in ('subprocess','pymysql','os.system','socket.','systemctl'))
    installer=(root/'deploy/install.sh').read_text()
    assert 'CLEANUP_RESTART=false' in installer and 'systemctl enable --now dnf-gm-cleanup.timer' not in installer
    rollback=(root/'deploy/rollback.sh').read_text()
    assert 'flock -x 9' in installer and 'flock -x 9' in rollback


def test_installer_inherited_lock_does_not_deadlock_or_release_early(tmp_path):
    import subprocess
    source=(Path(__file__).resolve().parents[1]/'deploy/install.sh').read_text()
    prefix='# Keep the same inherited flock'+source.split('# Keep the same inherited flock',1)[1].split('\nBASE=',1)[0]
    prefix=prefix.replace('/var/lib/dnf-gm',str(tmp_path/'state'))
    child=tmp_path/'child.sh';child.write_text('set -euo pipefail\n'+prefix+'\nprintf inherited-lock-ok\n')
    result=subprocess.run(['bash','-c',prefix+'\nexec bash "$1"','_',str(child)],capture_output=True,text=True,timeout=4)
    assert result.returncode==0 and result.stdout=='inherited-lock-ok'
    with rf.maintenance_lock(tmp_path/'state/maintenance.lock'):
        p=subprocess.Popen(['bash',str(child)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            with pytest.raises(subprocess.TimeoutExpired):p.communicate(timeout=0.1)
        except BaseException:
            p.kill();p.communicate();raise
    out,err=p.communicate(timeout=4)
    assert p.returncode==0 and out=='inherited-lock-ok'


def test_pointer_changed_mid_batch_stops_before_next_directory(tree,tmp_path):
    req=request(tree,('release0','release1'))
    def move_pointer(name,**kwargs):
        shutil.rmtree(name,**kwargs)
        (tree/'previous').unlink();(tree/'previous').symlink_to(tree/'releases/release1')
    r=run(tree,req,tmp_path,remover=move_pointer)
    assert r['state']=='needs_review' and r['reason']=='protected_release'
    assert [i['state'] for i in r['items']]==['removed','prepared']
    assert (tree/'releases/release1').exists()
