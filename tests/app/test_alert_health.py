import time
from fastapi.testclient import TestClient
from dnfgm.alerts import new_state,observe,observations,atomic,public_view

P='/dnf-gm/api/v1/alerts'


def test_authenticated_report_readonly_stale_and_safe(env,tmp_path):
    c,s,db,app=env
    path=tmp_path/'alerts.json';s.alert_file=str(path)
    assert c.get(P).json()['state']=='unavailable'
    now=time.time();state=new_state()
    observe(state,observations({'collected_at':now,'core_ok':True},True,now,{'memory':256,'swap':1536,'disk':2}),now)
    atomic(path,public_view(state,now),0o644)
    r=c.get(P);assert r.status_code==200 and r.json()['state']=='ok'
    assert len(r.json()['rules'])==6
    old=public_view(state,now);old['updated_at']=now-300;atomic(path,old)
    assert c.get(P).json()['state']=='stale'
    assert c.post(P,json={}).status_code==405
    with TestClient(app) as anon:
        assert anon.get(P).status_code==401


def test_report_exceptions_redacted_and_rate_limited(env,tmp_path):
    c,s,db,app=env;s.alert_file=str(tmp_path/'private-credentials.json')
    r=c.get(P);assert 'private-credentials' not in r.text
    assert r.json()['rules']==[]
    results=[c.get(P).status_code for _ in range(31)]
    assert 429 in results
