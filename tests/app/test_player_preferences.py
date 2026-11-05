"""Only the new navigation path: persistence/ownership/no game changes."""
from dnfgm.player_preferences import PlayerPreferences
P='/dnf-gm/api/v1/players'


def test_saved_targets_persist_and_never_create_rewards(env):
    c,s,db,app=env
    target={'uid':900001,'charac_no':900001}
    assert c.post(P+'/visit',json=target).status_code==200
    assert c.put(P+'/favorite',json={**target,'favorite':True}).status_code==200
    result=c.get(P+'/collections?collection=favorites').json()
    assert result['total']==1 and result['items'][0]['available'] is True
    assert result['items'][0]['character']['charac_no']==900001
    assert PlayerPreferences(db).list('recent')['items'][0]['uid']==900001
    assert c.put(P+'/favorite',json={**target,'favorite':False}).status_code==200
    assert c.get(P+'/collections?collection=favorites').json()['total']==0
    assert c.get(P+'/collections?collection=recent').json()['total']==1
    with db.connect() as con,con.cursor() as q:
        for name in ('operations','audit','mail_batches'):
            q.execute('SELECT COUNT(*) n FROM dnf_gm.'+name);assert q.fetchone()['n']==0
        q.execute('SELECT cera FROM taiwan_billing.cash_cera WHERE account=900001');assert q.fetchone()['cera']==1000


def test_invalid_or_removed_targets_cannot_be_reused_but_can_be_unpinned(env):
    c,s,db,app=env
    target={'uid':900001,'charac_no':900001}
    assert c.put(P+'/favorite',json={**target,'favorite':True}).status_code==200
    assert c.post(P+'/visit',json={'uid':900002,'charac_no':900001}).status_code==409
    assert c.post(P+'/visit',json={'uid':True}).status_code==422
    with db.connect() as con,con.cursor() as q:
        q.execute('UPDATE taiwan_cain.charac_info SET delete_flag=1 WHERE charac_no=900001');con.commit()
    assert c.get(P+'/collections?collection=favorites').json()['items'][0]['available'] is False
    assert c.post(P+'/visit',json=target).status_code==409
    assert c.put(P+'/favorite',json={**target,'favorite':False}).status_code==200
    assert c.get(P+'/collections?collection=favorites').json()['total']==0
    c.cookies.clear()
    assert c.get(P+'/collections').status_code==401
