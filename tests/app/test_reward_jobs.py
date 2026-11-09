"""Durable batch API, target freezing, de-duplication and actual MySQL effects."""
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_mail_gold import P, rows
from test_combined_rewards import enable, read, write


def extra_role(db):
    write(db,"INSERT INTO taiwan_cain.charac_info(m_id,charac_no,charac_name,element_resist,spec_property,VIP) VALUES(900001,900003,'Second','','','0')")


def job_preview(c,**kw):
    data={'targets':{'mode':'selected','charac_nos':[900001]},'reward':{'currency_rewards':{'cera':100},'gold':123},'reason':'isolated batch test'}
    data.update(kw)
    r=c.post(P+'/reward-jobs/preview',json=data)
    assert r.status_code==200,r.text
    return r.json()


def start(c,job,**kw):
    data={k:job[k] for k in ('fingerprint','target_count','account_count')}
    data['idempotency_key']='batch-start-'+job['id'];data.update(kw)
    return c.post(P+'/reward-jobs/'+job['id']+'/start',json=data)


def detail(c,job):return c.get(P+'/reward-jobs/'+job['id']).json()
def control(c,job,action):return c.post(P+'/reward-jobs/'+job['id']+'/control',json={'action':action})


def test_once_per_account_and_every_role_mail(env):
    c,s,db,app=env;enable(s);extra_role(db)
    job=job_preview(c,targets={'mode':'selected','charac_nos':[900003,900001,900001]})
    assert job['target_count']==2 and job['account_count']==1
    assert job['preview']['duplicates_removed']==1 and job['preview']['currency_totals']=={'cera':'100'}
    assert start(c,job).status_code==200
    for _ in range(3):assert app.state.reward_jobs.step()
    assert detail(c,job)['status']=='finished'
    assert detail(c,job)['counts']=={'committed':2}
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100
    assert [r['gold'] for r in rows(db)]==[123,123]
    assert len(read(db,'SELECT * FROM dnf_gm.reward_account_credits'))==1
    assert start(c,job).status_code==200
    assert not app.state.reward_jobs.step()


def test_per_character_repeat_requires_explicit_ack(env):
    c,s,db,app=env;enable(s);extra_role(db)
    job=job_preview(c,targets={'mode':'selected','charac_nos':[900001,900003]},account_reward_mode='per_character')
    assert start(c,job).status_code==422
    assert start(c,job,acknowledge_repeat=True).status_code==200
    for _ in range(3):app.state.reward_jobs.step()
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1200


def test_all_server_freeze_and_full_test_uid_gate(env):
    c,s,db,app=env;enable(s)
    job=job_preview(c,targets={'mode':'all'})
    assert start(c,job).status_code==422
    assert start(c,job,all_server_confirmation='全服发放').status_code==403
    assert detail(c,job)['status']=='preview'
    assert not rows(db)
    extra_role(db)
    assert detail(c,job)['target_count']==2
    assert len(c.get(P+'/reward-jobs/'+job['id']+'/targets').json()['items'])==2


def test_online_selection_and_pause_resume_cancel(env):
    c,s,db,app=env;enable(s);extra_role(db)
    job=job_preview(c,targets={'mode':'online'})
    assert job['target_count']==2
    assert start(c,job).status_code==200
    assert control(c,job,'pause').status_code==200
    assert not app.state.reward_jobs.step()
    assert control(c,job,'resume').status_code==200
    app.state.reward_jobs.step()
    assert control(c,job,'cancel').status_code==200
    assert not app.state.reward_jobs.step()
    assert len(rows(db))==1
    assert control(c,job,'resume').status_code==409


def test_worker_disabled_no_silent_running(env):
    c,s,db,app=env
    job=job_preview(c)
    assert start(c,job).status_code==409
    assert detail(c,job)['status']=='preview'


def test_failure_is_atomic_and_requires_manual_retry(env,monkeypatch):
    c,s,db,app=env;enable(s)
    job=job_preview(c);assert start(c,job).status_code==200
    original=app.state.service.apply_mail
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('fault after postal insertion')
    monkeypatch.setattr(app.state.service,'apply_mail',fail)
    assert app.state.reward_jobs.step()
    assert detail(c,job)['status']=='paused' and detail(c,job)['counts']=={'failed':1}
    assert not rows(db) and not read(db,'SELECT * FROM dnf_gm.reward_account_credits')
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    monkeypatch.setattr(app.state.service,'apply_mail',original)
    assert not app.state.reward_jobs.step()
    assert control(c,job,'retry-failed').status_code==200
    assert not app.state.reward_jobs.step()
    assert control(c,job,'resume').status_code==200
    assert app.state.reward_jobs.step()
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100
    assert len(rows(db))==1


