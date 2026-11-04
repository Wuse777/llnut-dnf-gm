"""Synthetic observations only. Never calls production, a webhook or systemctl."""
import copy
import json
import os
from pathlib import Path
import sys
import pytest
from dnfgm import alerts as a
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import alert_worker as worker

THRESHOLDS = {'memory': 256, 'swap': 1536, 'disk': 2}
CFG = {'health_host': '127.0.0.1:8765', 'thresholds': THRESHOLDS, 'webhook_url': '', 'webhook_token': ''}


def values(t, **kw):
    status = dict(collected_at=t, core_ok=True, mem_available_mib=500, swap_free_mib=5000, disk_free_gib=12)
    status.update(kw)
    return a.observations(status, True, t, THRESHOLDS)


def fire():
    state = a.new_state()
    a.observe(state, values(100, mem_available_mib=100), 100)
    a.observe(state, values(130, mem_available_mib=100), 130)
    return state


def test_debounce_repeat_recovery_and_unique_ids():
    state=fire()
    assert len(state['history'])==1 and state['rules']['memory']['active']
    for t in (160,190,220): a.observe(state,values(t,mem_available_mib=100),t)
    assert len(state['history'])==1
    for t in (250,280): a.observe(state,values(t),t)
    assert [e['state'] for e in state['history']]==['firing','resolved']
    assert len({e['id'] for e in state['history']})==2
    assert a.pending(state)[0]['state']=='resolved'


def test_unknown_and_cached_observation_never_resolve_or_confirm():
    s=a.new_state();v=values(100,core_ok=False)
    a.observe(s,v,100);a.observe(s,v,130)
    assert not s['rules']['core']['active']
    a.observe(s,values(160,core_ok=False),160)
    assert s['rules']['core']['active']
    a.observe(s,a.observations(None,False,190,THRESHOLDS),190)
    assert s['rules']['core']['active'] and s['rules']['core']['observed']=='unknown'
    assert len(s['history'])==1


def test_elapsed_confirmation_gap_and_clock_regression():
    s=a.new_state()
    for t in (1,2): a.observe(s,values(t,core_ok=False),t)
    assert not s['history']
    a.observe(s,values(200,core_ok=False),200)
    assert not s['history']
    with pytest.raises(ValueError): a.observe(s,values(199),199)
    a.observe(s,values(230,core_ok=False),230)
    assert len(s['history'])==1


@pytest.mark.parametrize('timestamp', [None,True,float('nan'),1000,0])
def test_stale_missing_future_invalid_collector(timestamp):
    o=a.observations({'collected_at':timestamp,'core_ok':True},True,500,THRESHOLDS)
    assert o['collector']['bad'] and o['core']['bad'] is None


def test_maintenance_excuses_only_verified_current_core():
    o=values(100,core_ok=False,mem_available_mib=100,maintenance={'active':True,'verified':True,'collected_at':100,'expires_at':120})
    assert o['core']['bad'] is None and o['memory']['bad'] is True
    for window in ({'active':True,'verified':False}, {'active':True,'verified':True,'collected_at':100,'expires_at':99}):
        assert values(100,core_ok=False,maintenance=window)['core']['bad'] is True


def test_response_loss_persists_before_send_retries_same_id():
    s=fire();saved=[];sent=[]
    def persist(x): saved.append(copy.deepcopy(x))
    def send(body):
        assert saved[-1]['notification']['state']=='pending'
        sent.append(body);raise OSError('secret URL must never escape')
    a.delivery(s,130,True,send,persist)
    assert s['notification']['next_attempt']==190
    a.delivery(s,160,True,send,persist);assert len(sent)==1
    a.delivery(s,190,True,send,persist);assert len(sent)==2
    assert sent[0]['events'][0]['id']==sent[1]['events'][0]['id']
    assert 'secret' not in json.dumps(s)
    a.delivery(s,310,True,lambda _:True,persist)
    assert not a.pending(s) and s['notification']['state']=='accepted'
    a.delivery(s,340,True,lambda _:pytest.fail('Duplicate notification'),persist)


def test_no_send_when_intent_cannot_persist():
    with pytest.raises(OSError):
        a.delivery(fire(),130,True,lambda _:pytest.fail('Must not send'),lambda _:(_ for _ in ()).throw(OSError()))


def test_disabled_collects_history_without_network_and_restart_dedup(tmp_path):
    status=tmp_path/'status.json';root=tmp_path/'alerts';root.mkdir()
    def run(t):
        a.atomic(status,dict(collected_at=t,core_ok=False))
        return worker.run_once(CFG,root=root,status_path=status,clock=lambda:t,probe=lambda _:False,send=lambda *_:pytest.fail('disabled'))
    run(100);r=run(130);assert len(r['history'])==2
    run(160);assert len(a.read_json(root/'private.json')['history'])==2
    assert os.stat(root/'private.json').st_mode & 0o777==0o600
    assert os.stat(root/'public.json').st_mode & 0o777==0o644
    public=a.read_report(root/'public.json',300)
    assert public['state']=='stale' and len(public['history'])==2
    os.unlink(root/'private.json')
    with pytest.raises(ValueError): run(330)


