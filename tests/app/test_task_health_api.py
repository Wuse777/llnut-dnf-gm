import time
from test_combined_rewards import enable, read, write
from test_reward_jobs import job_preview, start, control, detail
from test_schedules import definition
P='/dnf-gm/api/v1'


def health(c):
    r=c.get(P+'/task-health');assert r.status_code==200,r.text
    return r.json()


def running(env):
    c,s,db,app=env;enable(s)
    j=job_preview(c);assert start(c,j).status_code==200
    return j


def codes(result):return [i['code'] for i in result['issues']]


def test_authenticated_empty_read_only_snapshot(env):
    c,s,db,app=env
    before=read(db,'SELECT COUNT(*) n FROM dnf_gm.audit')
    h=health(c);assert h['state']=='clear' and h['issues']==[]
    assert h['workers']['rewards']['state']=='disabled'
    assert read(db,'SELECT COUNT(*) n FROM dnf_gm.audit')==before
    c.cookies.clear();assert c.get(P+'/task-health').status_code==401


def test_pending_worker_and_cancelled_uncertain_reconcile_no_reissue(env):
    c,s,db,app=env;j=running(env)
    assert 'worker_stopped' in codes(health(c))
    write(db,"UPDATE dnf_gm.reward_targets SET status='uncertain' WHERE job_id=%s",(j['id'],))
    assert control(c,j,'cancel').status_code==200
    assert codes(health(c))==['uncertain']
    before=read(db,'SELECT cera FROM taiwan_billing.cash_cera')
    r=control(c,j,'reconcile');assert r.status_code==200,r.text
    assert r.json()['status']=='cancelled' and r.json()['counts']=={'failed':1}
    assert health(c)['state']=='clear'
    assert '任务已取消' in read(db,'SELECT error_message FROM dnf_gm.reward_targets WHERE job_id=%s',(j['id'],))[0]['error_message']
    assert control(c,j,'resume').status_code==409
    assert control(c,j,'retry-failed').status_code==409
    assert not app.state.reward_jobs.step()
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')==before


def test_cancelled_committed_result_can_be_reconciled(env):
    c,s,db,app=env;j=running(env)
    app.state.reward_jobs.step()
    write(db,"UPDATE dnf_gm.reward_targets SET status='uncertain' WHERE job_id=%s",(j['id'],))
    assert control(c,j,'cancel').status_code==200
    assert control(c,j,'reconcile').json()['counts']=={'committed':1}
    assert detail(c,j)['status']=='cancelled'
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100


def test_conflicting_cancelled_result_remains_uncertain(env):
    c,s,db,app=env;j=running(env)
    app.state.reward_jobs.step()
    write(db,"UPDATE dnf_gm.reward_targets SET status='uncertain' WHERE job_id=%s",(j['id'],))
    write(db,"DELETE FROM dnf_gm.audit WHERE action='reward'")
    control(c,j,'cancel')
    assert control(c,j,'reconcile').status_code==409
    assert detail(c,j)['status']=='cancelled'
    assert codes(health(c))==['uncertain']


def test_stale_execution_failed_and_manual_pause(env):
    c,s,db,app=env;j=running(env)
    control(c,j,'pause');assert health(c)['state']=='clear'
    write(db,"UPDATE dnf_gm.reward_targets SET status='executing',last_attempt=%s WHERE job_id=%s",(int(time.time()),j['id']))
    assert health(c)['state']=='clear'
    write(db,"UPDATE dnf_gm.reward_targets SET last_attempt=0 WHERE job_id=%s",(j['id'],))
    assert codes(health(c))==['executing']
    write(db,"UPDATE dnf_gm.reward_targets SET status='failed' WHERE job_id=%s",(j['id'],))
    assert codes(health(c))==['failed']


def test_head_not_old_queued_jobs_is_observed(env):
    c,s,db,app=env;j=running(env);j2=job_preview(c);start(c,j2)
    h=app.state.task_health;now=[0.0];h.clock=lambda:now[0];h.alive=lambda:True
    h.pulse.call('rewards',lambda:None)
    assert health(c)['state']=='observing'
    now[0]=60;health(c);now[0]=120
    result=health(c)
    assert codes(result)==['no_progress']
    assert result['issues'][0]['id']==result['head_job_id']
    control(c,{'id':result['head_job_id']},'pause')
    assert health(c)['state']=='observing'
    now[0]=250
    assert health(c)['state']=='observing' # gap resets


def test_bounded_truncation_does_not_claim_complete(env):
    c,s,db,app=env;j=running(env);control(c,j,'cancel')
    with db.connect() as conn,conn.cursor() as q:
        for n in range(2,53):
            q.execute("INSERT INTO dnf_gm.reward_targets(job_id,ordinal,target_uid,charac_no,target_json,operation_id,status) VALUES(%s,%s,900001,%s,'{}',%s,'failed')",(j['id'],n,n,f'{n:032x}'))
        conn.commit()
    result=health(c)
    assert result['state']=='unknown' and result['truncated'] and not result['issues']


def test_schedule_error_overdue_and_outstanding_run(env):
    c,s,db,app=env;enable(s);s.schedule_worker_enabled=True
    r=c.post(P+'/schedules/preview',json=definition(int(time.time())));assert r.status_code==200,r.text
    sid=r.json()['id']
    write(db,"UPDATE dnf_gm.schedules SET status='paused',last_error='' WHERE id=%s",(sid,))
    assert health(c)['state']=='clear'
    write(db,"UPDATE dnf_gm.schedules SET last_error='private message' WHERE id=%s",(sid,))
    assert codes(health(c))==['schedule_error']
    assert 'private message' not in str(health(c))
    write(db,"UPDATE dnf_gm.schedules SET status='active',last_error='',next_due=0 WHERE id=%s",(sid,))
    assert codes(health(c))==['overdue','worker_stopped']
    write(db,"UPDATE dnf_gm.schedules SET status='completed' WHERE id=%s",(sid,))
    write(db,"INSERT INTO dnf_gm.schedule_runs(id,schedule_id,due_at,started_at,checked_at,status) VALUES(%s,%s,0,0,0,'awaiting')",('a'*32,sid))
    assert codes(health(c))==['unreconciled','worker_stopped']
    write(db,"UPDATE dnf_gm.schedule_runs SET status='finished'")
    assert health(c)['state']=='clear'


def test_query_failure_clears_previous_evidence(env):
    c,s,db,app=env
    assert health(c)['state']=='clear'
    write(db,'DROP TABLE dnf_gm.schedule_runs')
    h=health(c)
    assert h['state']=='unknown' and h['reason']=='query_failed' and not h['issues']


def test_snapshot_rate_limit_and_no_public_task_details(env):
    c,s,db,app=env
    for _ in range(15):assert c.get(P+'/task-health').status_code==200
    assert c.get(P+'/task-health').status_code==429
    c.cookies.clear()
    response=c.get(P+'/health')
    assert response.status_code==200
    assert 'issues' not in response.json() and 'workers' not in response.json()
