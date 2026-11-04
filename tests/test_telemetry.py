"""Synthetic filesystem/history only; no real service or game operations."""
from pathlib import Path
import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import telemetry
import monitor
import monitor_runtime as runtime
from dnfgm.operations_dashboard import read_telemetry


@pytest.fixture
def recorder(tmp_path):
    root = tmp_path / 'releases'; root.mkdir()
    p = tmp_path / 'state.json'
    r = telemetry.Recorder(tmp_path / 'telemetry.sqlite', releases=str(root),
                           current=str(tmp_path/'current'),previous=str(tmp_path/'previous'),protection=str(p))
    yield r
    r.close()


def status(**overrides):
    return dict(cpu_percent=20,mem_available_mib=600,mem_total_mib=1600,
                swap_free_mib=3000,swap_total_mib=6000,disk_free_gib=10,disk_total_gib=40,core_ok=True,**overrides)


def test_history_minute_worst_values_and_health(recorder,monkeypatch):
    now=1800000000
    monkeypatch.setattr(telemetry.time,'time',lambda:now)
    recorder.observe(status())
    recorder.observe({**status(),'cpu_percent':60,'mem_available_mib':200,'core_ok':False})
    recorder.observe(status())
    d=read_telemetry(str(recorder.path))
    assert d['fresh'] and d['coverage_samples']==1
    assert d['points'][0]['cpu_percent']==60 and d['points'][0]['mem_available_mib']==200
    assert d['points'][0]['failed_samples']==1
    assert recorder.path.stat().st_mode & 0o777 == 0o644


def test_unknown_core_not_rewritten_as_healthy(recorder):
    recorder.observe({**status(),'core_ok':None,'state':'unknown'})
    recorder.observe(status())
    d=read_telemetry(str(recorder.path));assert d['points'][0]['unknown_samples']==1


