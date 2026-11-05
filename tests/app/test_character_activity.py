import json
P='/dnf-gm/api/v1'


def test_role_activity_sparse_cursor_and_account_scope(env):
    client,_,db,_=env
    with db.connect() as c,c.cursor() as q:
        def add(i,role):
            q.execute("INSERT INTO dnf_gm.audit(operation_id,actor,action,target_uid,reason,request_json,result_json) VALUES(%s,'owner','mail',900001,'fixture',%s,'{}')",(f'{i:032x}',json.dumps({'charac_no':role} if role else {})))
        add(1,900001);add(2,None)
        for i in range(3,103):add(i,900002)
        c.commit()
    first=client.get(P+'/characters/900001/activity').json()
    assert first['items']==[] and first['next_before'] is not None and first['scanned']==100
    second=client.get(P+'/characters/900001/activity',params={'before':first['next_before']}).json()
    assert [x['scope'] for x in second['items']]==['account','character']
    assert second['next_before'] is None
    only=client.get(P+'/characters/900001/activity',params={'before':first['next_before'],'include_account':False}).json()
    assert len(only['items'])==1 and only['items'][0]['operation_id']==f'{1:032x}'
    assert client.get(P+'/characters/2147483647/activity').status_code==404
