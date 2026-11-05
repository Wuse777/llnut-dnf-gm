"""Account lists expand to a frozen role set, not a repeated account credit."""
import pytest
from test_combined_rewards import enable, read, write
from test_reward_jobs import job_preview, start, extra_role
from test_schedules import scheduled, preview, activate, trigger
P='/dnf-gm/api/v1'


def test_uid_list_deduplicates_accounts_but_preserves_all_roles(env):
    c,s,db,app=env;enable(s);extra_role(db)
    j=job_preview(c,targets={'mode':'accounts','account_uids':[900001,900001]})
    assert (j['target_count'],j['account_count'])==(2,1)
    assert j['preview']['account_selection']=={'input_kind':'account_uids','requested_accounts':1,'duplicates_removed':1}
    assert j['preview']['currency_totals']=={'cera':'100'}
    assert start(c,j).status_code==200
    for _ in range(3):app.state.reward_jobs.step()
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100
    assert len(read(db,'SELECT * FROM taiwan_cain_2nd.postal'))==2


def test_names_exact_match_and_freeze_before_later_roles(env):
    c,s,db,app=env;enable(s)
    write(db,"INSERT INTO d_taiwan.accounts VALUES(900004,'GM_M0_FIXTURE')")
    j=job_preview(c,targets={'mode':'accounts','account_names':['gm_m0_fixture','gm_m0_fixture']})
    assert j['target_count']==1 and j['preview']['duplicates_removed']==1
    extra_role(db)
    assert len(c.get(P+'/reward-jobs/'+j['id']+'/targets').json()['items'])==1


def test_numeric_account_name_not_interpreted_as_uid(env):
    c,s,db,app=env
    write(db,"UPDATE d_taiwan.accounts SET accountname='900002' WHERE UID=900001")
    j=job_preview(c,targets={'mode':'accounts','account_names':['900002']})
    targets=c.get(P+'/reward-jobs/'+j['id']+'/targets').json()['items']
    assert targets[0]['target_uid']==900001


@pytest.mark.parametrize('targets',[
 {'mode':'accounts'}, {'mode':'accounts','account_uids':[900001],'account_names':['gm_m0_fixture']},
 {'mode':'accounts','account_uids':[900001],'charac_nos':[900001]},
 {'mode':'accounts','account_uids':[900001],'min_level':1},
 {'mode':'accounts','account_uids':[0]}, {'mode':'accounts','account_uids':[True]},
 {'mode':'selected','charac_nos':[900001],'account_uids':[900001]},
 {'mode':'all','account_names':['gm_m0_fixture']},
 {'mode':'accounts','account_names':['bad\nname']},
 {'mode':'accounts','account_names':[' ']},
 {'mode':'accounts','account_names':['x'*256]},
 {'mode':'accounts','account_names':["x' OR 1=1 --"]},
 {'mode':'accounts','account_names':['gm_m0_fixture','missing']},
 {'mode':'accounts','account_uids':[900001,999999]},
])
def test_invalid_mixed_or_missing_accounts_do_not_create_partial_jobs(env,targets):
    c,s,db,app=env
    r=c.post(P+'/reward-jobs/preview',json={'targets':targets,'reward':{'gold':1},'reason':'fixture'})
    assert r.status_code==422,r.text
    assert not read(db,'SELECT id FROM dnf_gm.reward_jobs')
    assert not read(db,'SELECT job_id FROM dnf_gm.reward_targets')
    assert len(read(db,'SELECT UID FROM d_taiwan.accounts'))==2


def test_account_without_role_refuses_whole_list_not_silent_shrink(env):
    c,s,db,app=env
    write(db,"INSERT INTO d_taiwan.accounts VALUES(900003,'empty_account')")
    r=c.post(P+'/reward-jobs/preview',json={'targets':{'mode':'accounts','account_uids':[900001,900003]},'reward':{'gold':1},'reason':'fixture'})
    assert r.status_code==422 and '名单未被静默缩减' in r.text
    assert not read(db,'SELECT job_id FROM dnf_gm.reward_targets')
    write(db,'UPDATE taiwan_cain.charac_info SET delete_flag=1 WHERE m_id=900001')
    r=c.post(P+'/reward-jobs/preview',json={'targets':{'mode':'accounts','account_uids':[900001]},'reward':{'gold':1},'reason':'fixture'})
    assert r.status_code==422


