from fastapi.testclient import TestClient
from dnfgm.observer_policy import PATH
from dnfgm.capability_policy import PolicyUpdate,SWITCHES


def test_owner_switches_exposed_only_to_authenticated_local_observer(env):
    _,s,_,app=env;s.task_probe_token='a'*64
    policy=app.state.capability_policy
    policy.update(PolicyUpdate(request_id='f'*32,expected_revision=0,enabled=list(SWITCHES),reason='Enable owner capabilities').model_dump())
    probe=TestClient(app,client=('127.0.0.1',1234))
    headers={'Authorization':'Bearer '+s.task_probe_token}
    try:
        result=probe.get(PATH,headers=headers)
        assert result.status_code==200
        assert set(result.json())=={'revision','checked_at','enabled'}
        assert set(result.json()['enabled'])=={'health-alerts','backup-alerts','task-alerts'}
        assert probe.get(PATH).status_code==404
        assert probe.get(PATH,headers={**headers,'Origin':'http://testserver'}).status_code==404
        assert probe.get(PATH+'?query=1',headers=headers).status_code==404
    finally:probe.close()
