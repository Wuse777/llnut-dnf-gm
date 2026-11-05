"""Mail subject is an explicit first line; no nonexistent native subject field."""
from test_mail_gold import P,preview,confirm
from test_combined_rewards import read,enable
from test_reward_jobs import job_preview,start


def test_title_template_roundtrip_override_and_delivery(env):
    c,s,db,app=env;enable(s)
    gift={'name':'title fixture','expected_version':0,'items':[], 'gold':1,
          'mail_title':'Welcome','message':'Your reward'}
    r=c.post(P+'/gift-templates',json=gift);assert r.status_code==200,r.text
    tid=r.json()['id']
    assert c.get(P+f'/gift-templates/{tid}/versions').json()['items'][0]['payload']['mail_title']=='Welcome'
    r=preview(c,gold=0,template_id=tid,template_version=1)
    assert r.status_code==200,r.text
    assert r.json()['preview']['mail_text']=='Welcome\nYour reward'
    op=r.json()['operation_id'];assert confirm(c,op).status_code==200
    assert read(db,'SELECT letter_text FROM taiwan_cain_2nd.letter')[0]['letter_text']=='Welcome\nYour reward'
    details=c.get(P+'/mail-center/'+op).json()['batch']
    assert details['message']=='Welcome\nYour reward' and details['request']['mail_title']=='Welcome'
    assert details['request']['message']=='Your reward'
    # Batch uses the same composer and preserves an explicit one-off subject.
    j=job_preview(c,reward={'template_id':tid,'template_version':1,'template_overrides':{
        'items':[],'gold':2,'mail_title':'Compensation','message':'Adjusted','currency_rewards':{}}})
    assert j['preview']['mail_text']=='Compensation\nAdjusted'
    assert start(c,j).status_code==200
    for _ in range(2):app.state.reward_jobs.step()
    assert read(db,'SELECT letter_text FROM taiwan_cain_2nd.letter ORDER BY letter_id DESC')[0]['letter_text']=='Compensation\nAdjusted'


def test_title_bounds_and_legacy_empty_title(env):
    c,_,db,_=env
    # Both field lengths are valid, but their UTF-8 representation exceeds the game field.
    assert preview(c,mail_title='a'*40,message='😀'*60).status_code==422
    assert preview(c,mail_title='line\nbreak').status_code==422
    r=preview(c,mail_title='',message='Legacy body');assert r.status_code==200,r.text
    assert 'mail_text' not in r.json()['preview']
    assert confirm(c,r.json()['operation_id']).status_code==200
    assert read(db,'SELECT letter_text FROM taiwan_cain_2nd.letter')[0]['letter_text']=='Legacy body'