def test_ambiguous_exact_name_refused(env):
    c,s,db,app=env
    write(db,"INSERT INTO d_taiwan.accounts VALUES(900003,'gm_m0_fixture')")
    r=c.post(P+'/reward-jobs/preview',json={'targets':{'mode':'accounts','account_names':['gm_m0_fixture']},'reward':{'gold':1},'reason':'fixture'})
    assert r.status_code==422 and '名称不唯一' in r.text


def test_per_character_requires_ack_and_test_target_restriction_still_applies(env):
    c,s,db,app=env;enable(s);extra_role(db)
    j=job_preview(c,targets={'mode':'accounts','account_uids':[900001]},account_reward_mode='per_character')
    assert j['preview']['currency_totals']=={'cera':'200'}
    assert start(c,j).status_code==422
    assert start(c,j,acknowledge_repeat=True).status_code==200
    other=job_preview(c,targets={'mode':'accounts','account_uids':[900001,900002]})
    assert start(c,other).status_code==403


def test_schedule_resolves_names_once_and_freezes_roles_at_due(scheduled):
    c,s,db,app,engine,now=scheduled
    item=preview(scheduled,reward_job={'targets':{'mode':'accounts','account_names':['gm_m0_fixture']},'reward':{'currency_rewards':{'cera':100},'gold':1},'reason':'scheduled account fixture'})
    assert item['request']['reward_job']['targets']['account_uids']==[900001]
    assert item['request']['reward_job']['targets']['account_names']==[]
    assert item['preview']['account_selection']['input_kind']=='account_names'
    assert activate(c,item).status_code==200
    write(db,"UPDATE d_taiwan.accounts SET accountname='renamed' WHERE UID=900001")
    write(db,"UPDATE d_taiwan.accounts SET accountname='gm_m0_fixture' WHERE UID=900002")
    extra_role(db);trigger(scheduled,item)
    rows=read(db,'SELECT target_uid FROM dnf_gm.reward_targets')
    assert len(rows)==2 and {r['target_uid'] for r in rows}=={900001}
    for _ in range(3):app.state.reward_jobs.step()
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1100


def test_schedule_account_role_loss_is_attention_not_silent_partial_reward(scheduled):
    c,s,db,app,engine,now=scheduled
    item=preview(scheduled,reward_job={'targets':{'mode':'accounts','account_uids':[900001]},'reward':{'gold':1},'reason':'fixture'})
    assert activate(c,item).status_code==200
    write(db,'UPDATE taiwan_cain.charac_info SET delete_flag=1 WHERE m_id=900001')
    trigger(scheduled,item)
    assert c.get(P+'/schedules/'+item['id']).json()['status']=='needs_attention'
    assert not read(db,'SELECT id FROM dnf_gm.reward_jobs')


def test_unicode_account_name_resolves_exactly_without_password_columns(env):
    c,s,db,app=env
    write(db,"UPDATE d_taiwan.accounts SET accountname=%s WHERE UID=900001",('测试账户',))
    job=job_preview(c,targets={'mode':'accounts','account_names':['测试账户']})
    targets=c.get(P+'/reward-jobs/'+job['id']+'/targets').json()['items']
    assert targets[0]['target_uid']==900001 and targets[0]['target']['accountname']=='测试账户'


def test_rollback_guard_checks_real_schedule_json(scheduled, tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('rollback_guard_integration', Path(__file__).parents[2] / 'deploy/check_rollback.py')
    guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
    c,s,db,app,engine,now=scheduled
    item=preview(scheduled,reward_job={'targets':{'mode':'accounts','account_names':['gm_m0_fixture']},'reward':{'gold':1},'reason':'rollback fixture'})
    with db.connect() as conn, conn.cursor() as q:
        with pytest.raises(guard.IncompatibleRollback): guard.check(q,tmp_path)
    write(db,"UPDATE dnf_gm.schedules SET status='cancelled' WHERE id=%s",(item['id'],))
    with db.connect() as conn, conn.cursor() as q:
        with pytest.raises(guard.IncompatibleRollback): guard.check(q,tmp_path)
    (tmp_path/'deploy').mkdir()
    (tmp_path/'deploy/release-features.json').write_text('{"schema_version":1,"reward_target_modes":["accounts"]}')
    with db.connect() as conn, conn.cursor() as q: guard.check(q,tmp_path)