def test_abandoned_execution_never_automatically_replays(env):
    c,s,db,app=env;enable(s)
    job=job_preview(c);assert start(c,job).status_code==200
    write(db,"UPDATE dnf_gm.reward_targets SET status='executing' WHERE job_id=%s",(job['id'],))
    assert app.state.reward_jobs.step()
    assert detail(c,job)['status']=='paused' and detail(c,job)['counts']=={'failed':1}
    assert not app.state.reward_jobs.step() and not rows(db)


def test_two_workers_serialize_game_mutations(env):
    c,s,db,app=env;enable(s);extra_role(db)
    job=job_preview(c,targets={'mode':'online'});assert start(c,job).status_code==200
    with ThreadPoolExecutor(2) as executor:
        list(executor.map(lambda _:app.state.reward_jobs.step(),range(2)))
    for _ in range(3):app.state.reward_jobs.step()
    assert detail(c,job)['counts']=={'committed':2}
    assert len(rows(db))==2
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100


def test_target_identity_changed_pauses_without_write(env):
    c,s,db,app=env;enable(s)
    job=job_preview(c);assert start(c,job).status_code==200
    write(db,"UPDATE taiwan_cain.charac_info SET charac_name='renamed' WHERE charac_no=900001")
    app.state.reward_jobs.step()
    assert detail(c,job)['counts']=={'failed':1} and not rows(db)


@pytest.mark.parametrize('targets',[{'mode':'filtered'},{'mode':'selected','charac_nos':[900001,999999]},{'mode':'all','uid':900001},{'mode':'selected','charac_nos':[-1]}])
def test_invalid_selection_has_no_partial_job(env,targets):
    c,s,db,app=env
    r=c.post(P+'/reward-jobs/preview',json={'targets':targets,'reward':{'gold':1},'reason':'test'})
    assert r.status_code==422,r.text
    assert not read(db,'SELECT * FROM dnf_gm.reward_jobs') and not read(db,'SELECT * FROM dnf_gm.reward_targets')


@pytest.mark.parametrize('commit_number,committed',[(1,True),(2,True),(2,False)])
def test_lost_commit_reply_does_not_duplicate(env,commit_number,committed):
    from contextlib import contextmanager
    from dnfgm.reward_jobs import RewardJobs
    c,s,db,app=env;enable(s)
    job=job_preview(c);assert start(c,job).status_code==200
    class Connection:
        def __init__(self,con):self.con=con;self.count=0
        def __getattr__(self,name):return getattr(self.con,name)
        def commit(self):
            self.count+=1
            if self.count==commit_number:
                if committed:self.con.commit()
                raise OSError('simulated lost commit response')
            self.con.commit()
    class FaultDB:
        @contextmanager
        def connect(self):
            with db.connect() as con:yield Connection(con)
    jobs=RewardJobs(FaultDB(),s,app.state.service)
    if commit_number==1:
        with pytest.raises(OSError):jobs.step()
    else:
        # Failure recording may itself lose its commit reply; the persisted target
        # remains authoritative regardless of the worker exception.
        try:jobs.step()
        except OSError:pass
    app.state.reward_jobs.step()
    if detail(c,job)['counts'].get('uncertain'):
        assert control(c,job,'reconcile').status_code==200
    if commit_number==2 and committed:
        assert detail(c,job)['counts']=={'committed':1}
        assert len(rows(db))==1
        assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100
    else:
        assert detail(c,job)['counts']=={'failed':1}
        assert not rows(db)
        assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    app.state.reward_jobs.step()
    assert len(rows(db))==(1 if commit_number==2 and committed else 0)


def test_expired_preview_idempotency_conflict_and_other_session(env):
    from dnfgm.security import COOKIE,digest
    from fastapi import HTTPException
    c,s,db,app=env;enable(s)
    first=job_preview(c);second=job_preview(c)
    assert start(c,first,idempotency_key='same-batch-key-1234').status_code==200
    assert start(c,second,idempotency_key='same-batch-key-1234').status_code==409
    assert start(c,first,idempotency_key='different-batch-key').status_code==409
    with pytest.raises(HTTPException) as e:
        app.state.reward_jobs.start('other-session',second['id'],{**second,'idempotency_key':'batch-other-session'})
    assert e.value.status_code==404
    write(db,'UPDATE dnf_gm.reward_jobs SET expires_at=0 WHERE id=%s',(second['id'],))
    assert start(c,second).status_code==409