def test_public_projection_no_secrets_and_malformed_does_not_show_healthy(tmp_path):
    r=a.public_view(fire(),130);r['webhook_token']='secret';r['rules'][0]['label']='secret'
    p=tmp_path/'public.json';a.atomic(p,r)
    assert 'secret' not in json.dumps(a.read_report(p,130))
    for mutation in [lambda r:r.update(rules=[]),lambda r:r['notification'].update(last_attempt='secret'),lambda r:r['rules'][0].update(observed='secret')]:
        x=copy.deepcopy(r);mutation(x);a.atomic(p,x)
        assert a.read_report(p,130)['state']=='unavailable'


def test_reject_symlinks_oversize_fifo_and_corrupted_state(tmp_path):
    p=tmp_path/'x';p.write_text('{}');link=tmp_path/'link';link.symlink_to(p)
    assert a.read_report(link,100)['state']=='unavailable'
    p.write_bytes(b' '*(a.MAX_BYTES+1));assert a.read_report(p,100)['state']=='unavailable'
    fifo=tmp_path/'fifo';os.mkfifo(fifo);assert a.read_report(fifo,100)['state']=='unavailable'
    with pytest.raises(ValueError): a.validate_state({'version':1})


def test_history_bounded():
    s=a.new_state()
    for t in range(100,10000,30):
        a.observe(s,values(t,core_ok=(t//60)%2==0),t)
    assert len(s['history'])==100 and len(a.pending(s))<=len(a.LABELS)


@pytest.mark.parametrize('url', ['http://example.com','https://user:pw@example.com','https://example.com:8443','https://127.0.0.1','https://169.254.169.254','https://example.com/#secret','https://example.com/\n'])
def test_reject_unsafe_destinations(url):
    with pytest.raises(ValueError): worker.validate_config({**CFG,'webhook_url':url})


def test_config_and_no_redirect():
    assert worker.validate_config(CFG)==CFG
    with pytest.raises(ValueError): worker.validate_config({**CFG,'webhook_token':'x'})
    with pytest.raises(ValueError): worker.validate_config({**CFG,'health_host':'x\r\nX:a'})
    assert worker.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.test') is None


def test_network_requests_fixed_health_and_private_payload(monkeypatch):
    calls=[]
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):assert n==8193;return b'{"ok":true}'
    class Opener:
        def open(self,req,timeout):calls.append((req,timeout));return Response()
    monkeypatch.setattr(worker,'build_opener',lambda *args:Opener())
    assert worker.health(CFG)
    cfg={**CFG,'webhook_url':'https://example.com/hook','webhook_token':'private'}
    assert worker.notify(cfg,{'events':[]})
    assert calls[0][0].full_url=='http://127.0.0.1:8765/dnf-gm/api/v1/health'
    assert calls[1][0].get_header('Authorization')=='Bearer private'
    assert all(timeout==3 for _,timeout in calls)


def test_unit_is_independent_unprivileged_and_in_shared_budget():
    deploy=Path(worker.__file__).parent
    unit=(deploy/'dnf-gm-alert.service').read_text()
    assert 'User=dnfgm-alert' in unit and 'Slice=dnf-gm.slice' in unit and 'TimeoutStartSec=15' in unit
    assert 'Requires=dnf-gm.service' not in unit and 'PartOf=' not in unit
    assert 'CapabilityBoundingSet=\n' in unit and 'MemoryMax=32M' in unit
    script=(deploy/'enable-alerts.sh').read_text()
    assert 'systemctl restart' not in script and 'systemctl stop' not in script


def test_worker_lock_prevents_overlapping_sender(tmp_path):
    import fcntl
    lock=tmp_path/'worker.lock'
    with lock.open('w') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            worker.run_once(CFG,root=tmp_path,probe=lambda _:pytest.fail('Overlapping probe'))


def test_missing_core_is_unknown_not_healthy_collector():
    assert a.observations({'collected_at':100},True,100,THRESHOLDS)['collector']['bad'] is True


def test_corrupt_existing_private_file_never_resets_dedup(tmp_path):
    (tmp_path/'private.json').write_text('{')
    with pytest.raises(ValueError):
        worker.run_once(CFG,root=tmp_path,probe=lambda _:pytest.fail('Must fail closed'))


def test_retry_delay_capped_and_coalescing_recovers_without_old_outage():
    s=fire();now=130
    for _ in range(12):
        a.delivery(s,now,True,lambda _:False,lambda _:None)
        assert s['notification']['next_attempt']-now<=3600
        now=s['notification']['next_attempt']
    for t in (now,now+30):a.observe(s,values(t),t)
    sent=[]
    a.delivery(s,now+60,True,lambda body:sent.append(body) or True,lambda _:None)
    assert sent[0]['events'][0]['state']=='resolved'
    assert len(sent[0]['events'])==1


def test_public_reader_rejects_deeply_nested_json(tmp_path):
    p=tmp_path/'public.json';p.write_text('{"x":'+('['*2000)+(']'*2000)+'}')
    assert a.read_report(p,100)['state']=='unavailable'


def test_install_does_not_expose_existing_private_config_directory():
    script=(Path(worker.__file__).parent/'enable-alerts.sh').read_text()
    assert '/etc/dnf-gm-alerts.json' in script
    assert 'chmod 755 /etc/dnf-gm' not in script
    assert 'usermod' not in script
