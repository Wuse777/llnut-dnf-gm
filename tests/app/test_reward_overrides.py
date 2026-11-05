"""Focused template draft tests; uses only the isolated MySQL fixture."""
import json
from test_mail_gold import P, preview, confirm, rows
from test_combined_rewards import enable, read
from test_reward_jobs import job_preview, start, extra_role


def gift(c):
    r=c.post(P+'/gift-templates',json={'name':'Original','expected_version':0,
        'items':[{'id':990002,'quantity':2}],'gold':12,'message':'original',
        'currency_rewards':{'cera':10}})
    assert r.status_code==200,r.text
    return r.json()['id']


def adjusted():
    return {'items':[{'id':990002,'quantity':200}], 'gold':50,
            'message':'one-off', 'currency_rewards':{'cera':25}}


def test_adjusted_reward_retains_source_and_never_mutates_template(env):
    c,s,db,app=env;enable(s);tid=gift(c)
    r=preview(c,action='reward',gold=0,template_id=tid,template_version=1,template_overrides=adjusted())
    assert r.status_code==200,r.text
    assert r.json()['preview']['template_source']=={'id':tid,'version':1,'adjusted':True}
    op=r.json()['operation_id'];r=confirm(c,op);assert r.status_code==200,r.text
    assert rows(db)[0]['gold']==50 and rows(db)[0]['add_info']==200
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1025
    audit=json.loads(read(db,'SELECT request_json FROM dnf_gm.audit WHERE operation_id=%s',(op,))[0]['request_json'])
    assert audit['template_id']==tid and audit['template_overrides']['message']=='one-off'
    versions=c.get(P+f'/gift-templates/{tid}/versions').json()['items']
    assert len(versions)==1 and versions[0]['payload']['gold']==12
    assert versions[0]['payload']['items'][0]['quantity']==2


def test_adjusted_reward_requires_source_and_still_checks_current_version(env):
    c,s,db,app=env;enable(s)
    assert preview(c,action='reward',gold=0,template_overrides=adjusted()).status_code==422
    tid=gift(c)
    assert preview(c,action='reward',gold=0,template_id=tid,template_version=99,template_overrides=adjusted()).status_code==409
    r=preview(c,action='reward',gold=0,template_id=tid,template_version=1,template_overrides={**adjusted(),'items':[{'id':999999,'quantity':1}]})
    assert r.status_code in (409,422),r.text


def test_adjusted_batch_credits_once_and_delivers_each_character(env):
    c,s,db,app=env;enable(s);extra_role(db);tid=gift(c)
    j=job_preview(c,targets={'mode':'selected','charac_nos':[900001,900003]},
                  reward={'template_id':tid,'template_version':1,'template_overrides':adjusted()})
    assert j['preview']['currency_totals']=={'cera':'25'} and j['preview']['gold_total']=='100'
    r=start(c,j);assert r.status_code==200,r.text
    for _ in range(3):app.state.reward_jobs.step()
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1025
    assert len(rows(db))==2 and all(r['gold']==50 and r['add_info']==200 for r in rows(db))