def test_templates_currency_only_dedup_and_changed_version(env):
    c,s,db,app=env;enable(s);extra_role(db)
    data={'name':'currency only','expected_version':0,'currency_rewards':{'cera':100}}
    tid=c.post(P+'/gift-templates',json=data).json()['id']
    job=job_preview(c,targets={'mode':'online'},reward={'template_id':tid,'template_version':1})
    assert start(c,job).status_code==200
    for _ in range(3):app.state.reward_jobs.step()
    assert detail(c,job)['counts']=={'committed':2}
    assert not rows(db)
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100
    job=job_preview(c,reward={'template_id':tid,'template_version':1})
    assert start(c,job).status_code==200
    assert c.put(P+f'/gift-templates/{tid}',json={**data,'expected_version':1,'currency_rewards':{'cera':200}}).status_code==200
    app.state.reward_jobs.step()
    assert detail(c,job)['counts']=={'failed':1}
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100


def test_target_pagination_and_filter_query(env):
    c,s,db,app=env
    with db.connect() as conn,conn.cursor() as q:
        for i in range(260):
            q.execute("INSERT INTO taiwan_cain.charac_info(m_id,charac_no,charac_name,lev,element_resist,spec_property,VIP) VALUES(900001,%s,%s,50,'','','0')",(901000+i,'role'+str(i)))
        conn.commit()
    job=job_preview(c,targets={'mode':'filtered','uid':900001,'min_level':50})
    assert job['target_count']==260
    cursor=0;roles=[]
    while True:
        page=c.get(P+'/reward-jobs/'+job['id']+'/targets',params={'after':cursor}).json()
        roles.extend(r['charac_no'] for r in page['items']);cursor=page['next_after']
        if cursor is None:break
    assert len(roles)==len(set(roles))==260
    assert c.get(P+'/reward-jobs').json()['items'][0]['id']==job['id']


def test_reward_routes_auth_csrf_and_recent_auth(env):
    c,s,db,app=env
    job=job_preview(c)
    csrf=c.headers.pop('X-CSRF-Token')
    assert start(c,job).status_code==403
    c.headers['X-CSRF-Token']=csrf
    write(db,'UPDATE dnf_gm.sessions SET authenticated_at=0')
    assert start(c,job).status_code==403
    c.cookies.clear()
    assert c.get(P+'/reward-jobs').status_code==401
    assert c.get(P+'/reward-jobs/'+job['id']).status_code==401