def test_retention_and_clock_rollback(recorder,monkeypatch):
    now=1800000000;monkeypatch.setattr(telemetry.time,'time',lambda:now)
    with recorder.connection() as db:
        for minute in (now//60-10080,now//60-10079,now//60+1):
            db.execute("INSERT INTO samples(minute,sampled_at,state) VALUES(?,?,'unknown')",(minute,minute*60))
    recorder.observe(status())
    with recorder.connection() as db:assert [r[0] for r in db.execute('SELECT minute FROM samples ORDER BY minute')]==[now//60-10079,now//60]


def test_sparse_24h_and_7d_buckets_not_filled(recorder,monkeypatch):
    now=1800000000;monkeypatch.setattr(telemetry.time,'time',lambda:now)
    for offset in (7000,600,20,0):
        monkeypatch.setattr(telemetry.time,'time',lambda offset=offset:now-offset*60);recorder.observe(status())
    monkeypatch.setattr(telemetry.time,'time',lambda:now)
    assert read_telemetry(str(recorder.path))['coverage_samples']==3
    week=read_telemetry(str(recorder.path),'7d')
    assert week['coverage_samples']==4 and week['bucket_seconds']==1800


def test_event_retention_paging_and_secret_scrubbing(recorder):
    for i in range(270):recorder.record_event('probe_slow',{'probe':'dnf_components','argv':'secret-password','elapsed_seconds':i,'error_type':'unsafe/secret'})
    recorder.record_event('not_an_event',{'secret':'hidden'})
    d=read_telemetry(str(recorder.path));assert len(d['events'])==50 and d['next_before']
    assert set(d['events'][0]['details'])=={'probe','elapsed_seconds'}
    older=read_telemetry(str(recorder.path),before=d['next_before']);assert older['events'][0]['id']<d['next_before']
    with recorder.connection() as db:assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==256
    assert 'secret-password' not in recorder.path.read_bytes().decode(errors='ignore')


@pytest.mark.parametrize('kind',['missing','corrupt','symlink','locked','stale','future'])
def test_unavailable_is_not_empty_or_healthy(recorder,tmp_path,kind,monkeypatch):
    recorder.observe(status());path=recorder.path;lock=None
    if kind=='missing':path=tmp_path/'absent.sqlite'
    if kind=='corrupt':path=tmp_path/'broken';path.write_text('secret-private-path')
    if kind=='symlink':path=tmp_path/'link';path.symlink_to(recorder.path)
    if kind=='locked':lock=sqlite3.connect(path);lock.execute('BEGIN EXCLUSIVE')
    if kind in ('stale','future'):
        with recorder.connection() as db:recorder.meta(db,'updated_at',telemetry.time.time()+(-1000 if kind=='stale' else 1000))
    try:
        d=read_telemetry(str(path));assert not d['fresh']
        assert d['state']==('stale' if kind in ('stale','future') else 'unavailable')
        assert 'secret-private-path' not in json.dumps(d)
    finally:
        if lock:lock.close()


def test_protection_only_safe_fields_and_missing_replaces_old(recorder):
    recorder.protection.write_text(json.dumps({'reason':'resource_failure','stopped_at':100,'manual_restart_required':True,'secret':'do-not-send','raw_command':'cat /private'}))
    recorder.observe(status());d=read_telemetry(str(recorder.path))
    assert d['protection']=={'reason':'resource_failure','stopped_at':100,'manual_restart_required':True}
    recorder.protection.unlink();recorder.observe(status());assert read_telemetry(str(recorder.path))['protection'] is None


def test_release_inventory_protects_targets_and_refuses_symlinks(tmp_path):
    root=tmp_path/'releases';root.mkdir()
    for name in ('current-version','previous-version','historical-version'):
        (root/name).mkdir();(root/name/'SOURCE_REVISION').write_text('1234abc')
    (root/'linked').symlink_to(root/'historical-version',target_is_directory=True)
    cur=tmp_path/'current';cur.symlink_to(root/'current-version')
    prev=tmp_path/'previous';prev.symlink_to(root/'previous-version')
    rows=telemetry.inventory(root,cur,prev)['items']
    assert len(rows)==3 and sum(r['protected'] for r in rows)==2
    assert all(r['source_revision']=='1234abc' for r in rows)


def test_release_inventory_truncation_and_untrusted_metadata(tmp_path):
    root=tmp_path/'releases';root.mkdir()
    for i in range(103):(root/str(i)).mkdir()
    assert telemetry.inventory(root,tmp_path/'c',tmp_path/'p')['truncated']
    root2=tmp_path/'second';root2.mkdir();(root2/'one').mkdir();(root2/'one'/'SOURCE_REVISION').write_text('/etc/password')
    assert telemetry.inventory(root2,tmp_path/'c',tmp_path/'p')['items'][0]['source_revision'] is None


@pytest.mark.parametrize('result,expected', [('ok','ok'),('timeout','timeout'),('error','unavailable'),('malformed','unavailable')])
def test_storage_scan_fixed_argv_and_unknown_not_zero(tmp_path,result,expected):
    paths=[{'id':'fixture','label':'测试数据','path':str(tmp_path)}]
    calls=[]
    def run(argv,**kw):
        calls.append((argv,kw))
        if result=='timeout':raise subprocess.TimeoutExpired(argv,5)
        return SimpleNamespace(returncode=1 if result=='error' else 0,stdout=b'1234\tfixture\n' if result!='malformed' else b'partial\noutput\n')
    row=telemetry.scan_storage(paths,runner=run)['items'][0]
    assert row['state']==expected
    assert row['bytes']==(1234 if result=='ok' else None)
    assert calls[0][0]==['du','-sx','-B1','--',str(tmp_path)] and calls[0][1]['timeout']==5
    assert 'path' not in row


def test_storage_refuses_root_symlink(tmp_path):
    link=tmp_path/'link';link.symlink_to(tmp_path,target_is_directory=True)
    def nope(*a,**k):raise AssertionError('must not scan')
    d=telemetry.scan_storage([{'id':'fixture','label':'x','path':str(link)}],runner=nope)
    assert d['items'][0]['state']=='symlink_refused'


def test_monitor_failure_in_telemetry_does_not_disable_event(monkeypatch,capsys):
    class Bad:
        def record_event(self,*a):raise OSError('private credentials')
    monkeypatch.setattr(runtime,'TELEMETRY',Bad());runtime.event('protection_stop',reason='resource_failure')
    text=capsys.readouterr().out;assert 'protection_stop' in text and 'telemetry_write_failed' in text and 'private credentials' not in text


@pytest.mark.parametrize('paths',[[{'id':'x','label':'x','path':'/'}],[{'id':'x','label':'x','path':'/tmp/../private'}],[{'id':'x','label':'x','path':'/tmp'}]*2,[{'id':'bad;id','label':'x','path':'/tmp'}]])
def test_monitor_rejects_invalid_storage_configuration(paths):
    cfg=json.loads((Path(monitor.__file__).parent/'monitor.example.json').read_text());cfg['storage_paths']=paths
    with pytest.raises(ValueError):monitor.validate(cfg)


def test_background_scan_does_not_block_sampler(recorder,monkeypatch,tmp_path):
    import threading
    entered,release=threading.Event(),threading.Event()
    def scan(paths):
        entered.set();assert release.wait(3)
        return {'items':[],'collected_at':telemetry.time.time(),'note':'synthetic'}
    monkeypatch.setattr(telemetry,'scan_storage',scan)
    recorder.storage_paths=[{'id':'fixture','label':'测试','path':str(tmp_path)}]
    recorder.observe(status());assert entered.wait(1)
    # Sample again before allowing the storage scan to finish.
    recorder.observe(status());assert read_telemetry(str(recorder.path))['fresh']
    future=recorder.future;release.set();future.result(timeout=2);recorder.observe(status())
    assert recorder.future is None and read_telemetry(str(recorder.path))['storage']['note']=='synthetic'


def test_reader_projects_private_metadata_keys_out(recorder):
    recorder.observe(status())
    with recorder.connection() as db:
        recorder.meta(db,'storage',{'items':[{'id':'fixture','label':'x','bytes':2,'path':'/private/secret','password':'hidden'}],'secret':'hidden'})
        recorder.meta(db,'releases',{'items':[{'name':'release','source_revision':'abc','config':'private'}],'secret':'hidden'})
        recorder.meta(db,'protection',{'reason':'resource_failure','private':'hidden'})
    text=json.dumps(read_telemetry(str(recorder.path)))
    assert 'hidden' not in text and '/private' not in text and '"config"' not in text


def test_storage_real_temporary_tree_no_external_follow(tmp_path):
    root=tmp_path/'scan';root.mkdir();(root/'file').write_bytes(b'x'*8192)
    elsewhere=tmp_path/'private';elsewhere.mkdir();(elsewhere/'data').write_bytes(b'x'*1048576)
    (root/'symlink').symlink_to(elsewhere,target_is_directory=True)
    d=telemetry.scan_storage([{'id':'fixture','label':'临时目录','path':str(root)}])['items'][0]
    assert d['state']=='ok' and 8192<=d['bytes']<1048576


def test_monitor_observe_failure_preserves_protection_loop(monkeypatch,tmp_path):
    clock=[0];calls=[]
    class Bad:
        def record_event(self,*a):pass
        def observe(self,*a):raise OSError('private diagnostics failure')
    monkeypatch.setattr(runtime,'DEST',tmp_path/'run/status.json')
    monkeypatch.setattr(runtime,'STATE',tmp_path/'state/protection.json')
    monkeypatch.setattr(runtime,'cpu',lambda:(100,50))
    monkeypatch.setattr(runtime,'resources',lambda _:dict(mem_available_mib=100,swap_free_mib=4000,disk_free_gib=10))
    monkeypatch.setattr(runtime.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(runtime.Controller,'apply',lambda _,reason,*args:calls.append(reason))
    def sleep(_):
        clock[0]+=5
        if clock[0]>=10:raise KeyboardInterrupt
    monkeypatch.setattr(runtime.time,'sleep',sleep)
    # Restore the global even though run assigns it internally.
    monkeypatch.setattr(runtime,'TELEMETRY',None)
    with pytest.raises(KeyboardInterrupt):runtime.run(lambda:{'core_ok':True},disk_path=str(tmp_path),telemetry=Bad())
    assert calls==[None,'resource_failure']
    assert json.loads(runtime.DEST.read_text())['state']=='resource_protection'


def test_inventory_failure_does_not_discard_resource_history(recorder,monkeypatch):
    def fail(*a):raise PermissionError('private directory')
    monkeypatch.setattr(telemetry,'inventory',fail)
    recorder.observe(status());d=read_telemetry(str(recorder.path))
    assert d['fresh'] and d['points'] and d['releases']['state']=='unavailable'


def test_failed_background_task_is_consumed_not_permanently_rethrown(recorder):
    from concurrent.futures import Future
    f=Future();f.set_exception(OSError('private storage scan'))
    recorder.future=f;recorder.observe(status())
    d=read_telemetry(str(recorder.path));assert d['fresh'] and d['storage']['state']=='unavailable'
    assert recorder.future is None and 'private storage scan' not in json.dumps(d)


def test_storage_permission_is_not_absence(tmp_path,monkeypatch):
    original=Path.lstat
    def stat(path,*a,**k):
        if path==tmp_path/'forbidden':raise PermissionError('secret')
        return original(path,*a,**k)
    monkeypatch.setattr(Path,'lstat',stat)
    d=telemetry.scan_storage([{'id':'denied','label':'拒绝','path':str(tmp_path/'forbidden')},{'id':'absent','label':'缺失','path':str(tmp_path/'absent')}])
    assert [i['state'] for i in d['items']]==['unavailable','missing']
