import time
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient
from dnfgm.app import create_app
from dnfgm.config import Settings
from dnfgm.task_probe import PROBE_PATH, FIELDS
from test_combined_rewards import enable
from test_reward_jobs import job_preview,start
from dnfgm import alerts
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'deploy'))
import alert_worker
TOKEN='a'*64


@pytest.fixture
def probe_env():
    settings=Settings(secret='s'*64,db_password='fixture',origins=('http://testserver',),task_probe_token=TOKEN)
    app=create_app(settings);calls=[]
    def read():
        calls.append(1)
        return {'state':'attention','checked_at':int(time.time()),'issues':[{'id':'private-task','target_name':'private-player'}],'truncated':False}
    app.state.task_health.read=read
    c=TestClient(app,client=('127.0.0.1',12345),raise_server_exceptions=False)
    yield c,settings,app,calls
    c.close()


def auth():return {'Authorization':'Bearer '+TOKEN}


def test_private_read_is_aggregate_only_and_not_an_admin_session(probe_env):
    c,s,app,calls=probe_env
    r=c.get(PROBE_PATH,headers=auth())
    assert r.status_code==200 and set(r.json())==FIELDS and r.json()['issue_count']==1
    assert 'private' not in r.text and TOKEN not in r.text and calls==[1]
    assert c.get('/dnf-gm/api/v1/auth/me',headers=auth()).status_code==401
    assert c.get('/dnf-gm/api/v1/task-health',headers=auth()).status_code==401
    assert r.headers['cache-control']=='no-store'


@pytest.mark.parametrize('headers',[{}, {'Authorization':'Bearer wrong'}, {'Authorization':TOKEN},
    {**auth(),'Origin':'http://testserver'},{**auth(),'X-Forwarded-For':'127.0.0.1'},
    {**auth(),'Forwarded':'for=127.0.0.1'}])
def test_no_browser_proxy_or_invalid_token_query(probe_env,headers):
    c,s,app,calls=probe_env
    assert c.get(PROBE_PATH,headers=headers).status_code==404
    assert not calls


def test_disabled_endpoint_queries_and_remote_peer_cannot_bypass(probe_env):
    c,s,app,calls=probe_env
    assert c.get(PROBE_PATH+'?token='+TOKEN,headers=auth()).status_code==404
    remote=TestClient(app,client=('203.0.113.4',12345))
    try:assert remote.get(PROBE_PATH,headers=auth()).status_code==404
    finally:remote.close()
    s.task_probe_token=''
    assert c.get(PROBE_PATH,headers=auth()).status_code==404 and not calls


def test_probe_global_limit_bounds_database_reads(probe_env):
    c,s,app,calls=probe_env
    for _ in range(30):assert c.get(PROBE_PATH,headers=auth()).status_code==200
    assert c.get(PROBE_PATH,headers=auth()).status_code==429
    assert len(calls)==30


def test_worker_can_observe_real_task_api_without_browser_or_new_db_pool(env,tmp_path):
    c,s,db,app=env;enable(s);s.task_probe_token=TOKEN
    job=job_preview(c);assert start(c,job).status_code==200
    probe=TestClient(app,client=('127.0.0.1',4321))
    root=tmp_path/'observer';root.mkdir();status=tmp_path/'status'
    cfg={'health_host':'testserver','thresholds':{'memory':256,'swap':1536,'disk':2},'task_probe_token':TOKEN,
         'task_health_enabled':True,'webhook_url':'https://example.com','webhook_token':''}
    now=[int(time.time())];sent=[]
    h=app.state.task_health;h.clock=lambda:float(now[0]);h.wall=lambda:now[0]
    def tick():
        t=now[0];status.write_text(__import__('json').dumps({'collected_at':t,'core_ok':True,'mem_available_mib':512,'swap_free_mib':4096,'disk_free_gib':8}))
        return alert_worker.run_once(cfg,root=root,status_path=status,clock=lambda:t,probe=lambda _:True,
                task_probe=lambda _:probe.get(PROBE_PATH,headers=auth()).json(),send=lambda _,body:sent.append(body) or True)
    try:
        tick();now[0]+=30;tick()
        assert [(e['key'],e['state']) for body in sent for e in body['events']]==[('tasks','firing')]
        # Real isolated reward completion. No browser is polling the task health.
        app.state.reward_jobs.step();app.state.reward_jobs.step()
        now[0]+=30;tick();now[0]+=30;tick()
        assert [(e['key'],e['state']) for body in sent for e in body['events']]==[('tasks','firing'),('tasks','resolved')]
        assert job['id'] not in str(sent) and TOKEN not in str(sent)
        assert app.state.reward_jobs.db is db and h.db is db
        assert alerts.read_report(root/'public.json',now[0])['state']=='ok'
    finally:probe.close()


def test_continuous_observer_detects_stall_and_resolves_on_real_progress(env,tmp_path):
    from test_reward_jobs import extra_role
    c,s,db,app=env;enable(s);s.task_probe_token=TOKEN;extra_role(db)
    job=job_preview(c,targets={'mode':'selected','charac_nos':[900001,900003]});assert start(c,job).status_code==200
    probe=TestClient(app,client=('127.0.0.1',4321))
    root=tmp_path/'observer';root.mkdir();status=tmp_path/'status'
    cfg={'health_host':'testserver','thresholds':{'memory':256,'swap':1536,'disk':2},'task_probe_token':TOKEN,
         'task_health_enabled':True,'webhook_url':'https://example.com','webhook_token':''}
    now=[int(time.time())];sent=[];h=app.state.task_health
    h.clock=lambda:float(now[0]);h.wall=lambda:now[0];h.alive=lambda:True
    def tick():
        t=now[0];h.pulse.call('rewards',lambda:False)
        status.write_text(__import__('json').dumps({'collected_at':t,'core_ok':True,'mem_available_mib':512,'swap_free_mib':4096,'disk_free_gib':8}))
        return alert_worker.run_once(cfg,root=root,status_path=status,clock=lambda:t,probe=lambda _:True,
                task_probe=lambda _:probe.get(PROBE_PATH,headers=auth()).json(),send=lambda _,body:sent.append(body) or True)
    try:
        for _ in range(6):tick();now[0]+=30
        assert [(e['key'],e['state']) for body in sent for e in body['events']]==[('tasks','firing')]
        assert app.state.reward_jobs.detail(job['id'])['counts']=={'pending':2}
        assert app.state.reward_jobs.step()
        tick();now[0]+=30;tick()
        assert [(e['key'],e['state']) for body in sent for e in body['events']]==[('tasks','firing'),('tasks','resolved')]
        assert app.state.reward_jobs.detail(job['id'])['counts']=={'committed':1,'pending':1}
    finally:probe.close()
