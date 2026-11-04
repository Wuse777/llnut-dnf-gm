"""Actual isolated MySQL transactions, not claims about in-game client effects."""
import json
import pytest
from test_mail_gold import P, preview, confirm, rows


def enable(settings):
    settings.writes=(*settings.writes,'reward','batch-reward')
    settings.write_approvals.update(reward=True,**{'batch-reward':True})
    settings.batch_worker_enabled=True


def read(db,sql,args=()):
    with db.connect() as c,c.cursor() as q:
        q.execute(sql,args)
        return list(q.fetchall())


def write(db,sql,args=()):
    with db.connect() as c,c.cursor() as q:
        q.execute(sql,args);c.commit()


def test_combined_all_currencies_mail_single_commit_and_idempotency(env):
    c,s,db,app=env;enable(s)
    r=preview(c,action='reward',currency_rewards={'cera':50,'cera_point':20,'mileage':30},items=[{'id':990002,'quantity':12345}])
    assert r.status_code==200,r.text
    assert r.json()['preview']['balances']['cera']['after']==1050
    op=r.json()['operation_id'];r=confirm(c,op);assert r.status_code==200,r.text
    assert r.json()['currency_rewards']['mileage']['after']==30
    assert confirm(c,op).json()==r.json()
    assert len(rows(db))==1 and rows(db)[0]['add_info']==12345
    assert len(read(db,'SELECT * FROM dnf_gm.audit WHERE operation_id=%s',(op,)))==1
    assert c.get(P+'/mail-center/'+op).status_code==200


def test_combined_mail_failure_rolls_back_every_currency(env,monkeypatch):
    c,s,db,app=env;enable(s)
    r=preview(c,action='reward',currency_rewards={'cera':50,'mileage':30});op=r.json()['operation_id']
    original=app.state.service.apply_mail
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('injected after mail writes')
    monkeypatch.setattr(app.state.service,'apply_mail',fail)
    assert confirm(c,op).status_code==500
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==1000
    assert not read(db,'SELECT * FROM d_taiwan.member_miles')
    assert not rows(db)
    assert not read(db,'SELECT * FROM dnf_gm.mail_batches')
    assert not read(db,'SELECT * FROM dnf_gm.audit WHERE operation_id=%s',(op,))


def test_combined_requires_explicit_permissions_and_stale_balance_repreview(env):
    c,s,db,app=env
    r=preview(c,action='reward',gold=0,currency_rewards={'cera':50});op=r.json()['operation_id']
    assert confirm(c,op).status_code==403
    enable(s)
    r=preview(c,action='reward',gold=0,currency_rewards={'cera':50});op=r.json()['operation_id']
    write(db,"UPDATE taiwan_billing.cash_cera SET cera=999")
    assert confirm(c,op).status_code==409
    assert read(db,'SELECT cera FROM taiwan_billing.cash_cera')[0]['cera']==999


def test_currency_only_versioned_template_and_no_implicit_mail_downgrade(env):
    c,s,db,app=env;enable(s)
    r=c.post(P+'/gift-templates',json={'name':'Currency gift','expected_version':0,'currency_rewards':{'cera':10}})
    assert r.status_code==200,r.text
    tid=r.json()['id']
    assert preview(c,action='mail',gold=0,template_id=tid,template_version=1).status_code==422
    r=preview(c,action='reward',gold=0,charac_no=None,template_id=tid,template_version=1)
    assert r.status_code==200,r.text
    assert confirm(c,r.json()['operation_id']).status_code==200
    assert not rows(db)
    versions=c.get(P+f'/gift-templates/{tid}/versions').json()['items']
    assert versions[0]['payload']['currency_rewards']['cera']==10


@pytest.mark.parametrize('amount',[-1,True,1.1,1000000001])
def test_currency_reward_boundary(env,amount):
    assert preview(env[0],action='reward',currency_rewards={'cera':amount}).status_code==422
