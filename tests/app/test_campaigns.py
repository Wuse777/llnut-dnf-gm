"""Real isolated MySQL claims, rollback, concurrency, pinned gifts and schedules."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi import HTTPException
from test_mail_gold import P, confirm, rows
from test_combined_rewards import enable, read, write
from test_reward_jobs import extra_role, start


def create_campaign(env, dedupe='account', targets=None):
    client,settings,db,app=env;enable(settings)
    r=client.post(P+'/gift-templates',json={'name':'活动固定礼包','expected_version':0,
        'items':[{'id':990002,'quantity':2}],'gold':12,'currency_rewards':{'cera':10}})
    assert r.status_code==200,r.text
    template=r.json()['id']
    value={'name':'独立活动','status':'active','dedupe':dedupe,'expected_revision':0,
           'targets':targets or {'mode':'accounts','account_uids':[900001]},'template_id':template,
           'template_version':1,'reason':'隔离活动验收'}
    manager=app.state.service.campaigns
    op=manager.preview('c'*64,value)['operation_id']
    result=manager.confirm('c'*64,op,'campaign-'+op)
    assert manager.confirm('c'*64,op,'campaign-'+op)==result
    return manager.detail(result['campaign_id'])


def campaign_preview(env,campaign,charac_no=900001):
    client=env[0]
    r=client.post(P+'/operations/preview',json={'action':'reward','campaign_id':campaign['id'],
        'uid':900001,'charac_no':charac_no,'reason':'活动奖励'})
    assert r.status_code==200,r.text
    return r.json()['operation_id']


def test_manual_cross_batch_deduplication_skips_whole_gift(env):
    campaign=create_campaign(env);client,settings,db,app=env
    op=campaign_preview(env,campaign);assert confirm(client,op).status_code==200
    draft=campaign['job_draft'];draft['reason']='同活动批量'
    r=client.post(P+'/reward-jobs/preview',json=draft);assert r.status_code==200,r.text
    batch=r.json();assert start(client,batch).status_code==200
    for _ in range(3):app.state.reward_jobs.step()
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1010
    assert len(rows(db))==1 and rows(db)[0]['gold']==12
    assert len(read(db,'SELECT * FROM dnf_gm.campaign_claims'))==1
    operations=read(db,"SELECT result_json FROM dnf_gm.operations WHERE action='reward'")
    assert any(json.loads(r['result_json'] or '{}').get('state')=='campaign_duplicate_skipped' for r in operations)
    detail=app.state.service.campaigns.detail(campaign['id'])
    assert detail['claims']=={'subjects':1,'accounts':1}
    assert next(t for t in detail['totals'] if t['metric']=='cera')['amount']=='10'


@pytest.mark.parametrize('dedupe,expected',[('account',1),('character',2)])
def test_concurrent_manual_claims_have_one_atomic_subject(env,dedupe,expected):
    extra_role(env[2]);campaign=create_campaign(env,dedupe)
    first=campaign_preview(env,campaign);second=campaign_preview(env,campaign,900003)
    service=env[3].state.service
    session=read(env[2],'SELECT session_hash FROM dnf_gm.operations WHERE operation_id=%s',(first,))[0]['session_hash']
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(service.confirm,session,op,'claim-'+op) for op in (first,second)]
        results=[];failed=[]
        for op,future in zip((first,second),futures):
            try:results.append(future.result())
            except HTTPException as error:
                assert dedupe=='character' and error.status_code==409
                failed.append(op)
    if dedupe=='character':
        # Ordinary previews retain exact account balances. The losing role's
        # claim, links, mail and projection must all roll back before repreview.
        assert len(failed)==1
        assert len(read(env[2],'SELECT * FROM dnf_gm.campaign_claims'))==1
        assert len(rows(env[2]))==1
        assert not read(env[2],'SELECT * FROM dnf_gm.campaign_links WHERE reference_id=%s',(failed[0],))
        role=900001 if failed[0]==first else 900003
        retry=campaign_preview(env,campaign,role)
        results.append(service.confirm(session,retry,'claim-'+retry))
    else:
        assert not failed and sum(r['campaign']['skipped'] for r in results)==1
    assert sum(not r['campaign']['skipped'] for r in results)==expected
    assert len(read(env[2],'SELECT * FROM dnf_gm.campaign_claims'))==expected
    assert len(rows(env[2]))==expected
    assert read(env[2],'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000+expected*10


@pytest.mark.parametrize('dedupe,expected,same_character',[('account',1,False),('character',2,False),('character',1,True)])
def test_two_batch_transactions_share_atomic_campaign_claims(env,dedupe,expected,same_character):
    client,settings,db,app=env;extra_role(db)
    campaign=create_campaign(env,dedupe)
    jobs=[];targets=[]
    for _ in range(2):
        response=client.post(P+'/reward-jobs/preview',json=campaign['job_draft'])
        assert response.status_code==200,response.text
        job=response.json()
        assert start(client,job,acknowledge_repeat=True).status_code==200
        jobs.append(read(db,'SELECT * FROM dnf_gm.reward_jobs WHERE id=%s',(job['id'],))[0])
    # Dispatch targets from separate batches. This bypasses only the
    # executor's global scheduling lock, exercising the real target transactions.
    for job,role in zip(jobs,(900001,900001 if same_character else 900003)):
        write(db,"UPDATE dnf_gm.reward_targets SET status='executing' WHERE job_id=%s AND charac_no=%s",(job['id'],role))
        targets.append(read(db,'SELECT * FROM dnf_gm.reward_targets WHERE job_id=%s AND charac_no=%s',(job['id'],role))[0])
    barrier=Barrier(2)
    def execute(pair):
        job,target=pair
        with app.state.service.write_gate.writer() as lease,db.connect() as connection,connection.cursor() as cursor:
            barrier.wait(timeout=5)
            app.state.reward_jobs.execute_target(connection,cursor,job,target,lease)
    with ThreadPoolExecutor(2) as executor:
        list(executor.map(execute,zip(jobs,targets)))
    assert len(read(db,'SELECT * FROM dnf_gm.campaign_claims'))==expected
    assert len(rows(db))==expected
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000+expected*10
    assert len(read(db,"SELECT * FROM dnf_gm.campaign_links WHERE kind='reward'"))==2
    assert read(db,"SELECT SUM(amount) total FROM dnf_gm.economy_values WHERE metric='cera'")[0]['total']==expected*10
    assert not read(db,'SELECT * FROM dnf_gm.reward_account_credits')
    for _ in range(8):app.state.reward_jobs.step()
    assert all(app.state.reward_jobs.detail(job['id'])['status']=='finished' for job in jobs)
    final_expected=2 if dedupe=='character' else 1
    assert len(rows(db))==final_expected
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000+final_expected*10


@pytest.mark.parametrize('failure_stage',['mail','economy'])
def test_reward_failure_rolls_back_claim_mail_balances_and_statistics(env,monkeypatch,failure_stage):
    campaign=create_campaign(env);op=campaign_preview(env,campaign)
    owner=env[3].state.service if failure_stage=='mail' else env[3].state.service.economy
    method='apply_mail' if failure_stage=='mail' else 'record'
    original=getattr(owner,method)
    def fail(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('isolated failure after '+failure_stage)
    monkeypatch.setattr(owner,method,fail)
    assert confirm(env[0],op).status_code==500
    assert not read(env[2],'SELECT * FROM dnf_gm.campaign_claims') and not rows(env[2])
    assert read(env[2],'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    assert not read(env[2],"SELECT * FROM dnf_gm.campaign_links WHERE kind='reward'")
    assert not read(env[2],'SELECT * FROM dnf_gm.economy_values')
    assert not read(env[2],'SELECT * FROM dnf_gm.economy_operations')


def test_fixed_campaign_version_survives_template_new_version_and_pause_blocks_commit(env):
    campaign=create_campaign(env);client,settings,db,app=env
    tid=campaign['definition']['template_id']
    r=client.put(P+'/gift-templates/'+str(tid),json={'name':'礼包新版','expected_version':1,'currency_rewards':{'cera':999}})
    assert r.status_code==200,r.text
    op=campaign_preview(env,campaign)
    assert client.get(P+'/operations/'+op).json()['preview']['balances']['cera']['delta']==10
    manager=app.state.service.campaigns
    draft={**campaign['definition'],'campaign_id':campaign['id'],'expected_revision':campaign['revision'],'status':'paused','reason':'暂停'}
    preview=manager.preview('c'*64,draft);manager.confirm('c'*64,preview['operation_id'],'pause-'+preview['operation_id'])
    assert confirm(client,op).status_code==409
    assert not read(db,'SELECT * FROM dnf_gm.campaign_claims')


def test_campaign_schedule_uses_saved_audience_and_links_atomic_child(env):
    campaign=create_campaign(env);client,settings,db,app=env
    settings.schedule_worker_enabled=True
    now=int(time.time());app.state.schedules.clock=lambda:now
    r=client.post(P+'/schedules/preview',json={'title':'活动一期','kind':'reward','first_due':now+60,'reward_job':campaign['job_draft']})
    assert r.status_code==200,r.text
    plan=r.json();r=client.post(P+'/schedules/'+plan['id']+'/activate',json={'idempotency_key':'schedule-'+plan['id'],'fingerprint':plan['fingerprint']})
    assert r.status_code==200,r.text
    app.state.schedules.clock=lambda:now+60
    assert app.state.schedules.step()
    for _ in range(3):app.state.reward_jobs.step()
    links=read(db,'SELECT kind FROM dnf_gm.campaign_links WHERE campaign_id=%s',(campaign['id'],))
    assert {r['kind'] for r in links}=={'schedule','job','reward'}
    assert len(read(db,'SELECT * FROM dnf_gm.campaign_claims'))==1


def test_saved_tags_and_character_date_bounds_exclude_unknown_and_online_records(env):
    client,settings,db,app=env;extra_role(db)
    write(db,"UPDATE taiwan_cain.charac_info SET create_time='2026-10-01',last_play_time='2026-10-15' WHERE charac_no=900001")
    write(db,"UPDATE taiwan_login.login_account_3 SET login_status=0 WHERE m_id=900001")
    write(db,"INSERT INTO dnf_gm.player_profiles(uid,revision,notes,tags_json,updated_at) VALUES(900001,1,'','[\"回归\"]',1)")
    targets={'mode':'filtered','tags_all':['回归'],'created_from':'2026-10-01','created_to':'2026-10-01','inactive_before':'2026-11-01'}
    campaign=create_campaign(env,targets=targets)
    r=client.post(P+'/reward-jobs/preview',json=campaign['job_draft'])
    assert r.status_code==200,r.text
    assert r.json()['target_count']==1
    write(db,'UPDATE taiwan_login.login_account_3 SET login_status=1 WHERE m_id=900001')
    assert client.post(P+'/reward-jobs/preview',json=campaign['job_draft']).status_code==422


def test_target_status_and_error_filters_keep_keyset_and_global_counts(env):
    campaign=create_campaign(env);client,settings,db,app=env
    r=client.post(P+'/reward-jobs/preview',json=campaign['job_draft']);job=r.json()
    write(db,"UPDATE dnf_gm.reward_targets SET status='failed',error_type='FixtureError',error_message='isolated' WHERE job_id=%s",(job['id'],))
    result=app.state.reward_jobs.targets(job['id'],0,'failed','FixtureError')
    assert len(result['items'])==1 and result['counts']=={'failed':1}
    assert result['errors']==[{'error_type':'FixtureError','n':1}]
    assert app.state.reward_jobs.targets(job['id'],0,'pending')['items']==[]


@pytest.mark.parametrize('after_start',[False,True])
def test_changed_batch_definition_is_rejected_before_claim_or_reward(env,after_start):
    campaign=create_campaign(env);client,settings,db,app=env
    response=client.post(P+'/reward-jobs/preview',json=campaign['job_draft'])
    assert response.status_code==200,response.text
    job=response.json()
    if after_start:assert start(client,job).status_code==200
    request=read(db,'SELECT request_json FROM dnf_gm.reward_jobs WHERE id=%s',(job['id'],))[0]
    changed=json.loads(request['request_json']);changed['reward']['currency_rewards']={'cera':999}
    write(db,'UPDATE dnf_gm.reward_jobs SET request_json=%s WHERE id=%s',(json.dumps(changed),job['id']))
    if after_start:
        assert app.state.reward_jobs.step()
        assert app.state.reward_jobs.detail(job['id'])['counts']=={'failed':1}
    else:assert start(client,job).status_code==409
    assert not read(db,'SELECT * FROM dnf_gm.campaign_claims') and not rows(db)
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000


def test_changed_manual_reward_and_campaign_storage_cannot_credit(env):
    campaign=create_campaign(env);client,settings,db,app=env
    op=campaign_preview(env,campaign)
    request=json.loads(read(db,'SELECT request_json FROM dnf_gm.operations WHERE operation_id=%s',(op,))[0]['request_json'])
    request['currency_rewards']={'cera':999}
    write(db,'UPDATE dnf_gm.operations SET request_json=%s WHERE operation_id=%s',(json.dumps(request),op))
    assert confirm(client,op).status_code==409
    assert not read(db,'SELECT * FROM dnf_gm.campaign_claims') and not rows(db)
    write(db,'UPDATE dnf_gm.campaigns SET reward_json=%s WHERE id=%s',('{"gold":999}',campaign['id']))
    response=client.post(P+'/operations/preview',json={'action':'reward','campaign_id':campaign['id'],
        'uid':900001,'charac_no':900001,'reason':'核验冻结定义'})
    assert response.status_code==409,response.text
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000


def test_changed_catalog_after_campaign_activation_rejects_frozen_reward(env):
    import sqlite3
    campaign=create_campaign(env);client,settings,db,app=env
    with sqlite3.connect(settings.catalog_file) as index:
        index.execute("UPDATE items SET name='Changed material' WHERE id=990002")
    response=client.post(P+'/operations/preview',json={'action':'reward','campaign_id':campaign['id'],
        'uid':900001,'charac_no':900001,'reason':'核验物品索引'})
    assert response.status_code==409,response.text
    assert not read(db,'SELECT * FROM dnf_gm.campaign_claims') and not rows(db)


def test_campaign_cannot_attach_to_untracked_currency_action(env):
    campaign=create_campaign(env);client,settings,db,app=env
    response=client.post(P+'/operations/preview',json={'action':'currency','campaign_id':campaign['id'],
        'uid':900001,'charac_no':900001,'currency':'cera','delta':10,'reason':'活动必须整份发放'})
    assert response.status_code==422,response.text
    assert not read(db,'SELECT * FROM dnf_gm.campaign_claims')


def pending_campaign_change(env,campaign):
    client=env[0]
    response=client.post(P+'/campaigns/preview',json={**campaign['definition'],
        'campaign_id':campaign['id'],'expected_revision':campaign['revision'],'status':'paused','reason':'暂停活动'})
    assert response.status_code==200,response.text
    operation=response.json()['operation_id']
    session=read(env[2],'SELECT session_hash FROM dnf_gm.operations WHERE operation_id=%s',(operation,))[0]['session_hash']
    return operation,session


def login_again(client):
    response=client.post(P+'/auth/login',json={'username':'admin','password':'fixture-password-no-production'})
    assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=response.json()['csrf']


def test_lost_campaign_commit_can_be_read_by_original_id_after_new_login(env):
    from contextlib import contextmanager
    campaign=create_campaign(env);client,settings,db,app=env
    operation,session=pending_campaign_change(env,campaign)
    manager=app.state.service.campaigns
    class ReplyLostDatabase:
        @contextmanager
        def connect(self):
            with db.connect() as connection:
                class Proxy:
                    def __getattr__(self,key):return getattr(connection,key)
                    def commit(self):connection.commit();raise ConnectionError('isolated reply lost after real commit')
                yield Proxy()
    manager.db=ReplyLostDatabase()
    try:
        with pytest.raises(HTTPException) as error:
            manager.confirm(session,operation,'lost-campaign-'+operation)
        assert error.value.status_code==503
    finally:manager.db=db
    login_again(client)
    response=client.get(P+'/campaigns/operations/'+operation)
    assert response.status_code==200,response.text
    assert response.json()['status']=='committed' and response.json()['result']['campaign_id']==campaign['id']
    assert response.json()['same_session'] is False and response.json()['confirmable'] is False
    assert client.post(P+'/campaigns/operations/'+operation+'/confirm',json={'idempotency_key':'lost-campaign-'+operation}).status_code==404
    assert len(read(db,"SELECT * FROM dnf_gm.audit WHERE action='campaign' AND operation_id=%s",(operation,)))==1
    assert not rows(db) and not read(db,'SELECT * FROM dnf_gm.campaign_claims')


def test_new_login_cancels_only_old_preview_under_original_operation_lock(env):
    campaign=create_campaign(env);client,settings,db,app=env
    operation,session=pending_campaign_change(env,campaign)
    login_again(client)
    response=client.get(P+'/campaigns/operations/'+operation)
    assert response.status_code==200,response.text
    assert response.json()['status']=='preview' and response.json()['confirmable'] is False
    for _ in range(2):
        response=client.post(P+'/campaigns/operations/'+operation+'/cancel')
        assert response.status_code==200,response.text
        assert response.json()['status']=='cancelled'
    with pytest.raises(HTTPException) as error:
        app.state.service.campaigns.confirm(session,operation,'cancelled-campaign-'+operation)
    assert error.value.status_code==409
    assert app.state.service.campaigns.detail(campaign['id'])['status']=='active'
    cancelled=read(db,"SELECT * FROM dnf_gm.audit WHERE action='campaign-cancel'")
    assert len(cancelled)==1 and json.loads(cancelled[0]['request_json'])['operation_id']==operation
    # Cancellation of an already committed save returns that result unchanged.
    committed=read(db,"SELECT operation_id FROM dnf_gm.operations WHERE action='campaign' AND status='committed'")[0]['operation_id']
    response=client.post(P+'/campaigns/operations/'+committed+'/cancel')
    assert response.status_code==200 and response.json()['status']=='committed'
    assert len(read(db,"SELECT * FROM dnf_gm.audit WHERE action='campaign-cancel'"))==1