def test_fresh_bootstrap_and_actual_least_privilege_worker(env):
    import importlib.util
    import os
    from pathlib import Path
    import pymysql
    from fastapi.testclient import TestClient
    from dnfgm.db import Database
    from dnfgm.app import create_app
    from dnfgm.security import PASSWORDS
    c,s,rootdb,app=env;enable(s)
    spec=importlib.util.spec_from_file_location('job_grants',Path(__file__).resolve().parents[2]/'deploy/grants.py')
    grants=importlib.util.module_from_spec(spec);spec.loader.exec_module(grants)
    sql=grants.bootstrap_sql({'db_user':'job_minimal','db_password':'isolated-password-12345','db_account_host':'localhost'},PASSWORDS.hash('fixture-admin-password'))
    with rootdb.connect() as conn,conn.cursor() as q:
        q.execute('DROP DATABASE dnf_gm')
        q.execute("DROP USER IF EXISTS 'job_minimal'@'localhost'")
        for statement in sql.split(';'):
            if statement.strip():q.execute(statement)
        conn.commit()
    def factory():
        return pymysql.connect(unix_socket=os.environ['DNF_GM_M0_SOCKET'],user='job_minimal',password='isolated-password-12345',charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    limited_db=Database(s,factory);limited_app=create_app(s,limited_db)
    # No lifespan context: execute deterministic worker steps, not a background timer.
    limited=TestClient(limited_app,raise_server_exceptions=True)
    try:
        limited.headers['Origin']='http://testserver'
        r=limited.post(P+'/auth/login',json={'username':'admin','password':'fixture-admin-password'})
        assert r.status_code==200,r.text
        limited.headers['X-CSRF-Token']=r.json()['csrf']
        assert limited.get(P+'/health').status_code==200
        assert limited.get(P+'/catalog/collections').status_code==200
        job=job_preview(limited);assert start(limited,job).status_code==200
        assert limited_app.state.reward_jobs.step()
        assert detail(limited,job)['counts']=={'committed':1}
        targets=limited.get(P+'/reward-jobs/'+job['id']+'/targets').json()['items']
        result=limited.get(P+'/operations/'+targets[0]['operation_id']).json()
        assert result['result']['currency_rewards']['cera']['after']==1100
        assert len(rows(rootdb))==1
        # lev belongs to the installed level-maintenance feature; base profession
        # and creation dates must still be read-only to the combined app account.
        for sql in ('DELETE FROM dnf_gm.reward_targets','DROP TABLE dnf_gm.reward_jobs',"SELECT password FROM d_taiwan.accounts",'UPDATE taiwan_cain.charac_info SET job=1',"UPDATE taiwan_cain.charac_info SET create_time='2026-11-09 00:00:00'"):
            with pytest.raises(pymysql.err.OperationalError):
                read(limited_db,sql)
                pytest.fail('Forbidden SQL unexpectedly succeeded: '+sql)
    finally:
        limited.close()
        write(rootdb,"DROP USER 'job_minimal'@'localhost'")


def test_concurrent_pause_cannot_dispatch_after_acknowledged_pause(env,monkeypatch):
    from threading import Event
    c,s,db,app=env;enable(s)
    job=job_preview(c);assert start(c,job).status_code==200
    dispatched=Event();resume=Event();original=app.state.reward_jobs.execute_target
    def wait_before_game(*args):
        dispatched.set();assert resume.wait(5)
        return original(*args)
    monkeypatch.setattr(app.state.reward_jobs,'execute_target',wait_before_game)
    with ThreadPoolExecutor(1) as executor:
        running=executor.submit(app.state.reward_jobs.step)
        assert dispatched.wait(5)
        assert control(c,job,'pause').status_code==200
        resume.set();assert running.result(timeout=5)
    assert detail(c,job)['status']=='paused'
    assert detail(c,job)['counts']=={'pending':1}
    assert not rows(db)


def test_inconsistent_recovery_quarantines_target_without_starving_other_jobs(env):
    c,s,db,app=env;enable(s)
    old=job_preview(c);assert start(c,old).status_code==200
    target=c.get(P+'/reward-jobs/'+old['id']+'/targets').json()['items'][0]
    write(db,"UPDATE dnf_gm.reward_targets SET status='executing' WHERE job_id=%s",(old['id'],))
    write(db,"INSERT INTO dnf_gm.audit(operation_id,actor,action,reason,request_json,result_json) VALUES(%s,'owner','reward','inconsistent fixture','{}','{}')",(target['operation_id'],))
    assert app.state.reward_jobs.step()
    assert detail(c,old)['status']=='paused' and detail(c,old)['counts']=={'uncertain':1}
    other=job_preview(c);assert start(c,other).status_code==200
    assert app.state.reward_jobs.step()
    assert detail(c,other)['counts']=={'committed':1}
    assert control(c,old,'reconcile').status_code==409
    assert detail(c,old)['counts']=={'uncertain':1}
    assert len(rows(db))==1


def test_real_lifespan_worker_runs_persisted_job_and_stops(env,monkeypatch):
    import time
    import dnfgm.app as application
    from fastapi.testclient import TestClient
    c,s,db,app=env;enable(s)
    workers=[];original=application.JobWorker
    def capture(*args):
        worker=original(*args);workers.append(worker);return worker
    monkeypatch.setattr(application,'JobWorker',capture)
    running_app=application.create_app(s,db)
    with TestClient(running_app,raise_server_exceptions=True) as live:
        live.headers['Origin']='http://testserver'
        auth=live.post(P+'/auth/login',json={'username':'admin','password':'fixture-password-no-production'})
        assert auth.status_code==200
        live.headers['X-CSRF-Token']=auth.json()['csrf']
        job=job_preview(live);assert start(live,job).status_code==200
        deadline=time.monotonic()+8
        while detail(live,job)['status']!='finished' and time.monotonic()<deadline:time.sleep(.15)
        assert detail(live,job)['status']=='finished'
        assert len(rows(db))==1 and workers[0].thread.is_alive()
    assert not workers[0].thread.is_alive()
