"""Synthetic probe/config/observer tests; no production or real notifications."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from dnfgm.config import Settings
from dnfgm.task_probe import PROBE_PATH, summary, validate_summary
from dnfgm import alerts
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
import alert_worker as worker
import configure_task_probe as setup

TOKEN='a'*64
CFG={'health_host':'testserver','thresholds':{'memory':256,'swap':1536,'disk':2},
     'webhook_url':'','webhook_token':'','task_health_enabled':True,'task_probe_token':TOKEN}


def sample(t=100,state='attention',truncated=False):
    return {'schema':1,'checked_at':t,'state':state,'issue_count':1 if state=='attention' else 0,'truncated':truncated}


def observation(t,state='attention',**kwargs):
    return alerts.observations({'collected_at':t,'core_ok':True,'mem_available_mib':512,'swap_free_mib':4096,'disk_free_gib':8},True,t,CFG['thresholds'],tasks=sample(t,state,**kwargs))


def test_projection_never_includes_player_task_payload_or_errors():
    projected=summary({'state':'attention','checked_at':100,'issues':[{'id':'private','name':'player'}],
                       'workers':{'private':'details'},'reason':'secret'})
    assert projected==sample()
    assert 'private' not in json.dumps(projected)


@pytest.mark.parametrize('patch',[{'schema':True},{'schema':2},{'checked_at':float('nan')},{'checked_at':101},
    {'checked_at':39},{'state':'healthy'},{'issue_count':-1},{'issue_count':True},{'issue_count':501},
    {'issue_count':0},{'truncated':0},{'state':'clear'},{'secret':'x'}])
def test_reject_invalid_stale_or_inconsistent_evidence(patch):
    with pytest.raises(ValueError):validate_summary({**sample(),**patch},100)


def test_unknown_and_observing_do_not_resolve_but_advancement_can():
    s=alerts.new_state()
    for t in (100,130):alerts.observe(s,observation(t),t)
    assert s['rules']['tasks']['active']
    for t in (160,190):alerts.observe(s,observation(t,'observing'),t)
    assert s['rules']['tasks']['active']
    for t in (220,250):alerts.observe(s,observation(t,'unknown'),t)
    assert s['rules']['tasks']['active'] and s['rules']['task_probe']['active']
    for t in (280,310):alerts.observe(s,observation(t,'clear'),t)
    assert not s['rules']['tasks']['active'] and not s['rules']['task_probe']['active']
    assert [(e['key'],e['state']) for e in s['history']]==[('tasks','firing'),('task_probe','firing'),('tasks','resolved'),('task_probe','resolved')]


def test_truncated_attention_reports_both_fault_and_incomplete_check():
    s=alerts.new_state()
    for t in (100,130):alerts.observe(s,observation(t,truncated=True),t)
    assert s['rules']['tasks']['active'] and s['rules']['task_probe']['active']


def test_stale_sample_cannot_recover_and_disabled_rules_keep_history_without_delivery():
    s=alerts.new_state()
    for t in (100,130):alerts.observe(s,observation(t),t)
    for t in (200,230):
        alerts.observe(s,alerts.observations(None,True,t,CFG['thresholds'],tasks=sample(100,'clear')),t)
    assert s['rules']['tasks']['active']
    history=copy.deepcopy(s['history'])
    alerts.observe(s,alerts.observations(None,True,260,CFG['thresholds']),260)
    assert s['rules']['tasks']['observed']=='disabled' and s['history']==history
    assert not any(e['key'] in ('tasks','task_probe') for e in alerts.pending(s))


def test_old_eight_rule_state_upgrades_without_resetting_event_ids():
    s=alerts.new_state()
    for t in (100,130):alerts.observe(s,observation(t),t)
    for key in ('tasks','task_probe'):s['rules'].pop(key)
    s['history']=[e for e in s['history'] if e['key'] not in ('tasks','task_probe')]
    original=copy.deepcopy(s['history'])
    alerts.observe(s,observation(160),160)
    assert len(s['rules'])==10 and s['history']==original


@pytest.mark.parametrize('patch',[{'task_health_enabled':1},{'task_probe_token':'bad'},
    {'task_probe_token':''},{'task_probe_token':None},{'task_probe_token':TOKEN.upper()},
    {'webhook_url':'https://example.com','webhook_token':TOKEN}])
def test_observer_config_rejects_invalid_and_reused_tokens(patch):
    with pytest.raises(ValueError):worker.validate_config({**CFG,**patch})


@pytest.mark.parametrize('token',[None,'abc',123,'A'*64,'a'*63])
def test_app_config_rejects_invalid_probe_tokens(token):
    with pytest.raises(ValueError):Settings(db_password='fixture',secret='s'*64,task_probe_token=token).check()


def test_dedicated_app_secret():
    with pytest.raises(ValueError):Settings(db_password='fixture',secret=TOKEN,task_probe_token=TOKEN).check()
    assert Settings(db_password='fixture',secret='s'*64).check().task_probe_token==''


def test_fixed_probe_no_redirect_no_proxy_auth_header_and_read_bound(monkeypatch):
    calls=[]
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):assert n==4097;return json.dumps(sample()).encode()
    class Opener:
        def open(self,req,timeout):calls.append((req,timeout));return Response()
    handlers=[]
    monkeypatch.setattr(worker,'build_opener',lambda *args:handlers.extend(args) or Opener())
    assert worker.task_health(CFG)==sample()
    req,timeout=calls[0]
    assert req.full_url=='http://127.0.0.1:8765'+PROBE_PATH and req.get_method()=='GET'
    assert req.get_header('Authorization')=='Bearer '+TOKEN and timeout==3
    assert isinstance(handlers[0],worker.ProxyHandler) and handlers[0].proxies=={}
    assert isinstance(handlers[1],worker.NoRedirect)
    assert TOKEN not in req.full_url


@pytest.mark.parametrize('body',[b'x'*4097,b'not json'])
def test_probe_transport_failure_is_unknown_without_secret(monkeypatch,body):
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return body
    class Opener:
        def open(self,*args,**kw):return Response()
    monkeypatch.setattr(worker,'build_opener',lambda *args:Opener())
    assert worker.task_health(CFG)=={'state':'unknown'}


def test_worker_independent_persistence_and_optional_flag(tmp_path):
    state=tmp_path/'state';state.mkdir();status=tmp_path/'status';sent=[]
    def run(t,enabled=True):
        status.write_text(json.dumps({'collected_at':t,'core_ok':True,'mem_available_mib':512,'swap_free_mib':4096,'disk_free_gib':8}))
        return worker.run_once({**CFG,'task_health_enabled':enabled,'webhook_url':'https://example.com'},root=state,status_path=status,
            clock=lambda:t,probe=lambda _:True,task_probe=lambda _:sample(t),send=lambda _,body:sent.append(body) or True)
    run(100);run(130);run(160)
    assert len(sent)==1 and sent[0]['events'][0]['key']=='tasks'
    assert TOKEN not in json.dumps(sent) and 'issue_count' not in json.dumps(sent)
    run(190,False)
    report=alerts.read_report(state/'public.json',190)
    assert next(r for r in report['rules'] if r['key']=='tasks')['observed']=='disabled'
    assert len(sent)==1


def private_files(tmp_path):
    app=tmp_path/'app.json';obs=tmp_path/'observer.json'
    app.write_text(json.dumps({'secret':'s'*64,'db_password':'fixture','writes':[]}));app.chmod(0o600)
    obs.write_text(json.dumps({**CFG,'task_health_enabled':False,'task_probe_token':''}));obs.chmod(0o640)
    return app,obs


def configure(mode,app,obs,**kw):
    return setup.configure(mode,app_path=app,observer_path=obs,app_owners=(os.getuid(),),observer_owners=(os.getuid(),),**kw)


def test_prepare_enable_disable_preserves_identity_permissions_and_secrets(tmp_path):
    app,obs=private_files(tmp_path)
    result=configure('prepare',app,obs)
    a=json.loads(app.read_text());b=json.loads(obs.read_text());token=a['task_probe_token']
    assert len(token)==64 and token==b['task_probe_token']
    assert a['secret']=='s'*64 and a['db_password']=='fixture' and not b['task_health_enabled']
    assert token not in json.dumps(result)
    content=(app.read_bytes(),obs.read_bytes());configure('prepare',app,obs)
    assert content==(app.read_bytes(),obs.read_bytes())
    configure('enable',app,obs,probe=lambda _:sample(time.time(),'clear'))
    assert json.loads(obs.read_text())['task_health_enabled'] is True
    configure('disable',app,obs)
    assert json.loads(obs.read_text())['task_probe_token']==token
    assert app.stat().st_mode&0o777==0o600 and obs.stat().st_mode&0o777==0o640


def test_interrupted_prepare_reuses_already_saved_token(tmp_path,monkeypatch):
    app,obs=private_files(tmp_path);original=setup.replace_private
    def interrupted(path,*args,**kw):
        if path==obs:raise OSError('synthetic interrupted second file')
        original(path,*args,**kw)
    monkeypatch.setattr(setup,'replace_private',interrupted)
    with pytest.raises(OSError):configure('prepare',app,obs)
    token=json.loads(app.read_text())['task_probe_token']
    monkeypatch.setattr(setup,'replace_private',original)
    configure('prepare',app,obs)
    assert json.loads(obs.read_text())['task_probe_token']==token


def test_mismatch_or_running_probe_unknown_does_not_enable(tmp_path):
    app,obs=private_files(tmp_path);configure('prepare',app,obs)
    before=(app.read_bytes(),obs.read_bytes())
    with pytest.raises(ValueError):configure('enable',app,obs,probe=lambda _:sample(time.time(),'unknown'))
    assert before==(app.read_bytes(),obs.read_bytes())
    cfg=json.loads(obs.read_text());cfg['task_probe_token']='b'*64;obs.write_text(json.dumps(cfg))
    before=(app.read_bytes(),obs.read_bytes())
    with pytest.raises(ValueError):configure('prepare',app,obs)
    assert before==(app.read_bytes(),obs.read_bytes())


def test_symlink_and_world_readable_config_rejected(tmp_path):
    app,obs=private_files(tmp_path);app.chmod(0o644)
    with pytest.raises(ValueError):configure('prepare',app,obs)
    app.chmod(0o600);link=tmp_path/'link';link.symlink_to(app)
    with pytest.raises(OSError):configure('prepare',link,obs)


def test_observer_import_no_database_libraries_and_no_new_service_power():
    result=subprocess.run([sys.executable,'-c',"import sys; sys.path.insert(0,'deploy'); import alert_worker; assert 'pymysql' not in sys.modules; assert 'fastapi' not in sys.modules"],capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    text=Path(setup.__file__).read_text()
    assert 'subprocess' not in text and 'systemctl' not in text
    nginx=(Path(worker.__file__).parent/'nginx.conf').read_text()
    assert 'location ^~ /dnf-gm/api/v1/internal/ { return 404; }' in nginx
