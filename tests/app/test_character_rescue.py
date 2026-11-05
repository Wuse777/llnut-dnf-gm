"""Minimal location transaction checks, synthetic MySQL5.7 only."""
import json
import pytest
from test_inventory_operations import inv, P

BASE=P+'/character-rescues'

@pytest.fixture
def rescue(inv):
    client,s,db,app,root=inv
    s.writes=(*s.writes,'char-rescue');s.write_approvals['char-rescue']=True
    app.state.character_rescue.fence=app.state.inventory_operations.fence
    with db.connect() as c,c.cursor() as q:
        q.execute('UPDATE taiwan_cain.charac_info SET village=6 WHERE charac_no=900001')
        q.execute('INSERT INTO taiwan_cain.charac_stat(charac_no,village,village_prev,exp,fatigue) VALUES(900001,6,2,12345,77)')
        c.commit()
    return inv


def draft(rig):
    client=rig[0];r=client.get(BASE+'/characters/900001');assert r.status_code==200,r.text
    response=client.post(BASE+'/preview',json={'uid':900001,'charac_no':900001,'reference':r.json()['reference'],'reason':'合成位置救援'})
    assert response.status_code==200,response.text
    return response.json()['operation_id']


def test_rescue_updates_only_towns_and_preserves_original_result(rescue):
    client,s,db,app,root=rescue;op=draft(rescue);key={'idempotency_key':'rescue-synthetic-success'}
    route=BASE+'/operations/'+op+'/confirm';r=client.post(route,json=key)
    assert r.status_code==200,r.text
    assert r.json()['status']=='committed'
    assert client.post(route,json=key).json()==r.json()
    assert client.get(BASE+'/characters/900001').json()['archive']=={'format':'qf1031-location-1','selection_village':1,'saved_village':1,'previous_village':1}
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT exp,fatigue FROM taiwan_cain.charac_stat WHERE charac_no=900001');assert q.fetchone()=={'exp':12345,'fatigue':77}
        q.execute('SELECT before_blob,after_blob FROM dnf_gm.inventory_snapshots WHERE operation_id=%s',(op,));row=q.fetchone()
        assert json.loads(row['before_blob'])['saved_village']==6
        assert json.loads(row['after_blob'])['saved_village']==1
    assert client.post(P+'/operations/'+op+'/confirm',json=key).status_code==409
    current=client.get(BASE+'/characters/900001').json()
    assert client.post(BASE+'/preview',json={'uid':900001,'charac_no':900001,'reference':current['reference'],'reason':'已恢复不重复'}).status_code==422


def test_rescue_failed_transaction_rolls_back_both_town_records(rescue,monkeypatch):
    client,s,db,app,root=rescue;op=draft(rescue)
    apply=app.state.character_rescue.apply_archive
    def fail(*args):apply(*args);raise RuntimeError('synthetic interruption before commit')
    monkeypatch.setattr(app.state.character_rescue,'apply_archive',fail)
    r=client.post(BASE+'/operations/'+op+'/confirm',json={'idempotency_key':'rescue-synthetic-failure'})
    assert r.status_code==500
    assert client.get(BASE+'/characters/900001').json()['archive']=={'format':'qf1031-location-1','selection_village':6,'saved_village':6,'previous_village':2}
    with db.connect() as c,c.cursor() as q:
        q.execute('SELECT COUNT(*) AS n FROM dnf_gm.inventory_snapshots');assert q.fetchone()['n']==0
