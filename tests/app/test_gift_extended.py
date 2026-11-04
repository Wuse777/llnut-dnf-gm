from test_mail_gold import P, preview, confirm, rows


def test_gold_only_template_message_version_and_history(env):
    c,s,db,app=env
    data=dict(name='补偿礼包',expected_version=0,enabled=True,items=[],gold=456,message='Compensation',category='补偿')
    response=c.post(P+'/gift-templates',json=data);assert response.status_code==200,response.text
    tid=response.json()['id']
    response=preview(c,gold=0,template_id=tid,template_version=1)
    assert response.status_code==200,response.text
    op=response.json()['operation_id'];assert response.json()['preview']['gold']==456
    assert confirm(c,op).status_code==200
    assert rows(db)[0]['gold']==456 and rows(db)[0]['item_id']==0
    mail=c.get(P+'/mail-center/'+op).json()['batch'];assert mail['message']=='Compensation'
    data.update(expected_version=1,gold=789,message='Updated')
    assert c.put(P+f'/gift-templates/{tid}',json=data).status_code==200
    versions=c.get(P+f'/gift-templates/{tid}/versions').json()['items']
    assert [v['payload']['gold'] for v in versions]==[789,456]
    assert versions[1]['payload']['message']=='Compensation'
    assert versions[1]['payload']['name']=='补偿礼包'


def test_bound_template_rejects_silent_gold_override_and_stale_version(env):
    c,s,db,app=env
    data=dict(name='Fixed',items=[],gold=10,expected_version=0)
    tid=c.post(P+'/gift-templates',json=data).json()['id']
    assert preview(c,gold=20,template_id=tid,template_version=1).status_code==409
    op=preview(c,gold=0,template_id=tid,template_version=1).json()['operation_id']
    assert c.put(P+f'/gift-templates/{tid}',json={**data,'gold':11,'expected_version':1}).status_code==200
    assert confirm(c,op).status_code==409
    assert not rows(db)


def test_empty_gold_template_and_invalid_gold_rejected(env):
    c,s,db,app=env
    for gold in (0,-1,1000000001,True):
        r=c.post(P+'/gift-templates',json=dict(name='empty',expected_version=0,items=[],gold=gold))
        assert r.status_code==422,r.text


def test_template_category_filter_is_exact_and_parameterized(env):
    c,s,db,app=env
    for category in ('补偿','测试'):
        assert c.post(P+'/gift-templates',json=dict(name=category,expected_version=0,items=[],gold=1,category=category)).status_code==200
    data=c.get(P+'/gift-templates',params={'category':'补偿'}).json()
    assert len(data['items'])==1 and data['items'][0]['rewards']['category']=='补偿'
    assert c.get(P+'/gift-templates',params={'category':"' OR 1=1 --"}).json()['items']==[]
